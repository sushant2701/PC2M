import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:ui';
import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'pd_crypto.dart';
import 'store.dart';

enum ConnState { idle, signaling, connecting, connected, reconnecting, failed, closed }

/// One remote-desktop connection: signaling WS -> offer/answer (MAC-authenticated) -> WebRTC video + control channel.
class RemoteConnection extends ChangeNotifier {
  final PairedPc pc;
  Settings settings;
  RemoteConnection(this.pc, this.settings);

  ConnState state = ConnState.idle;
  String? error;
  final renderer = RTCVideoRenderer();
  bool rendererReady = false;

  // remote info
  Size remoteSize = Size.zero;
  int monitor = 0;
  List<Map<String, dynamic>> monitors = [];
  Offset cursorNorm = Offset.zero; // 0..1
  double fps = 0;
  int rttMs = -1;
  int retries = 0;

  WebSocketChannel? _ws;
  RTCPeerConnection? _pc;
  RTCDataChannel? _dc;
  Timer? _pingTimer, _flushTimer;
  bool _disposed = false, _userClosed = false;
  int _pingN = 0;
  final Map<int, int> _pingSent = {};
  Completer<Map<String, dynamic>>? _answerWaiter;
  String _sessionId = '';
  int _ts = 0;

  // coalesced pointer output
  Offset? _pendingAbs;
  double _pendingDx = 0, _pendingDy = 0, _pendingWx = 0, _pendingWy = 0;

  void _set(ConnState s, [String? err]) {
    if (_disposed) return;
    state = s;
    error = err;
    notifyListeners();
  }

  Future<void> start() async {
    await renderer.initialize();
    rendererReady = true;
    _userClosed = false;
    retries = 0;
    await _connectOnce();
  }

  Future<void> _connectOnce() async {
    _set(retries == 0 ? ConnState.signaling : ConnState.reconnecting);
    try {
      await _teardown();
      final wsUrl = '${pc.serverUrl.replaceFirst('https://', 'wss://').replaceFirst('http://', 'ws://')}/ws';
      final ws = WebSocketChannel.connect(Uri.parse(wsUrl));
      _ws = ws;
      await ws.ready.timeout(const Duration(seconds: 12));
      ws.sink.add(jsonEncode({'type': 'auth', 'role': 'device', 'id': pc.deviceId, 'secret': pc.token}));
      final readyC = Completer<List>();
      ws.stream.listen((raw) {
        final m = jsonDecode(raw as String) as Map<String, dynamic>;
        switch (m['type']) {
          case 'ready':
            if (!readyC.isCompleted) readyC.complete(m['ice_servers'] as List);
            break;
          case 'answer':
            _answerWaiter?.complete(m);
            break;
          case 'error':
            if (m['error'] == 'auth') {
              _fail('Access revoked or credentials invalid. Re-pair this PC.', fatal: true);
            } else {
              _answerWaiter?.completeError(StateError('The PC rejected the request.'));
            }
            break;
          case 'agent_offline':
            _answerWaiter?.completeError(StateError('The PC is offline.'));
            break;
        }
      }, onDone: () {
        if (!readyC.isCompleted) readyC.completeError(StateError('Signaling closed'));
        if (state == ConnState.signaling || state == ConnState.connecting) {
          _answerWaiter?.completeError(StateError('Signaling closed'));
        }
      }, onError: (e) {
        if (!readyC.isCompleted) readyC.completeError(e);
      });
      final ice = await readyC.future.timeout(const Duration(seconds: 12));

      _set(ConnState.connecting);
      final conn = await createPeerConnection({
        'iceServers': ice,
        'sdpSemantics': 'unified-plan',
        'iceCandidatePoolSize': 0,
      });
      _pc = conn;
      _dc = await conn.createDataChannel('control', RTCDataChannelInit()..ordered = true);
      _dc!.onMessage = _onDcMessage;
      _dc!.onDataChannelState = (s) {
        if (s == RTCDataChannelState.RTCDataChannelOpen) _onDcOpen();
      };
      await conn.addTransceiver(
          kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
          init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly));
      conn.onTrack = (e) {
        if (e.track.kind == 'video' && e.streams.isNotEmpty) {
          renderer.srcObject = e.streams[0];
          notifyListeners();
        }
      };
      conn.onConnectionState = (s) {
        if (_disposed || _userClosed) return;
        if (s == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          retries = 0;
          _set(ConnState.connected);
        } else if (s == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            s == RTCPeerConnectionState.RTCPeerConnectionStateClosed) {
          _scheduleReconnect('Connection lost');
        } else if (s == RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          Future.delayed(const Duration(seconds: 6), () {
            if (!_disposed && !_userClosed && _pc == conn &&
                conn.connectionState == RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
              _scheduleReconnect('Connection lost');
            }
          });
        }
      };

      final gathered = Completer<void>();
      conn.onIceGatheringState = (s) {
        if (s == RTCIceGatheringState.RTCIceGatheringStateComplete && !gathered.isCompleted) gathered.complete();
      };
      final offer = await conn.createOffer();
      await conn.setLocalDescription(offer);
      await gathered.future.timeout(const Duration(seconds: 8), onTimeout: () {});
      final local = await conn.getLocalDescription();
      final sdp = local!.sdp!;
      final key = unhex(pc.pairKeyHex);
      _sessionId = hex(List<int>.generate(16, (_) => Random.secure().nextInt(256)));
      _ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      _answerWaiter = Completer();
      ws.sink.add(jsonEncode({
        'type': 'offer', 'agent_id': pc.agentId, 'session_id': _sessionId, 'ts': _ts, 'sdp': sdp,
        'mac': offerMac(key, _sessionId, pc.deviceId, _ts, sdp),
      }));
      final ans = await _answerWaiter!.future.timeout(const Duration(seconds: 25));
      if (ans['session_id'] != _sessionId ||
          !constantTimeEquals(answerMac(key, _sessionId, pc.deviceId, _ts, ans['sdp']), '${ans['mac']}')) {
        _fail('Security check failed: the PC could not be verified.', fatal: true);
        return;
      }
      await conn.setRemoteDescription(RTCSessionDescription(ans['sdp'], 'answer'));
    } on TimeoutException {
      _scheduleReconnect('Timed out');
    } catch (e) {
      if (!_disposed && !_userClosed && state != ConnState.failed) _scheduleReconnect(e is StateError ? e.message : '$e');
    }
  }

  void _scheduleReconnect(String why) {
    if (_disposed || _userClosed || state == ConnState.failed) return;
    if (retries >= 5) {
      _fail('$why. Could not reconnect — check the PC is on and online.');
      return;
    }
    retries++;
    _set(ConnState.reconnecting, why);
    final delay = Duration(seconds: min(10, 1 << retries));
    Future.delayed(delay, () {
      if (!_disposed && !_userClosed && state == ConnState.reconnecting) _connectOnce();
    });
  }

  void _fail(String msg, {bool fatal = false}) {
    _teardown();
    _set(ConnState.failed, msg);
  }

  // ---------- data channel ----------
  void _onDcOpen() {
    sendCfg();
    _flushTimer = Timer.periodic(const Duration(milliseconds: 16), (_) => _flush());
    _pingTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      final n = ++_pingN;
      _pingSent[n] = DateTime.now().millisecondsSinceEpoch;
      _send({'t': 'ping', 'n': n});
    });
  }

  void _onDcMessage(RTCDataChannelMessage m) {
    if (m.isBinary) return;
    final j = jsonDecode(m.text) as Map<String, dynamic>;
    switch (j['t']) {
      case 'info':
        remoteSize = Size((j['w'] as num).toDouble(), (j['h'] as num).toDouble());
        monitor = j['monitor'] ?? 0;
        monitors = (j['monitors'] as List).cast<Map<String, dynamic>>();
        notifyListeners();
        break;
      case 'cur':
        cursorNorm = Offset((j['x'] as num).toDouble(), (j['y'] as num).toDouble());
        notifyListeners();
        break;
      case 'stats':
        fps = (j['fps'] as num).toDouble();
        notifyListeners();
        break;
      case 'clip':
        onClipboard?.call(j['s'] as String);
        break;
      case 'pong':
        final t0 = _pingSent.remove(j['n']);
        if (t0 != null) {
          rttMs = DateTime.now().millisecondsSinceEpoch - t0;
          notifyListeners();
        }
        break;
    }
  }

  void _send(Map<String, dynamic> m) {
    final dc = _dc;
    if (dc != null && dc.state == RTCDataChannelState.RTCDataChannelOpen) {
      dc.send(RTCDataChannelMessage(jsonEncode(m)));
    }
  }

  void sendCfg({int? monitorIdx}) {
    _send({'t': 'cfg', 'quality': settings.quality, 'monitor': ?monitorIdx});
  }

  // ---------- input API (coalesced to ~60 Hz) ----------
  void moveAbs(Offset n) => _pendingAbs = n;
  void moveRel(double dx, double dy) {
    _pendingDx += dx;
    _pendingDy += dy;
  }

  void scroll(double dx, double dy) {
    _pendingWx += dx;
    _pendingWy += dy;
  }

  void _flush() {
    final a = _pendingAbs;
    if (a != null) {
      _send({'t': 'mm', 'x': double.parse(a.dx.toStringAsFixed(5)), 'y': double.parse(a.dy.toStringAsFixed(5))});
      _pendingAbs = null;
    }
    if (_pendingDx.abs() >= 1 || _pendingDy.abs() >= 1) {
      final dx = _pendingDx.truncate(), dy = _pendingDy.truncate();
      _pendingDx -= dx;
      _pendingDy -= dy;
      _send({'t': 'mr', 'dx': dx, 'dy': dy});
    }
    if (_pendingWx.abs() >= 0.1 || _pendingWy.abs() >= 0.1) {
      _send({'t': 'ws', 'dx': _pendingWx, 'dy': _pendingWy});
      _pendingWx = _pendingWy = 0;
    }
  }

  /// Flushes pending moves first so click lands at the intended position.
  void button(String b, bool down) {
    _flush();
    _send({'t': 'mb', 'b': b, 'd': down});
  }

  void click(String b, {int count = 1}) {
    for (var i = 0; i < count; i++) {
      button(b, true);
      button(b, false);
    }
  }

  void key(String code, bool down) => _send({'t': 'k', 'c': code, 'd': down});
  void tap(String code) {
    key(code, true);
    key(code, false);
  }

  void combo(List<String> mods, String code) {
    for (final m in mods) {
      key(m, true);
    }
    tap(code);
    for (final m in mods.reversed) {
      key(m, false);
    }
  }

  void text(String s) => _send({'t': 'tx', 's': s});

  void Function(String text)? onClipboard;
  void sendClipboard(String s) => _send({'t': 'clip', 's': s.length > 50000 ? s.substring(0, 50000) : s});
  void requestClipboard() => _send({'t': 'clipget'});
  void lockPc() => _send({'t': 'lock'});

  // ---------- lifecycle ----------
  Future<void> _teardown() async {
    _pingTimer?.cancel();
    _flushTimer?.cancel();
    final dc = _dc, p = _pc, ws = _ws;
    _dc = null;
    _pc = null;
    _ws = null;
    try {
      await dc?.close();
    } catch (_) {}
    try {
      await p?.close();
    } catch (_) {}
    try {
      await ws?.sink.close();
    } catch (_) {}
  }

  Future<void> reconnectNow() async {
    retries = 0;
    _userClosed = false;
    await _connectOnce();
  }

  Future<void> disconnect() async {
    _userClosed = true;
    _send({'t': 'bye'});
    await Future.delayed(const Duration(milliseconds: 100));
    await _teardown();
    _set(ConnState.closed);
  }

  @override
  void dispose() {
    _disposed = true;
    _userClosed = true;
    _teardown();
    renderer.srcObject = null;
    renderer.dispose();
    super.dispose();
  }
}
