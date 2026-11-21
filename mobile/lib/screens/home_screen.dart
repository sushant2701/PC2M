import 'dart:async';
import 'package:flutter/material.dart';
import '../core/api.dart';
import '../core/store.dart';
import 'pair_screen.dart';
import 'remote_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<PairedPc> pcs = [];
  Settings settings = Settings();
  final Map<String, bool?> online = {};
  final Set<String> revoked = {};
  bool loading = true;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _load();
    _t = Timer.periodic(const Duration(seconds: 6), (_) => _poll());
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    pcs = await Store.loadPcs();
    settings = await Store.loadSettings();
    setState(() => loading = false);
    _poll();
  }

  Future<void> _poll() async {
    for (final pc in pcs) {
      try {
        final o = await fetchOnline(pc);
        if (mounted) setState(() => online[pc.deviceId] = o);
      } on ApiException {
        if (mounted) setState(() => revoked.add(pc.deviceId));
      }
    }
  }

  Future<void> _add() async {
    final pc = await Navigator.of(context).push<PairedPc>(MaterialPageRoute(builder: (_) => PairScreen(settings: settings)));
    if (pc != null) {
      pcs = [...pcs.where((p) => p.deviceId != pc.deviceId), pc];
      await Store.savePcs(pcs);
      setState(() {});
      _poll();
    }
  }

  Future<void> _remove(PairedPc pc) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Remove ${pc.name}?'),
        content: const Text('This phone will be unpaired and can no longer control the PC.'),
        actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Remove'))],
      ),
    );
    if (ok == true) {
      await revokeSelf(pc);
      pcs = pcs.where((p) => p.deviceId != pc.deviceId).toList();
      await Store.savePcs(pcs);
      setState(() {});
    }
  }

  void _open(PairedPc pc) {
    if (revoked.contains(pc.deviceId)) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Access was revoked. Remove this PC and pair again.')));
      return;
    }
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => RemoteScreen(pc: pc, settings: settings)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('PocketDesk'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () async {
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => SettingsScreen(settings: settings)));
              setState(() {});
            },
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(onPressed: _add, icon: const Icon(Icons.add), label: const Text('Pair PC')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : pcs.isEmpty
              ? const Center(
                  child: Padding(
                    padding: EdgeInsets.all(32),
                    child: Text('No PCs yet.\nInstall PocketDesk Agent on your Windows PC, then tap “Pair PC”.', textAlign: TextAlign.center),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _poll,
                  child: ListView(children: [
                    for (final pc in pcs)
                      ListTile(
                        leading: Icon(Icons.desktop_windows, color: revoked.contains(pc.deviceId) ? Colors.red : (online[pc.deviceId] == true ? Colors.green : Colors.grey)),
                        title: Text(pc.name),
                        subtitle: Text(revoked.contains(pc.deviceId)
                            ? 'Access revoked'
                            : online[pc.deviceId] == true ? 'Online' : online[pc.deviceId] == false ? 'Offline — PC or agent not running' : 'Checking…'),
                        trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _remove(pc)),
                        onTap: () => _open(pc),
                      ),
                  ]),
                ),
    );
  }
}
