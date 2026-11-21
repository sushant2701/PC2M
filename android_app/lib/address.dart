// Follows the PC's changing tunnel address. The PC announces its current address on a private ntfy.sh topic, signed per phone with
// the pair key (HMAC-SHA256 over "pd1|addr|<url>|<ts>"), so only an address announced by your own PC is ever followed.
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

String addrMac(String keyHex, String url, int ts) {
  final key = <int>[for (var i = 0; i < keyHex.length; i += 2) int.parse(keyHex.substring(i, i + 2), radix: 16)];
  return Hmac(sha256, key).convert(utf8.encode('pd1|addr|$url|$ts')).toString();
}

bool ctEq(String a, String b) {
  if (a.length != b.length) return false;
  var r = 0;
  for (var i = 0; i < a.length; i++) {
    r |= a.codeUnitAt(i) ^ b.codeUnitAt(i);
  }
  return r == 0;
}

/// Returns the newest validly-signed https address for any paired PC, or null.
String? pickAddress(List pcs, String ntfyPollBody, {int? nowSeconds}) {
  final now = nowSeconds ?? DateTime.now().millisecondsSinceEpoch ~/ 1000;
  for (final line in ntfyPollBody.trim().split('\n').reversed) {
    try {
      final ev = jsonDecode(line);
      if (ev['event'] != 'message') continue;
      final m = jsonDecode(ev['message'] as String);
      final url = m['u'] as String, ts = (m['ts'] as num).toInt();
      if (!url.startsWith('https://') || (now - ts).abs() > 7 * 24 * 3600) continue;
      for (final pc in pcs) {
        final mac = (m['m'] as Map?)?[pc['deviceId']];
        if (mac is String && ctEq(mac, addrMac(pc['keyHex'] as String, url, ts))) return url;
      }
    } catch (_) {}
  }
  return null;
}

Future<String?> discoverAddress(List pcs) async {
  for (final pc in pcs) {
    final topic = (pc['topic'] ?? '') as String;
    if (topic.isEmpty) continue;
    try {
      final r = await http.get(Uri.parse('https://ntfy.sh/$topic/json?poll=1&since=all')).timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) continue;
      final u = pickAddress(pcs, r.body);
      if (u != null) return u;
    } catch (_) {}
  }
  return null;
}
