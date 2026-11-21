import 'package:flutter/material.dart';
import 'screens/home_screen.dart';

void main() => runApp(const PocketDeskApp());

class PocketDeskApp extends StatelessWidget {
  const PocketDeskApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PocketDesk',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: Colors.indigo, brightness: Brightness.dark, useMaterial3: true),
      home: const SplashGate(),
    );
  }
}

class SplashGate extends StatefulWidget {
  const SplashGate({super.key});
  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate> {
  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 900), () {
      if (mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
    });
  }

  @override
  Widget build(BuildContext context) => const Scaffold(
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.desktop_windows, size: 72),
            SizedBox(height: 12),
            Text('PocketDesk', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
          ]),
        ),
      );
}
