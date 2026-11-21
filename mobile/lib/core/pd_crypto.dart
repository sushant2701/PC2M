// Pairing crypto — must match agent/pocketdesk_agent/crypto.py and ARCHITECTURE.md.
import 'dart:convert';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';

const _b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

class ParsedCode {
  final String lookup;
  final Uint8List secret;
  ParsedCode(this.lookup, this.secret);
}

/// Parses "LLLLLL-SSSS-SSSS-SSSS-SSSS" (dashes/spaces/case ignored). Throws FormatException.
ParsedCode parsePairingCode(String text) {
  final t = text.replaceAll(RegExp(r'[\s-]'), '').toUpperCase();
  if (t.length != 22 || t.split('').any((c) => !_b32.contains(c))) {
    throw const FormatException('Invalid pairing code');
  }
  return ParsedCode(t.substring(0, 6), base32Decode(t.substring(6)));
}

Uint8List base32Decode(String s) {
  var bits = 0, value = 0;
  final out = <int>[];
  for (final c in s.split('')) {
    value = (value << 5) | _b32.indexOf(c);
    bits += 5;
    if (bits >= 8) {
      out.add((value >> (bits - 8)) & 0xFF);
      bits -= 8;
    }
  }
  return Uint8List.fromList(out);
}

Uint8List hkdfSha256(List<int> ikm, List<int> salt, List<int> info, int length) {
  final prk = Hmac(sha256, salt).convert(ikm).bytes;
  final out = <int>[];
  var block = <int>[];
  var i = 1;
  while (out.length < length) {
    block = Hmac(sha256, prk).convert([...block, ...info, i]).bytes;
    out.addAll(block);
    i++;
  }
  return Uint8List.fromList(out.sublist(0, length));
}

Uint8List derivePairKey(List<int> secret) =>
    hkdfSha256(secret, utf8.encode('pocketdesk-pair-v1'), utf8.encode('pair-key'), 32);

String _mac(List<int> key, String msg) => Hmac(sha256, key).convert(utf8.encode(msg)).toString();

String claimProof(List<int> key, String lookup, String deviceName) => _mac(key, 'pd1|claim|$lookup|$deviceName');

String sdpFingerprint(String sdp) {
  final m = RegExp(r'^a=fingerprint:\S+\s+([0-9A-Fa-f:]+)\s*$', multiLine: true).firstMatch(sdp);
  if (m == null) throw const FormatException('no DTLS fingerprint in SDP');
  return m.group(1)!.toLowerCase();
}

String offerMac(List<int> key, String sid, String deviceId, int ts, String sdp) =>
    _mac(key, 'pd1|offer|$sid|$deviceId|$ts|${sdpFingerprint(sdp)}');

String answerMac(List<int> key, String sid, String deviceId, int ts, String sdp) =>
    _mac(key, 'pd1|answer|$sid|$deviceId|$ts|${sdpFingerprint(sdp)}');

bool constantTimeEquals(String a, String b) {
  if (a.length != b.length) return false;
  var r = 0;
  for (var i = 0; i < a.length; i++) {
    r |= a.codeUnitAt(i) ^ b.codeUnitAt(i);
  }
  return r == 0;
}

String hex(List<int> b) => b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
Uint8List unhex(String h) =>
    Uint8List.fromList([for (var i = 0; i < h.length; i += 2) int.parse(h.substring(i, i + 2), radix: 16)]);
