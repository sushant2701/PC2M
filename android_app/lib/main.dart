import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';

// PocketDesk app: a full-screen shell around the PocketDesk web client (which holds the pairing and does the
// encrypted connection). Adds: QR scanning, keeps the screen awake, remembers your server, full-screen immersive mode.
void main() => runApp(const App());

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'PocketDesk',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: const Color(0xFF4F7CFF), brightness: Brightness.dark, useMaterial3: true),
        home: const Boot(),
      );
}

class Boot extends StatefulWidget {
  const Boot({super.key});
  @override
  State<Boot> createState() => _BootState();
}

class _BootState extends State<Boot> {
  String? link; // page to load (saved server address)
  bool ready = false;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) => setState(() {
          link = p.getString('link');
          ready = true;
        }));
  }

  Future<void> _save(String? l) async {
    final p = await SharedPreferences.getInstance();
    if (l == null) {
      await p.remove('link');
    } else {
      await p.setString('link', l);
    }
    setState(() => link = l);
  }

  @override
  Widget build(BuildContext context) {
    if (!ready) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (link == null) return Welcome(onLink: _save);
    return Viewer(link: link!, onReset: () => _save(null), onNewLink: _save);
  }
}

/// Accepts a pairing link like https://host/#c=CODE or a plain server address.
String? normalizeLink(String raw) {
  final t = raw.trim();
  final u = Uri.tryParse(t.contains('://') ? t : 'https://$t');
  if (u == null || u.host.isEmpty || u.scheme != 'https') return null;
  return u.toString();
}

class Welcome extends StatelessWidget {
  final Future<void> Function(String) onLink;
  const Welcome({super.key, required this.onLink});

  Future<void> _scan(BuildContext c) async {
    final r = await Navigator.of(c).push<String>(MaterialPageRoute(builder: (_) => const Scanner()));
    if (r == null) return;
    final l = normalizeLink(r);
    if (l == null && c.mounted) {
      ScaffoldMessenger.of(c).showSnackBar(const SnackBar(content: Text('That QR is not a PocketDesk link (it must start with https://).')));
      return;
    }
    await onLink(l!);
  }

  @override
  Widget build(BuildContext context) {
    final ctl = TextEditingController();
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 24),
          const Row(children: [
            Text('🖥', style: TextStyle(fontSize: 40)),
            SizedBox(width: 12),
            Text('PocketDesk', style: TextStyle(fontSize: 30, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 28),
          const Text('1. On your PC open PocketDesk Agent and click “Pair a new phone”.\n2. Tap the button below and scan the QR code.\n3. Your PC desktop appears. It stays connected until you sign out.',
              style: TextStyle(fontSize: 16, height: 1.5)),
          const SizedBox(height: 28),
          SizedBox(
            height: 64,
            child: FilledButton.icon(
              onPressed: () => _scan(context),
              icon: const Icon(Icons.qr_code_scanner, size: 28),
              label: const Text('Scan QR code', style: TextStyle(fontSize: 18)),
            ),
          ),
          const SizedBox(height: 28),
          const Text('Or type the server address / pairing link:', style: TextStyle(color: Colors.white70)),
          const SizedBox(height: 8),
          TextField(
            controller: ctl,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(border: OutlineInputBorder(), hintText: 'https://your-server.example.com'),
            onSubmitted: (v) async {
              final l = normalizeLink(v);
              if (l != null) await onLink(l);
            },
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 52,
            child: OutlinedButton(
              onPressed: () async {
                final l = normalizeLink(ctl.text);
                if (l != null) await onLink(l);
              },
              child: const Text('Open'),
            ),
          ),
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
        body: MobileScanner(
          onDetect: (cap) {
            if (done) return;
            for (final b in cap.barcodes) {
              final v = b.rawValue;
              if (v != null && v.startsWith('http')) {
                done = true;
                Navigator.of(context).pop(v);
                return;
              }
            }
          },
        ),
      );
}

class Viewer extends StatefulWidget {
  final String link;
  final VoidCallback onReset;
  final Future<void> Function(String) onNewLink;
  const Viewer({super.key, required this.link, required this.onReset, required this.onNewLink});
  @override
  State<Viewer> createState() => _ViewerState();
}

class _ViewerState extends State<Viewer> {
  late final WebViewController ctl;
  String? loadError;
  late final String origin;

  @override
  void initState() {
    super.initState();
    final u = Uri.parse(widget.link);
    origin = '${u.scheme}://${u.authority}';
    WakelockPlus.enable(); // keep the phone screen on while connected
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    ctl = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF0F172A))
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (r) => Uri.parse(r.url).authority == u.authority ? NavigationDecision.navigate : NavigationDecision.prevent,
        onPageStarted: (_) => setState(() => loadError = null),
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? false) setState(() => loadError = e.description);
        },
      ))
      ..loadRequest(Uri.parse(widget.link));
    // After the first load keep only the clean origin saved (the pairing code in a link is single-use).
    widget.onNewLink(origin);
  }

  @override
  void dispose() {
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
          ListTile(leading: const Icon(Icons.qr_code_scanner), title: const Text('Scan a new QR / change server'), onTap: () => Navigator.pop(c, 'reset')),
          ListTile(leading: const Icon(Icons.close), title: const Text('Close app'), onTap: () => Navigator.pop(c, 'exit')),
        ]),
      ),
    );
    if (a == 'reload') {
      ctl.loadRequest(Uri.parse(origin));
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
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        _menu(); // Back button opens the menu instead of leaving the session
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF0F172A),
        body: loadError != null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.cloud_off, size: 56),
                    const SizedBox(height: 16),
                    const Text('Cannot reach your PocketDesk server.\nThe address may have changed (free tunnels change when they restart).', textAlign: TextAlign.center, style: TextStyle(fontSize: 16)),
                    const SizedBox(height: 8),
                    Text(loadError!, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white54, fontSize: 12)),
                    const SizedBox(height: 20),
                    FilledButton(onPressed: () => ctl.loadRequest(Uri.parse(origin)), child: const Text('Try again')),
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
