@TestOn('browser')
library;

// Real end-to-end test of the Flutter client protocol code (pairing, signaling, MAC-authenticated
// WebRTC session, control channel) against a REAL agent + signaling server, run in Chrome.
// Driven by tools/e2e_flutter_web.py which supplies server/code via --dart-define.
// ignore_for_file: avoid_print
import 'dart:ui';
import 'package:flutter_test/flutter_test.dart';
import 'package:pocketdesk/core/api.dart';
import 'package:pocketdesk/core/connection.dart';
import 'package:pocketdesk/core/store.dart';

const server = String.fromEnvironment('PD_SERVER');
const code = String.fromEnvironment('PD_CODE');

Future<void> until(bool Function() c, String what, {int secs = 25}) async {
  final end = DateTime.now().add(Duration(seconds: secs));
  while (!c()) {
    if (DateTime.now().isAfter(end)) fail('timeout waiting for $what');
    await Future.delayed(const Duration(milliseconds: 100));
  }
}

void main() {
  test('pair, connect, receive desktop video, send input', () async {
    final pc = await pairWithCode(server, code, 'Chrome Test Phone');
    final conn = RemoteConnection(pc, Settings(quality: 'low'));
    await conn.start();
    await until(() => conn.state == ConnState.connected, 'connected (state=${conn.state} err=${conn.error})');
    await until(() => conn.remoteSize != Size.zero, 'info message');
    await until(() => conn.renderer.videoWidth > 0, 'video frames', secs: 20);
    await until(() => conn.rttMs >= 0, 'ping/pong', secs: 10);
    // input: the harness watches the real cursor
    for (var i = 0; i < 40; i++) {
      conn.moveAbs(const Offset(0.3, 0.6));
      await Future.delayed(const Duration(milliseconds: 50));
    }
    conn.button('left', true);
    conn.button('left', false);
    conn.key('ShiftLeft', true);
    await Future.delayed(const Duration(milliseconds: 600));
    conn.key('ShiftLeft', false);
    print('E2E_OK video=${conn.renderer.videoWidth}x${conn.renderer.videoHeight} rtt=${conn.rttMs} remote=${conn.remoteSize}');
    await conn.disconnect();
  }, timeout: const Timeout(Duration(minutes: 2)));
}
