import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

typedef Json = Map<String, dynamic>;

class Api {
  String baseUrl;
  String token;
  Api(this.baseUrl, this.token);

  static Future<Api> load() async {
    final p = await SharedPreferences.getInstance();
    return Api(p.getString('baseUrl') ?? '', p.getString('token') ?? '');
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('baseUrl', baseUrl.trim());
    await p.setString('token', token.trim());
  }

  bool get configured => baseUrl.trim().isNotEmpty && token.trim().isNotEmpty;

  Uri _uri(String path, [Map<String, String>? query]) {
    var b = baseUrl.trim();
    while (b.endsWith('/')) {
      b = b.substring(0, b.length - 1);
    }
    return Uri.parse('$b$path').replace(queryParameters: query);
  }

  Future<dynamic> _send(String method, String path,
      {Json? body, Map<String, String>? query}) async {
    final req = http.Request(method, _uri(path, query));
    req.headers['Authorization'] = 'Bearer ${token.trim()}';
    req.headers['Content-Type'] = 'application/json';
    if (body != null) req.body = jsonEncode(body);
    try {
      final streamed = await req.send().timeout(const Duration(seconds: 30));
      final res = await http.Response.fromStream(streamed);
      final text = utf8.decode(res.bodyBytes);
      if (res.statusCode >= 400) {
        throw ApiException('HTTP ${res.statusCode}: $text');
      }
      return text.isEmpty ? null : jsonDecode(text);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('Network error: $e');
    }
  }

  List<Json> _list(dynamic v) => (v as List).cast<Json>();

  Future<List<Json>> listTasks() async => _list(await _send('GET', '/tasks'));
  Future<Json> createTask(String message) async =>
      (await _send('POST', '/tasks', body: {'message': message})) as Json;
  Future<Json> getTask(String id) async =>
      (await _send('GET', '/tasks/$id')) as Json;
  Future<List<Json>> events(String id, int after) async => _list(
      await _send('GET', '/tasks/$id/events', query: {'after': '$after'}));
  Future<void> sendMessage(String id, String message) =>
      _send('POST', '/tasks/$id/messages', body: {'message': message});
  Future<void> stopTask(String id) => _send('POST', '/tasks/$id/stop');
  Future<void> setAutoApprove(String id, bool value) =>
      _send('POST', '/tasks/$id/auto_approve', body: {'value': value});
  Future<void> resolveApproval(int id, bool approve) =>
      _send('POST', '/approvals/$id', body: {'approve': approve});

  Future<List<Json>> memory({String? kind}) async => _list(await _send(
      'GET', '/memory', query: kind == null ? null : {'kind': kind}));
  Future<void> setMemoryStatus(int id, String status) =>
      _send('PATCH', '/memory/$id', body: {'status': status});
  Future<void> deleteMemory(int id) => _send('DELETE', '/memory/$id');

  Future<Json> control() async => (await _send('GET', '/control')) as Json;
  Future<void> pauseAll() => _send('POST', '/control/pause');
  Future<void> resumeAll() => _send('POST', '/control/resume');
  Future<void> killAll() => _send('POST', '/control/kill');
}

String statusLabel(String s) {
  switch (s) {
    case 'queued':
      return 'লাইনে আছে';
    case 'running':
      return 'কাজ চলছে';
    case 'sleeping':
      return 'Kaggle/HF-এর জন্য অপেক্ষা';
    case 'waiting_approval':
      return 'আপনার অনুমতি দরকার';
    case 'waiting_user':
      return 'আপনার উত্তর দরকার';
    case 'done':
      return 'শেষ';
    case 'failed':
      return 'ব্যর্থ';
    case 'stopped':
      return 'থামানো';
    default:
      return s;
  }
}
