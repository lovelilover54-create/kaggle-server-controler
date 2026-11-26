import 'package:flutter/material.dart';

import '../api.dart';

class MemoryScreen extends StatefulWidget {
  final Api api;
  const MemoryScreen({super.key, required this.api});

  @override
  State<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<MemoryScreen> {
  String? _kind; // null = all
  List<Json> _items = [];
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await widget.api.memory(kind: _kind);
      if (mounted) {
        setState(() {
          _items = r;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _act(Future<void> Function() a) async {
    try {
      await a();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    const kinds = <String?, String>{
      null: 'সব',
      'skill': 'Skill',
      'lesson': 'Lesson',
      'fact': 'Fact'
    };
    return Scaffold(
      appBar: AppBar(title: const Text('Memory ও skill')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(8),
            child: Wrap(
              spacing: 8,
              children: [
                for (final k in kinds.entries)
                  ChoiceChip(
                    label: Text(k.value),
                    selected: _kind == k.key,
                    onSelected: (_) {
                      _kind = k.key;
                      _load();
                    },
                  ),
              ],
            ),
          ),
          if (_error != null)
            Padding(padding: const EdgeInsets.all(8), child: Text(_error!)),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    children: [
                      if (_items.isEmpty)
                        const Padding(
                            padding: EdgeInsets.all(24),
                            child: Center(child: Text('কিছু নেই।'))),
                      for (final m in _items)
                        Card(
                          margin: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 6),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                    '${m['kind']}${m['status'] == 'draft' ? ' · DRAFT (অনুমোদন দরকার)' : ''} · ${m['source']}',
                                    style:
                                        Theme.of(context).textTheme.labelSmall),
                                const SizedBox(height: 4),
                                Text('${m['title']}',
                                    style: const TextStyle(
                                        fontWeight: FontWeight.bold)),
                                const SizedBox(height: 4),
                                Text('${m['body']}',
                                    maxLines: 8,
                                    overflow: TextOverflow.ellipsis),
                                if ('${m['evidence']}'.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 4),
                                    child: Text('প্রমাণ: ${m['evidence']}',
                                        maxLines: 3,
                                        overflow: TextOverflow.ellipsis,
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodySmall),
                                  ),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.end,
                                  children: [
                                    if (m['status'] == 'draft')
                                      FilledButton(
                                          onPressed: () => _act(() => widget
                                              .api
                                              .setMemoryStatus(
                                                  m['id'] as int, 'active')),
                                          child: const Text('Approve')),
                                    TextButton(
                                        onPressed: () => _act(() => widget.api
                                            .setMemoryStatus(
                                                m['id'] as int, 'archived')),
                                        child: const Text('Archive')),
                                    TextButton(
                                        onPressed: () => _act(() => widget.api
                                            .deleteMemory(m['id'] as int)),
                                        child: const Text('Delete')),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}
