import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import '../core/connection.dart';
import '../core/geometry.dart';
import '../core/store.dart';

class RemoteScreen extends StatefulWidget {
  final PairedPc pc;
  final Settings settings;
  const RemoteScreen({super.key, required this.pc, required this.settings});
  @override
  State<RemoteScreen> createState() => _RemoteScreenState();
}

class _RemoteScreenState extends State<RemoteScreen> {
  late final RemoteConnection conn;
  bool toolbar = true, keyboard = false, extraKeys = false, panMode = false;
  late bool trackpad;
  double zoom = 1;
  Offset pan = Offset.zero;
  Size viewSize = Size.zero;
  final _kbFocus = FocusNode();
  final _kbCtl = TextEditingController(text: _sentinel);
  static const _sentinel = '​';
  final Set<String> mods = {}; // sticky modifiers (one-shot)

  // gesture state
  final Map<int, Offset> _ptrs = {};
  Offset _downPos = Offset.zero;
  DateTime _downTime = DateTime.now();
  bool _moved = false, _dragging = false, _longFired = false, _twoActive = false, _twoMoved = false, _pinching = false;
  Timer? _longTimer;
  double _d0 = 1, _z0 = 1;
  Offset _c0 = Offset.zero, _lastC = Offset.zero, _pan0 = Offset.zero;
  DateTime _twoDown = DateTime.now();

  @override
  void initState() {
    super.initState();
    trackpad = widget.settings.trackpad;
    conn = RemoteConnection(widget.pc, widget.settings)..addListener(() => mounted ? setState(() {}) : null);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    conn.start();
  }

  @override
  void dispose() {
    _longTimer?.cancel();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    conn.dispose();
    _kbFocus.dispose();
    _kbCtl.dispose();
    super.dispose();
  }

  ViewGeometry get geo => ViewGeometry(viewSize, conn.remoteSize, zoom: zoom, pan: pan);

  // ---------------- gestures ----------------
  void _down(PointerDownEvent e) {
    _ptrs[e.pointer] = e.localPosition;
    if (_ptrs.length == 1) {
      _downPos = e.localPosition;
      _downTime = DateTime.now();
      _moved = _dragging = _longFired = false;
      _longTimer?.cancel();
      _longTimer = Timer(const Duration(milliseconds: 450), _onLong);
    } else if (_ptrs.length == 2) {
      _longTimer?.cancel();
      if (_dragging) _endDrag();
      final pts = _ptrs.values.toList();
      _twoActive = true;
      _twoMoved = _pinching = false;
      _twoDown = DateTime.now();
      _d0 = math.max(1, (pts[0] - pts[1]).distance);
      _z0 = zoom;
      _pan0 = pan;
      _c0 = _lastC = (pts[0] + pts[1]) / 2;
    }
  }

  void _onLong() {
    if (_ptrs.length != 1 || _moved || panMode) return;
    HapticFeedback.mediumImpact();
    _longFired = true;
    if (trackpad) {
      conn.button('left', true); // press-and-hold then move = drag
      _dragging = true;
    } else {
      conn.moveAbs(geo.toNormalized(_downPos));
      conn.click('right');
    }
  }

  void _endDrag() {
    if (_dragging) conn.button('left', false);
    _dragging = false;
  }

  void _move(PointerMoveEvent e) {
    if (!_ptrs.containsKey(e.pointer)) return;
    final prev = _ptrs[e.pointer]!;
    _ptrs[e.pointer] = e.localPosition;
    if (_ptrs.length == 1) {
      final d = e.localPosition - prev;
      if (!_moved && (e.localPosition - _downPos).distance > 10) {
        _moved = true;
        if (!_longFired) _longTimer?.cancel();
        if (!trackpad && !panMode) {
          conn.moveAbs(geo.toNormalized(_downPos));
          conn.button('left', true);
          _dragging = true;
        }
      }
      if (!_moved) return;
      if (panMode) {
        _setPan(pan + d, zoom);
      } else if (trackpad) {
        final k = geo.remotePerScreenPixel() * widget.settings.sensitivity;
        conn.moveRel(d.dx * k, d.dy * k);
      } else {
        conn.moveAbs(geo.toNormalized(e.localPosition));
      }
    } else if (_ptrs.length == 2 && _twoActive) {
      final pts = _ptrs.values.toList();
      final dist = math.max(1, (pts[0] - pts[1]).distance);
      final c = (pts[0] + pts[1]) / 2;
      final ratio = dist / _d0;
      if (!_pinching && (ratio - 1).abs() > 0.12) _pinching = true;
      if ((c - _c0).distance > 8 || (ratio - 1).abs() > 0.05) _twoMoved = true;
      if (_pinching) {
        final nz = (_z0 * ratio).clamp(1.0, 6.0);
        // keep the content point under the initial centroid fixed
        final content = (_c0 - _pan0) / _z0;
        _setPan(c - content * nz, nz);
      } else if (_twoMoved) {
        final dy = c.dy - _lastC.dy, dx = c.dx - _lastC.dx;
        final sign = widget.settings.naturalScroll ? 1.0 : -1.0;
        conn.scroll(-sign * dx / 40, sign * dy / 40);
      }
      _lastC = c;
    }
  }

  void _setPan(Offset p, double z) {
    final g = ViewGeometry(viewSize, conn.remoteSize);
    setState(() {
      zoom = z;
      pan = g.clampPan(p, z);
    });
  }

  void _up(PointerUpEvent e) {
    final wasTwo = _ptrs.length == 2;
    _ptrs.remove(e.pointer);
    _longTimer?.cancel();
    if (wasTwo) {
      if (!_twoMoved && DateTime.now().difference(_twoDown).inMilliseconds < 350) {
        conn.moveAbs(trackpad ? conn.cursorNorm : geo.toNormalized(_lastC));
        conn.click('right');
      }
      _twoActive = false;
      return;
    }
    if (_ptrs.isNotEmpty) return;
    if (_dragging) {
      _endDrag();
    } else if (!_moved && !_longFired && !panMode && DateTime.now().difference(_downTime).inMilliseconds < 350) {
      if (!trackpad) conn.moveAbs(geo.toNormalized(e.localPosition));
      conn.click('left');
    }
  }

  void _cancel(PointerCancelEvent e) {
    _ptrs.remove(e.pointer);
    _longTimer?.cancel();
    _endDrag();
    _twoActive = false;
  }

  // ---------------- keyboard ----------------
  void _toggleKeyboard() {
    setState(() => keyboard = !keyboard);
    if (keyboard) {
      _kbFocus.requestFocus();
      SystemChannels.textInput.invokeMethod('TextInput.show');
    } else {
      _kbFocus.unfocus();
    }
  }

  void _onKbChanged(String v) {
    if (v.isEmpty) {
      _sendKey('Backspace');
    } else if (v.length > _sentinel.length) {
      final added = v.substring(_sentinel.length);
      for (final ch in added.characters) {
        if (ch == '\n') {
          _sendKey('Enter');
        } else if (mods.isNotEmpty && RegExp(r'^[a-zA-Z0-9]$').hasMatch(ch)) {
          final code = RegExp(r'[0-9]').hasMatch(ch) ? 'Digit$ch' : 'Key${ch.toUpperCase()}';
          _sendKey(code);
        } else {
          conn.text(ch);
        }
      }
    }
    _kbCtl.value = const TextEditingValue(text: _sentinel, selection: TextSelection.collapsed(offset: 1));
  }

  void _sendKey(String code) {
    for (final m in mods) {
      conn.key(m, true);
    }
    conn.tap(code);
    for (final m in mods.toList().reversed) {
      conn.key(m, false);
    }
    if (mods.isNotEmpty) setState(mods.clear);
  }

  void _toggleMod(String m) => setState(() => mods.contains(m) ? mods.remove(m) : mods.add(m));

  // ---------------- UI ----------------
  Color get _qualityColor {
    if (conn.state != ConnState.connected) return Colors.orange;
    if (conn.rttMs < 0) return Colors.grey;
    return conn.rttMs < 80 ? Colors.greenAccent : (conn.rttMs < 200 ? Colors.amber : Colors.redAccent);
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (!didPop) await _exit();
      },
      child: Scaffold(
        backgroundColor: Colors.black,
        resizeToAvoidBottomInset: false,
        body: Stack(children: [
          LayoutBuilder(builder: (context, c) {
            viewSize = Size(c.maxWidth, c.maxHeight);
            return Listener(
              behavior: HitTestBehavior.opaque,
              onPointerDown: _down,
              onPointerMove: _move,
              onPointerUp: _up,
              onPointerCancel: _cancel,
              child: ClipRect(child: _viewer()),
            );
          }),
          // hidden text field capturing the soft keyboard
          Positioned(
            left: -100, top: 0, width: 10, height: 10,
            child: keyboard
                ? TextField(
                    focusNode: _kbFocus,
                    controller: _kbCtl,
                    keyboardType: TextInputType.visiblePassword,
                    autocorrect: false,
                    enableSuggestions: false,
                    maxLines: null,
                    textInputAction: TextInputAction.newline,
                    onChanged: _onKbChanged,
                  )
                : const SizedBox.shrink(),
          ),
          if (conn.state != ConnState.connected || !conn.rendererReady) _overlay(),
          _topBar(),
          if (keyboard && extraKeys) Positioned(left: 0, right: 0, bottom: 0, child: _extraKeysBar()),
        ]),
      ),
    );
  }

  Widget _viewer() {
    final r = geo.fit;
    return Transform(
      transform: Matrix4.identity()..translateByDouble(pan.dx, pan.dy, 0, 1)..scaleByDouble(zoom, zoom, 1, 1),
      alignment: Alignment.topLeft,
      child: SizedBox(
        width: viewSize.width,
        height: viewSize.height,
        child: Stack(children: [
          if (conn.rendererReady)
            RTCVideoView(conn.renderer, objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain),
          if (conn.state == ConnState.connected && conn.remoteSize != Size.zero)
            Positioned(
              left: r.left + conn.cursorNorm.dx * r.width,
              top: r.top + conn.cursorNorm.dy * r.height,
              child: IgnorePointer(child: CustomPaint(size: const Size(18, 26), painter: _CursorPainter(1 / zoom))),
            ),
        ]),
      ),
    );
  }

  Widget _overlay() {
    final failed = conn.state == ConnState.failed;
    final msg = switch (conn.state) {
      ConnState.signaling => 'Contacting server…',
      ConnState.connecting => 'Connecting to ${widget.pc.name}…',
      ConnState.reconnecting => 'Reconnecting (${conn.retries}/5)…${conn.error != null ? '\n${conn.error}' : ''}',
      ConnState.failed => conn.error ?? 'Connection failed',
      ConnState.closed => 'Disconnected',
      _ => 'Starting…',
    };
    return Positioned.fill(
      child: ColoredBox(
        color: Colors.black87,
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (!failed && conn.state != ConnState.closed) const CircularProgressIndicator(),
            if (failed) const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
            const SizedBox(height: 16),
            Padding(padding: const EdgeInsets.symmetric(horizontal: 32), child: Text(msg, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white))),
            const SizedBox(height: 16),
            if (failed) FilledButton(onPressed: conn.reconnectNow, child: const Text('Try again')),
            TextButton(onPressed: _exit, child: const Text('Back')),
          ]),
        ),
      ),
    );
  }

  Future<void> _exit() async {
    await conn.disconnect();
    if (mounted) Navigator.of(context).pop();
  }

  Widget _topBar() {
    return Positioned(
      top: 0, left: 0, right: 0,
      child: SafeArea(
        child: Column(children: [
          if (toolbar)
            Container(
              margin: const EdgeInsets.all(6),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              decoration: BoxDecoration(color: Colors.black.withValues(alpha: .75), borderRadius: BorderRadius.circular(28)),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(tooltip: 'Disconnect', icon: const Icon(Icons.close, color: Colors.redAccent), onPressed: _exit),
                  Icon(Icons.circle, size: 10, color: _qualityColor),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Text(conn.state == ConnState.connected ? '${conn.rttMs < 0 ? '–' : conn.rttMs} ms · ${conn.fps.toStringAsFixed(0)} fps' : 'connecting',
                        style: const TextStyle(color: Colors.white70, fontSize: 12)),
                  ),
                  _tb(trackpad ? Icons.mouse : Icons.touch_app, trackpad ? 'Trackpad mode' : 'Touch mode', () => setState(() => trackpad = !trackpad)),
                  _tb(Icons.pan_tool_alt, 'Pan view', () => setState(() => panMode = !panMode), on: panMode),
                  _tb(Icons.zoom_out_map, 'Reset zoom', () => setState(() => (zoom = 1, pan = Offset.zero))),
                  _tb(Icons.keyboard, 'Keyboard', _toggleKeyboard, on: keyboard),
                  if (keyboard) _tb(Icons.keyboard_command_key, 'Extra keys', () => setState(() => extraKeys = !extraKeys), on: extraKeys),
                  PopupMenuButton<String>(
                    icon: const Icon(Icons.tune, color: Colors.white),
                    tooltip: 'Quality',
                    onSelected: (q) {
                      widget.settings.quality = q;
                      Store.saveSettings(widget.settings);
                      conn.sendCfg();
                    },
                    itemBuilder: (_) => [
                      for (final q in ['low', 'medium', 'high'])
                        CheckedPopupMenuItem(value: q, checked: widget.settings.quality == q, child: Text('Quality: $q')),
                    ],
                  ),
                  PopupMenuButton<String>(
                    icon: const Icon(Icons.more_vert, color: Colors.white),
                    tooltip: 'More',
                    onSelected: _more,
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'push', child: Text('Send phone clipboard to PC')),
                      PopupMenuItem(value: 'pull', child: Text('Copy PC clipboard to phone')),
                      PopupMenuItem(value: 'lock', child: Text('Lock PC…')),
                    ],
                  ),
                  if (conn.monitors.length > 1)
                    PopupMenuButton<int>(
                      icon: const Icon(Icons.monitor, color: Colors.white),
                      tooltip: 'Monitor',
                      onSelected: (i) => conn.sendCfg(monitorIdx: i),
                      itemBuilder: (_) => [
                        for (final m in conn.monitors) CheckedPopupMenuItem(value: m['i'] as int, checked: conn.monitor == m['i'], child: Text('Monitor ${(m['i'] as int) + 1} (${m['w']}×${m['h']})')),
                      ],
                    ),
                ]),
              ),
            ),
          GestureDetector(
            onTap: () => setState(() => toolbar = !toolbar),
            child: Container(
              width: 56, height: 18,
              decoration: BoxDecoration(color: Colors.black45, borderRadius: BorderRadius.circular(9)),
              child: Icon(toolbar ? Icons.expand_less : Icons.expand_more, size: 16, color: Colors.white70),
            ),
          ),
        ]),
      ),
    );
  }

  Future<void> _more(String a) async {
    final messenger = ScaffoldMessenger.of(context);
    if (a == 'push') {
      final d = await Clipboard.getData('text/plain');
      if (d?.text?.isNotEmpty ?? false) {
        conn.sendClipboard(d!.text!);
        messenger.showSnackBar(const SnackBar(content: Text('Clipboard sent to PC')));
      }
    } else if (a == 'pull') {
      conn.onClipboard = (s) {
        Clipboard.setData(ClipboardData(text: s));
        messenger.showSnackBar(const SnackBar(content: Text('PC clipboard copied to phone')));
      };
      conn.requestClipboard();
    } else if (a == 'lock') {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Lock the PC?'),
          content: const Text('The remote session will end showing the lock screen. You will need to sign in on the PC itself.'),
          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Lock'))],
        ),
      );
      if (ok == true) conn.lockPc();
    }
  }

  Widget _tb(IconData i, String tip, VoidCallback f, {bool on = false}) =>
      IconButton(tooltip: tip, icon: Icon(i, color: on ? Colors.lightBlueAccent : Colors.white), onPressed: f);

  Widget _extraKeysBar() {
    Widget k(String label, String code) => _keyBtn(label, () => _sendKey(code));
    Widget m(String label, String code) => _keyBtn(label, () => _toggleMod(code), on: mods.contains(code));
    Widget combo(String label, List<String> ms, String code) => _keyBtn(label, () => conn.combo(ms, code));
    return Container(
      color: Colors.black.withValues(alpha: .85),
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          m('Ctrl', 'ControlLeft'), m('Alt', 'AltLeft'), m('Shift', 'ShiftLeft'), m('Win', 'MetaLeft'),
          k('Esc', 'Escape'), k('Tab', 'Tab'), k('←', 'ArrowLeft'), k('↑', 'ArrowUp'), k('↓', 'ArrowDown'), k('→', 'ArrowRight'),
          k('Home', 'Home'), k('End', 'End'), k('PgUp', 'PageUp'), k('PgDn', 'PageDown'), k('Del', 'Delete'),
          combo('Copy', ['ControlLeft'], 'KeyC'), combo('Paste', ['ControlLeft'], 'KeyV'), combo('Cut', ['ControlLeft'], 'KeyX'),
          combo('Undo', ['ControlLeft'], 'KeyZ'), combo('All', ['ControlLeft'], 'KeyA'), combo('Save', ['ControlLeft'], 'KeyS'),
          combo('Alt+Tab', ['AltLeft'], 'Tab'), combo('Win+D', ['MetaLeft'], 'KeyD'), combo('TaskMgr', ['ControlLeft', 'ShiftLeft'], 'Escape'),
          for (var i = 1; i <= 12; i++) k('F$i', 'F$i'),
        ]),
      ),
    );
  }

  Widget _keyBtn(String label, VoidCallback f, {bool on = false}) => Padding(
        padding: const EdgeInsets.all(3),
        child: SizedBox(
          height: 34,
          child: FilledButton.tonal(
            style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                backgroundColor: on ? Colors.lightBlue : Colors.grey.shade800,
                foregroundColor: Colors.white),
            onPressed: f,
            child: Text(label),
          ),
        ),
      );
}

class _CursorPainter extends CustomPainter {
  final double scale;
  _CursorPainter(this.scale);
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(scale);
    final p = Path()
      ..moveTo(0, 0)
      ..lineTo(0, 22)
      ..lineTo(5, 17)
      ..lineTo(9, 26)
      ..lineTo(12, 24.5)
      ..lineTo(8, 16)
      ..lineTo(15, 16)
      ..close();
    canvas.drawPath(p, Paint()..color = Colors.black);
    canvas.drawPath(p, Paint()..color = Colors.white..style = PaintingStyle.stroke..strokeWidth = 1.5);
  }

  @override
  bool shouldRepaint(covariant _CursorPainter old) => old.scale != scale;
}
