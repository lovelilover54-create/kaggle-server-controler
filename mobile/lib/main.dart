import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/settings_screen.dart';
import 'screens/tasks_screen.dart';

void main() => runApp(const AgentApp());

class AgentApp extends StatelessWidget {
  const AgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Agent',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      darkTheme: ThemeData(
          colorSchemeSeed: Colors.indigo,
          brightness: Brightness.dark,
          useMaterial3: true),
      home: const Boot(),
    );
  }
}

class Boot extends StatefulWidget {
  const Boot({super.key});

  @override
  State<Boot> createState() => _BootState();
}

class _BootState extends State<Boot> {
  Api? _api;

  @override
  void initState() {
    super.initState();
    Api.load().then((a) {
      if (mounted) setState(() => _api = a);
    });
  }

  @override
  Widget build(BuildContext context) {
    final api = _api;
    if (api == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!api.configured) {
      return SettingsScreen(api: api, firstRun: true);
    }
    return TasksScreen(api: api);
  }
}
