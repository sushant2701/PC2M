import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class PairedPc {
  final String serverUrl, agentId, name, deviceId, token, pairKeyHex;
  PairedPc({required this.serverUrl, required this.agentId, required this.name, required this.deviceId,
      required this.token, required this.pairKeyHex});
  Map<String, dynamic> toJson() => {
        'serverUrl': serverUrl, 'agentId': agentId, 'name': name, 'deviceId': deviceId,
        'token': token, 'pairKeyHex': pairKeyHex,
      };
  factory PairedPc.fromJson(Map<String, dynamic> j) => PairedPc(
      serverUrl: j['serverUrl'], agentId: j['agentId'], name: j['name'], deviceId: j['deviceId'],
      token: j['token'], pairKeyHex: j['pairKeyHex']);
}

class Settings {
  String quality; // low|medium|high
  bool trackpad;
  double sensitivity;
  bool naturalScroll;
  String lastServer;
  Settings({this.quality = 'medium', this.trackpad = false, this.sensitivity = 1.4, this.naturalScroll = true,
      this.lastServer = ''});
  Map<String, dynamic> toJson() => {'quality': quality, 'trackpad': trackpad, 'sensitivity': sensitivity,
        'naturalScroll': naturalScroll, 'lastServer': lastServer};
  factory Settings.fromJson(Map<String, dynamic> j) => Settings(
      quality: j['quality'] ?? 'medium', trackpad: j['trackpad'] ?? false,
      sensitivity: (j['sensitivity'] ?? 1.4).toDouble(), naturalScroll: j['naturalScroll'] ?? true,
      lastServer: j['lastServer'] ?? '');
}

/// Secrets (device tokens, pair keys) live only in Android Keystore-backed secure storage.
class Store {
  static const _s = FlutterSecureStorage();
  static Future<List<PairedPc>> loadPcs() async {
    final raw = await _s.read(key: 'pcs');
    if (raw == null) return [];
    return (jsonDecode(raw) as List).map((e) => PairedPc.fromJson(e)).toList();
  }

  static Future<void> savePcs(List<PairedPc> pcs) => _s.write(key: 'pcs', value: jsonEncode(pcs.map((e) => e.toJson()).toList()));

  static Future<Settings> loadSettings() async {
    final raw = await _s.read(key: 'settings');
    return raw == null ? Settings() : Settings.fromJson(jsonDecode(raw));
  }

  static Future<void> saveSettings(Settings s) => _s.write(key: 'settings', value: jsonEncode(s.toJson()));
}
