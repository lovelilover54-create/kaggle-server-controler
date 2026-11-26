import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';

class ChatScreen extends StatefulWidget {
  final Api api;
  final String? taskId; // null = new chat, created on first message
  const ChatScreen({super.key, required this.api, this.taskId});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  String? _taskId;
  Json? _task;
  final List<Json> _events = [];
  int _lastId = 0;
  final _input = TextEditingController();
  final _scroll = ScrollController();
  Timer? _timer;
  bool _sending = false;
  bool _polling = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _taskId = widget.taskId;
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _poll() async {
    final id = _taskId;
    if (id == null || _polling) return;
    _polling = true;
    try {
      final t = await widget.api.getTask(id);
      final ev = await widget.api.events(id, _lastId);
      if (!mounted) return;
      setState(() {
        _task = t;
        _error = null;
        if (ev.isNotEmpty) {
          _events.addAll(ev);
          _lastId = ev.last['id'] as int;
        }
      });
      if (ev.isNotEmpty) _scrollToEnd();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      _polling = false;
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      if (_taskId == null) {
        final t = await widget.api.createTask(text);
        _taskId = t['id'] as String;
        _task = t;
      } else {
        await widget.api.sendMessage(_taskId!, text);
      }
      _input.clear();
      await _poll();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('পাঠানো যায়নি: $e')));
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _run(Future<void> Function() action) async {
    try {
      await action();
      await _poll();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  Widget _bubble(String text, Color bg, Color fg, {bool right = false}) {
    return Align(
      alignment: right ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        constraints:
            BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.85),
        decoration:
            BoxDecoration(color: bg, borderRadius: BorderRadius.circular(14)),
        child: SelectableText(text, style: TextStyle(color: fg)),
      ),
    );
  }

  Widget _small(IconData icon, String text, {Color? color}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 6),
          Expanded(
              child: Text(text,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: color))),
        ],
      ),
    );
  }

  Widget _approvalCard(Json e, bool pending) {
    final scheme = Theme.of(context).colorScheme;
    final id = e['approval_id'] as int;
    return Card(
      color: scheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('অনুমতি দরকার: ${e['tool']}',
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: scheme.onTertiaryContainer)),
            const SizedBox(height: 4),
            Text('${e['reason']}',
                style: TextStyle(color: scheme.onTertiaryContainer)),
            const SizedBox(height: 4),
            Text('${e['args']}',
                style: TextStyle(
                    fontSize: 12, color: scheme.onTertiaryContainer)),
            if (pending)
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                      onPressed: () =>
                          _run(() => widget.api.resolveApproval(id, false)),
                      child: const Text('বাতিল')),
                  FilledButton(
                      onPressed: () =>
                          _run(() => widget.api.resolveApproval(id, true)),
                      child: const Text('অনুমতি দিন')),
                ],
              )
            else
              Text('(সিদ্ধান্ত হয়ে গেছে)',
                  style: TextStyle(color: scheme.onTertiaryContainer)),
          ],
        ),
      ),
    );
  }

  List<Widget> _items() {
    final scheme = Theme.of(context).colorScheme;
    final pendingIds =
        ((_task?['pending_approvals'] as List?) ?? const []).cast<int>();
    final out = <Widget>[];
    for (final e in _events) {
      switch (e['kind']) {
        case 'user':
          out.add(_bubble('${e['text']}', scheme.primaryContainer,
              scheme.onPrimaryContainer,
              right: true));
          break;
        case 'assistant':
          if ('${e['text']}'.isNotEmpty) {
            out.add(_bubble('${e['text']}', scheme.secondaryContainer,
                scheme.onSecondaryContainer));
          }
          for (final c in (e['calls'] as List)) {
            out.add(_small(Icons.build_outlined, '${(c as Json)['name']}...'));
          }
          break;
        case 'tool':
          for (final it in (e['items'] as List)) {
            final m = it as Json;
            final ok = m['ok'] == true;
            out.add(_small(ok ? Icons.check : Icons.close,
                '${m['name']}: ${m['summary']}',
                color: ok ? Colors.green : scheme.error));
          }
          break;
        case 'final':
          out.add(Card(
            color: e['success'] == true
                ? scheme.primaryContainer
                : scheme.errorContainer,
            child: Padding(
                padding: const EdgeInsets.all(12),
                child: SelectableText('${e['text']}')),
          ));
          break;
        case 'ask':
          out.add(_bubble('${e['text']}', scheme.tertiaryContainer,
              scheme.onTertiaryContainer));
          break;
        case 'approval':
          out.add(_approvalCard(e, pendingIds.contains(e['approval_id'])));
          break;
        case 'note':
          out.add(_small(Icons.info_outline, '${e['text']}'));
          break;
        default:
          break;
      }
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final status = (_task?['status'] as String?) ?? 'new';
    final active = status == 'running' ||
        status == 'sleeping' ||
        status == 'queued' ||
        status == 'waiting_approval';
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_task?['title'] as String? ?? 'নতুন চ্যাট',
                maxLines: 1, overflow: TextOverflow.ellipsis),
            if (_task != null)
              Text(statusLabel(status),
                  style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
        actions: [
          if (_task != null && active)
            IconButton(
              tooltip: 'থামান',
              icon: const Icon(Icons.stop_circle_outlined),
              onPressed: () => _run(() => widget.api.stopTask(_taskId!)),
            ),
          if (_task != null)
            PopupMenuButton<String>(
              onSelected: (v) {
                if (v == 'auto') {
                  _run(() => widget.api.setAutoApprove(
                      _taskId!, _task!['auto_approve'] != true));
                }
              },
              itemBuilder: (_) => [
                CheckedPopupMenuItem(
                    value: 'auto',
                    checked: _task!['auto_approve'] == true,
                    child: const Text('এই চ্যাটে auto-approve')),
              ],
            ),
        ],
      ),
      body: Column(
        children: [
          if (_error != null)
            Container(
                width: double.infinity,
                color: Theme.of(context).colorScheme.errorContainer,
                padding: const EdgeInsets.all(6),
                child: Text('সংযোগ সমস্যা: $_error',
                    style: const TextStyle(fontSize: 12))),
          Expanded(
            child: _events.isEmpty
                ? const Center(
                    child: Padding(
                        padding: EdgeInsets.all(24),
                        child: Text(
                            'কী করাতে চান লিখুন। যেমন: "Qwen2.5-0.5B মডেলটা Hugging Face Space-এ host করে API দাও"',
                            textAlign: TextAlign.center)))
                : ListView(
                    controller: _scroll,
                    padding: const EdgeInsets.all(12),
                    children: _items()),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 5,
                      textInputAction: TextInputAction.newline,
                      decoration: const InputDecoration(
                          hintText: 'মেসেজ লিখুন...',
                          border: OutlineInputBorder()),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    onPressed: _sending ? null : _send,
                    icon: _sending
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
