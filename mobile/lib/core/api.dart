import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';
import 'pd_crypto.dart';
import 'store.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

/// https only in release builds; plain http permitted in debug (LAN testing).
String normalizeServerUrl(String url) {
  var u = url.trim().replaceAll(RegExp(r'/+$'), '');
  if (!u.contains('://')) u = 'https://$u';
  final uri = Uri.tryParse(u);
  if (uri == null || uri.host.isEmpty) throw ApiException('Invalid server URL');
  if (uri.scheme != 'https' && !(kDebugMode && uri.scheme == 'http')) {
    throw ApiException('Server must use https://');
  }
  return u;
}

Future<PairedPc> pairWithCode(String serverUrl, String code, String deviceName) async {
  final base = normalizeServerUrl(serverUrl);
  final ParsedCode p;
  try {
    p = parsePairingCode(code);
  } on FormatException {
    throw ApiException('That pairing code is not valid. It looks like ABCDEF-GHIJ-KLMN-OPQR-STUV.');
  }
  final key = derivePairKey(p.secret);
  final http.Response r;
  try {
    r = await http
        .post(Uri.parse('$base/api/pair/claim'),
            headers: {'content-type': 'application/json'},
            body: jsonEncode({'code': p.lookup, 'device_name': deviceName, 'proof': claimProof(key, p.lookup, deviceName)}))
        .timeout(const Duration(seconds: 15));
  } catch (e) {
    throw ApiException('Cannot reach the server. Check the URL and your connection.');
  }
  if (r.statusCode == 404) throw ApiException('Code is invalid or expired. Generate a new one on the PC.');
  if (r.statusCode == 409) throw ApiException('The PC is offline. Start PocketDesk Agent on it first.');
  if (r.statusCode == 429) throw ApiException('Too many attempts. Wait a minute and retry.');
  if (r.statusCode != 200) throw ApiException('Pairing failed (${r.statusCode}).');
  final j = jsonDecode(r.body);
  return PairedPc(serverUrl: base, agentId: j['agent_id'], name: j['agent_name'], deviceId: j['device_id'],
      token: j['device_token'], pairKeyHex: hex(key));
}

/// Returns true/false for online, null if the server is unreachable or the device was revoked.
Future<bool?> fetchOnline(PairedPc pc) async {
  try {
    final r = await http.get(Uri.parse('${pc.serverUrl}/api/status'),
        headers: {'Authorization': 'Bearer ${pc.deviceId}:${pc.token}'}).timeout(const Duration(seconds: 8));
    if (r.statusCode == 200) return jsonDecode(r.body)['online'] == true;
    if (r.statusCode == 401) throw ApiException('revoked');
    return null;
  } on ApiException {
    rethrow;
  } catch (_) {
    return null;
  }
}

Future<void> revokeSelf(PairedPc pc) async {
  try {
    await http.delete(Uri.parse('${pc.serverUrl}/api/devices/${pc.deviceId}'),
        headers: {'Authorization': 'Bearer ${pc.deviceId}:${pc.token}'}).timeout(const Duration(seconds: 8));
  } catch (_) {}
}
