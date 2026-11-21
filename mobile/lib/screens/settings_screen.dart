import 'package:flutter/material.dart';
import '../core/store.dart';

class SettingsScreen extends StatefulWidget {
  final Settings settings;
  const SettingsScreen({super.key, required this.settings});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Settings get s => widget.settings;
  void _save() {
    Store.saveSettings(s);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(children: [
        const ListTile(title: Text('Video quality'), subtitle: Text('Lower quality uses less data and works better on slow networks.')),
        RadioGroup<String>(
          groupValue: s.quality,
          onChanged: (v) {
            s.quality = v!;
            _save();
          },
          child: Column(children: [
            for (final q in const {'low': 'Low (960px, 12 fps)', 'medium': 'Medium (1280px, 20 fps)', 'high': 'High (1920px, 30 fps)'}.entries)
              RadioListTile<String>(value: q.key, title: Text(q.value)),
          ]),
        ),
        const Divider(),
        SwitchListTile(title: const Text('Start in trackpad mode'), subtitle: const Text('Drag anywhere to move the cursor like a laptop trackpad.'), value: s.trackpad, onChanged: (v) { s.trackpad = v; _save(); }),
        SwitchListTile(title: const Text('Natural scrolling'), value: s.naturalScroll, onChanged: (v) { s.naturalScroll = v; _save(); }),
        ListTile(title: const Text('Trackpad sensitivity'), subtitle: Slider(min: 0.5, max: 3, divisions: 10, value: s.sensitivity, label: s.sensitivity.toStringAsFixed(1), onChanged: (v) { s.sensitivity = v; _save(); })),
        const Divider(),
        const ListTile(
          title: Text('Gestures'),
          subtitle: Text('Touch mode: tap = click, long-press = right-click, drag = drag.\nTrackpad: drag = move, tap = click, hold then drag = drag.\nTwo fingers: drag = scroll, tap = right-click, pinch = zoom.\nUse the hand icon to pan a zoomed view.'),
        ),
      ]),
    );
  }
}
