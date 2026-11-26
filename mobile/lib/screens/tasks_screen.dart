import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import 'chat_screen.dart';
import 'memory_screen.dart';
import 'settings_screen.dart';

class TasksScreen extends StatefulWidget {
  final Api api;
  const TasksScreen({super.key, required this.api});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  List<Json> _tasks = [];
  Json? _control;
  String? _error;
  bool _loading = true;
  bool _busy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 6), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    try {
      final t = await widget.api.listTasks();
      final c = await widget.api.control();
      if (!mounted) return;
      setState(() {
        _tasks = t;
        _control = c;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    } finally {
      _busy = false;
    }
  }

  Future<void> _open(String? id) async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ChatScreen(api: widget.api, taskId: id)));
    _load();
  }

  Future<void> _kill() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('সব কাজ থামাবেন?'),
        content: const Text(
            'Kill switch: সব অসম্পূর্ণ task থেমে যাবে এবং agent pause হবে।'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('না')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('হ্যাঁ, থামাও')),
        ],
      ),
    );
    if (ok == true) {
      await widget.api.killAll();
      _load();
    }
  }

  IconData _icon(String s) {
    switch (s) {
      case 'running':
        return Icons.autorenew;
      case 'sleeping':
        return Icons.hourglass_bottom;
      case 'waiting_approval':
        return Icons.gpp_maybe;
      case 'waiting_user':
        return Icons.help_outline;
      case 'done':
        return Icons.check_circle_outline;
      case 'failed':
        return Icons.error_outline;
      case 'stopped':
        return Icons.stop_circle_outlined;
      default:
        return Icons.schedule;
    }
  }

  @override
  Widget build(BuildContext context) {
    final paused = _control?['paused'] == true;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Agent'),
        actions: [
          IconButton(
            tooltip: 'Memory ও skill',
            icon: const Icon(Icons.psychology_alt_outlined),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => MemoryScreen(api: widget.api))),
          ),
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v == 'pause') {
                await (paused
                    ? widget.api.resumeAll()
                    : widget.api.pauseAll());
                _load();
              } else if (v == 'kill') {
                _kill();
              } else if (v == 'settings') {
                if (!mounted) return;
                Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => SettingsScreen(api: widget.api)));
              }
            },
            itemBuilder: (_) => [
              PopupMenuItem(
                  value: 'pause',
                  child: Text(paused ? 'Agent চালু করুন' : 'Agent pause করুন')),
              const PopupMenuItem(
                  value: 'kill', child: Text('Kill switch (সব থামাও)')),
              const PopupMenuItem(value: 'settings', child: Text('Server সেটিংস')),
            ],
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _open(null),
        icon: const Icon(Icons.add),
        label: const Text('নতুন চ্যাট'),
      ),
      body: Column(
        children: [
          if (paused)
            Container(
              width: double.infinity,
              color: Theme.of(context).colorScheme.errorContainer,
              padding: const EdgeInsets.all(8),
              child: const Text('Agent pause করা আছে, নতুন কাজ শুরু হবে না।',
                  textAlign: TextAlign.center),
            ),
          if (_control != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                    'GPU (agent-এর হিসাব): ${_control!['gpu_hours_7d']}h / ${_control!['gpu_budget_hours']}h, শেষ ৭ দিনে',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      children: [
                        if (_error != null)
                          Padding(
                              padding: const EdgeInsets.all(16),
                              child: Text('সংযোগ সমস্যা: $_error')),
                        if (_tasks.isEmpty && _error == null)
                          const Padding(
                              padding: EdgeInsets.all(32),
                              child: Center(
                                  child: Text(
                                      'এখনো কোনো চ্যাট নেই। "নতুন চ্যাট" চাপুন।'))),
                        for (final t in _tasks)
                          ListTile(
                            leading: Icon(_icon(t['status'] as String)),
                            title: Text(t['title'] as String,
                                maxLines: 1, overflow: TextOverflow.ellipsis),
                            subtitle: Text(
                                '${statusLabel(t['status'] as String)}'
                                '${(t['preview'] ?? '') == '' ? '' : ' · ${t['preview']}'}',
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis),
                            trailing: (t['pending_approvals'] as List).isEmpty
                                ? null
                                : const Badge(label: Text('!')),
                            onTap: () => _open(t['id'] as String),
                          ),
                        const SizedBox(height: 80),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}
