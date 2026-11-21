import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../core/api.dart';
import '../core/store.dart';

class PairScreen extends StatefulWidget {
  final Settings settings;
  const PairScreen({super.key, required this.settings});
  @override
  State<PairScreen> createState() => _PairScreenState();
}

class _PairScreenState extends State<PairScreen> {
  late final _server = TextEditingController(text: widget.settings.lastServer);
  final _code = TextEditingController();
  final _name = TextEditingController(text: 'My Phone');
  bool busy = false;
  String? error;

  Future<void> _pair() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final pc = await pairWithCode(_server.text, _code.text, _name.text.trim().isEmpty ? 'My Phone' : _name.text.trim());
      widget.settings.lastServer = pc.serverUrl;
      await Store.saveSettings(widget.settings);
      if (mounted) Navigator.of(context).pop(pc);
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Pair a PC')),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        const Text('1. Open PocketDesk Agent on your PC and click “Pair a new phone”.\n2. Enter the server address and the code shown.'),
        const SizedBox(height: 20),
        TextField(controller: _server, keyboardType: TextInputType.url, autocorrect: false,
            decoration: const InputDecoration(labelText: 'Server address', hintText: 'https://pocketdesk.example.com', border: OutlineInputBorder())),
        const SizedBox(height: 14),
        TextField(
          controller: _code,
          autocorrect: false,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(
            labelText: 'Pairing code', hintText: 'ABCDEF-GHIJ-KLMN-OPQR-STUV', border: const OutlineInputBorder(),
            suffixIcon: IconButton(
              icon: const Icon(Icons.paste),
              tooltip: 'Paste',
              onPressed: () async {
                final d = await Clipboard.getData('text/plain');
                if (d?.text != null) _code.text = d!.text!.trim();
              },
            ),
          ),
        ),
        const SizedBox(height: 14),
        TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name of this phone', border: OutlineInputBorder())),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        const SizedBox(height: 20),
        FilledButton(onPressed: busy ? null : _pair, child: busy ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Pair')),
      ]),
    );
  }
}
