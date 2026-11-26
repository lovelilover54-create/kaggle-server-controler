import 'package:flutter/material.dart';

import '../api.dart';
import 'tasks_screen.dart';

class SettingsScreen extends StatefulWidget {
  final Api api;
  final bool firstRun;
  const SettingsScreen({super.key, required this.api, this.firstRun = false});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _url =
      TextEditingController(text: widget.api.baseUrl);
  late final TextEditingController _token =
      TextEditingController(text: widget.api.token);
  String? _result;
  bool _busy = false;

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _result = null;
    });
    widget.api.baseUrl = _url.text;
    widget.api.token = _token.text;
    try {
      await widget.api.listTasks(); // tests URL + token
      await widget.api.save();
      if (!mounted) return;
      if (widget.firstRun) {
        Navigator.of(context).pushReplacement(
            MaterialPageRoute(builder: (_) => TasksScreen(api: widget.api)));
      } else {
        setState(() => _result = 'সংযোগ ঠিক আছে, সেভ হয়েছে।');
      }
    } catch (e) {
      if (mounted) setState(() => _result = 'সংযোগ হয়নি: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Server সেটিংস')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
              'Render-এ deploy করা backend-এর URL আর APP_TOKEN দিন। '
              'Kaggle, Hugging Face বা Gemini key এই app-এ কখনো দেবেন না, ওগুলো শুধু server-এ থাকে।'),
          const SizedBox(height: 16),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
                labelText: 'Backend URL',
                hintText: 'https://agent-backend.onrender.com',
                border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _token,
            obscureText: true,
            decoration: const InputDecoration(
                labelText: 'APP_TOKEN', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_busy ? 'যাচাই হচ্ছে...' : 'যাচাই করে সেভ করুন')),
          if (_result != null)
            Padding(
                padding: const EdgeInsets.only(top: 12), child: Text(_result!)),
        ],
      ),
    );
  }
}
