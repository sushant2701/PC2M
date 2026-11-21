import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'address.dart';

// PocketDesk app: full-screen shell around the PocketDesk web client (which does the encrypted connection).
// The app adds: QR scan, keeps the screen awake, remembers your pairing natively, FOLLOWS the PC's changing address,
// and offers in-app updates. UI changes to the web client appear instantly (served live); APK updates are one tap.
void main() => runApp(const App());

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'PocketDesk',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorSchemeSeed: const Color(0xFF3D7A5A),
          brightness: Brightness.light,
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xFFF5F1EA),
          appBarTheme: const AppBarTheme(backgroundColor: Color(0xFFF5F1EA), foregroundColor: Color(0xFF2B2F2A), elevation: 0),
          filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)))),
          outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)))),
        ),
        home: const Boot(),
      );
}

String? normalizeLink(String raw) {
  final t = raw.trim();
  final u = Uri.tryParse(t.contains('://') ? t : 'https://$t');
  if (u == null || u.host.isEmpty || u.scheme != 'https') return null;
  return u.toString();
}

class Boot extends StatefulWidget {
  const Boot({super.key});
  @override
  State<Boot> createState() => _BootState();
}

class _BootState extends State<Boot> {
  String? origin;
  bool ready = false;
  int gen = 0;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) => setState(() {
          origin = p.getString('origin');
          ready = true;
        }));
  }

  Future<void> _set(String? o) async {
    final p = await SharedPreferences.getInstance();
    if (o == null) {
      await p.remove('origin');
      await p.remove('pcs');
    } else {
      await p.setString('origin', Uri.parse(o).origin);
    }
    setState(() {
      origin = o;
      gen++;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!ready) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (origin == null) return Welcome(onLink: _set);
    return Viewer(key: ValueKey(gen), startLink: origin!, onReset: () => _set(null), onNewLink: _set);
  }
}

class Welcome extends StatelessWidget {
  final Future<void> Function(String) onLink;
  const Welcome({super.key, required this.onLink});

  Future<void> _scan(BuildContext c) async {
    final r = await Navigator.of(c).push<String>(MaterialPageRoute(builder: (_) => const Scanner()));
    if (r == null) return;
    final l = normalizeLink(r);
    if (l == null) {
      if (c.mounted) ScaffoldMessenger.of(c).showSnackBar(const SnackBar(content: Text('That QR is not a PocketDesk link (it must start with https://).')));
      return;
    }
    final p = await SharedPreferences.getInstance();
    await p.setString('pending_link', l); // full link incl. one-time pairing code
    await onLink(l);
  }

  @override
  Widget build(BuildContext context) {
    final ctl = TextEditingController();
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 24),
          Row(children: [
            Container(
              width: 60, height: 60,
              decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFF4F9170), Color(0xFF2F6247)]), borderRadius: BorderRadius.circular(19), boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 14, offset: Offset(0, 6))]),
              alignment: Alignment.center,
              child: const Text('🖥', style: TextStyle(fontSize: 30)),
            ),
            const SizedBox(width: 14),
            const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('PocketDesk', style: TextStyle(fontSize: 30, fontWeight: FontWeight.bold, color: Color(0xFF2B2F2A), height: 1.1)),
              Text('Your PC, in your pocket', style: TextStyle(color: Color(0xFF6B7468))),
            ]),
          ]),
          const SizedBox(height: 28),
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(22), border: Border.all(color: const Color(0xFFE3DCCD))),
            child: const Text('1. On your PC open PocketDesk Agent and click “Pair a new phone”.\n\n2. Tap the button below and scan the QR code.\n\n3. Your desktop appears. It stays connected until you sign out.', style: TextStyle(fontSize: 16, height: 1.45, color: Color(0xFF2B2F2A))),
          ),
          const SizedBox(height: 28),
          SizedBox(height: 64, child: FilledButton.icon(onPressed: () => _scan(context), icon: const Icon(Icons.qr_code_scanner, size: 28), label: const Text('Scan QR code', style: TextStyle(fontSize: 18)))),
          const SizedBox(height: 28),
          const Text('Or type the server address:', style: TextStyle(color: Color(0xFF6B7468))),
          const SizedBox(height: 8),
          TextField(controller: ctl, keyboardType: TextInputType.url, decoration: const InputDecoration(border: OutlineInputBorder(), hintText: 'https://your-server.example.com')),
          const SizedBox(height: 12),
          SizedBox(height: 52, child: OutlinedButton(onPressed: () async { final l = normalizeLink(ctl.text); if (l != null) await onLink(l); }, child: const Text('Open'))),
        ]),
      ),
    );
  }
}

class Scanner extends StatefulWidget {
  const Scanner({super.key});
  @override
  State<Scanner> createState() => _ScannerState();
}

class _ScannerState extends State<Scanner> {
  bool done = false;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Scan the QR on your PC')),
        body: MobileScanner(onDetect: (cap) {
          if (done) return;
          for (final b in cap.barcodes) {
            final v = b.rawValue;
            if (v != null && v.startsWith('http')) {
              done = true;
              Navigator.of(context).pop(v);
              return;
            }
          }
        }),
      );
}

class Viewer extends StatefulWidget {
  final String startLink;
  final VoidCallback onReset;
  final Future<void> Function(String) onNewLink;
  const Viewer({super.key, required this.startLink, required this.onReset, required this.onNewLink});
  @override
  State<Viewer> createState() => _ViewerState();
}

class _ViewerState extends State<Viewer> {
  late final WebViewController ctl;
  String? loadError;
  late String origin;
  List pcs = [];
  Timer? healTimer;
  bool checkingAddr = false, updateChecked = false;
  late SharedPreferences prefs;

  @override
  void initState() {
    super.initState();
    origin = Uri.parse(widget.startLink).origin;
    WakelockPlus.enable();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(statusBarIconBrightness: Brightness.dark, systemNavigationBarIconBrightness: Brightness.dark));
    ctl = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFFF5F1EA))
      ..addJavaScriptChannel('PD', onMessageReceived: (m) async {
        // the web client reports its paired PCs (token + key + announcement topic): keep them natively
        try {
          jsonDecode(m.message);
          await prefs.setString('pcs', m.message);
          pcs = jsonDecode(m.message);
        } catch (_) {}
      })
      ..addJavaScriptChannel('PDS', onMessageReceived: (m) {
        if (m.message.startsWith('retry:') && (int.tryParse(m.message.substring(6)) ?? 0) >= 2) _checkAddress();
      })
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (r) => Uri.parse(r.url).origin == origin ? NavigationDecision.navigate : NavigationDecision.prevent,
        onPageStarted: (_) => setState(() => loadError = null),
        onPageFinished: (_) {
          _inject();
          _checkUpdate();
        },
        onWebResourceError: (e) {
          if (e.isForMainFrame != false) _fail(e.description);
        },
        onHttpError: (e) {
          if ((e.response?.statusCode ?? 0) >= 500) _fail('Server returned ${e.response?.statusCode}');
        },
      ));
    _start();
  }

  Future<void> _start() async {
    prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('pcs');
    pcs = raw == null ? [] : jsonDecode(raw);
    final pending = prefs.getString('pending_link'); // fresh QR with one-time code
    if (pending != null) {
      await prefs.remove('pending_link');
      origin = Uri.parse(pending).origin;
      ctl.loadRequest(Uri.parse(pending));
      return;
    }
    // Pick a working address BEFORE loading anything: the announced address (if the PC's address changed) or the saved one.
    final d = pcs.isEmpty ? null : await discoverAddress(pcs);
    for (final c in [if (d != null) Uri.parse(d).origin, origin]) {
      if (await _healthy(c)) {
        origin = c;
        await prefs.setString('origin', origin);
        _checkUpdate();
        ctl.loadRequest(Uri.parse(origin));
        _watch();
        return;
      }
    }
    _fail('Waiting for your PC…'); // keeps searching by itself and loads the page as soon as the PC answers
  }

  Future<bool> _healthy(String o) async {
    try {
      final r = await http.get(Uri.parse('$o/healthz')).timeout(const Duration(seconds: 8));
      return r.statusCode == 200 && r.body.contains('ok');
    } catch (_) {
      return false;
    }
  }

  int _badChecks = 0;
  Timer? watchTimer;

  /// While connected: if the address stops answering (tunnel restarted), go back to searching for the PC.
  void _watch() {
    watchTimer?.cancel();
    watchTimer = Timer.periodic(const Duration(seconds: 20), (_) async {
      if (loadError != null) return;
      if (await _healthy(origin)) {
        _badChecks = 0;
      } else if (++_badChecks >= 2) {
        _badChecks = 0;
        _fail('PC address changed or unreachable');
      }
    });
  }

  /// Restores the saved pairing into the page (needed whenever the address — and so the page origin — has changed).
  Future<void> _inject() async {
    if (pcs.isEmpty) return;
    final list = [for (final p in pcs) {...(p as Map), 'server': ''}]; // '' = use the page's own server
    final json = jsonEncode(jsonEncode(list));
    final auto = jsonEncode(list.first['deviceId']);
    await ctl.runJavaScript('''
      (function(){ try {
        var NEW = $json, cur = localStorage.getItem('pd_pcs');
        if (!cur || cur === '[]') {
          localStorage.setItem('pd_pcs', NEW); localStorage.setItem('pd_auto', $auto);
          if (!sessionStorage.getItem('pd_inj')) { sessionStorage.setItem('pd_inj', '1'); location.reload(); }
        }
      } catch (e) {} })();''');
  }

  void _fail(String why) {
    if (!mounted) return;
    setState(() => loadError = why);
    healTimer ??= Timer.periodic(const Duration(seconds: 8), (_) => _checkAddress());
  }

  Future<void> _checkAddress() async {
    if (checkingAddr) return;
    checkingAddr = true;
    try {
      final d = pcs.isEmpty ? null : await discoverAddress(pcs);
      for (final c in [if (d != null) Uri.parse(d).origin, origin]) {
        if (await _healthy(c)) {
          final changed = c != origin;
          origin = c;
          await prefs.setString('origin', origin);
          if (mounted) setState(() => loadError = null);
          healTimer?.cancel();
          healTimer = null;
          ctl.loadRequest(Uri.parse(origin)); // page reloads, pairing is re-injected, the session resumes
          _watch();
          if (changed) _checkUpdate();
          return;
        }
      }
    } finally {
      checkingAddr = false;
    }
  }

  Future<void> _checkUpdate() async {
    if (updateChecked) return;
    updateChecked = true;
    try {
      final r = await http.get(Uri.parse('$origin/app/version.json')).timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) return;
      final j = jsonDecode(r.body);
      final remote = (j['versionCode'] as num).toInt();
      final local = int.tryParse((await PackageInfo.fromPlatform()).buildNumber) ?? 0;
      if (remote <= local || !mounted) return;
      final yes = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Update available'),
          content: Text('A new version of PocketDesk is ready${j['notes'] != null ? ':\n${j['notes']}' : '.'}\n\nAndroid will ask you to confirm the install.'),
          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Later')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Update'))],
        ),
      );
      if (yes != true) return;
      final bytes = (await http.get(Uri.parse('$origin${j['url'] ?? '/app/PocketDesk.apk'}')).timeout(const Duration(minutes: 3))).bodyBytes;
      final f = File('${(await getTemporaryDirectory()).path}/PocketDesk-update.apk');
      await f.writeAsBytes(bytes);
      await OpenFilex.open(f.path, type: 'application/vnd.android.package-archive');
    } catch (_) {}
  }

  @override
  void dispose() {
    healTimer?.cancel();
    watchTimer?.cancel();
    WakelockPlus.disable();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    super.dispose();
  }

  Future<void> _menu() async {
    final a = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.refresh), title: const Text('Reload'), onTap: () => Navigator.pop(c, 'reload')),
          ListTile(leading: const Icon(Icons.system_update), title: const Text('Check for app update'), onTap: () => Navigator.pop(c, 'update')),
          ListTile(leading: const Icon(Icons.qr_code_scanner), title: const Text('Forget this PC / scan a new QR'), onTap: () => Navigator.pop(c, 'reset')),
          ListTile(leading: const Icon(Icons.close), title: const Text('Close app'), onTap: () => Navigator.pop(c, 'exit')),
        ]),
      ),
    );
    if (a == 'reload') {
      ctl.loadRequest(Uri.parse(origin));
    } else if (a == 'update') {
      updateChecked = false;
      _checkUpdate();
    } else if (a == 'reset') {
      widget.onReset();
    } else if (a == 'exit') {
      SystemNavigator.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _menu();
      },
      child: Scaffold(
        backgroundColor: const Color(0xFFF5F1EA),
        body: loadError != null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const CircularProgressIndicator(),
                    const SizedBox(height: 20),
                    const Text('Looking for your PC…\nThe app is checking whether its address changed and will reconnect by itself.', textAlign: TextAlign.center, style: TextStyle(fontSize: 16)),
                    const SizedBox(height: 8),
                    Text(loadError!, textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFF6B7468), fontSize: 12)),
                    const SizedBox(height: 20),
                    FilledButton(onPressed: _checkAddress, child: const Text('Try now')),
                    const SizedBox(height: 10),
                    OutlinedButton(onPressed: widget.onReset, child: const Text('Scan a new QR')),
                  ]),
                ),
              )
            : SafeArea(top: false, bottom: false, child: WebViewWidget(controller: ctl)),
      ),
    );
  }
}
