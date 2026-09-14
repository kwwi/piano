import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

/// Status of a backend transcription job.
class JobStatus {
  final String id;
  final String state; // queued | processing | done | error
  final double progress; // 0..1
  final String? stage;
  final String? error;

  const JobStatus({
    required this.id,
    required this.state,
    this.progress = 0,
    this.stage,
    this.error,
  });

  bool get isDone => state == 'done';
  bool get isError => state == 'error';

  factory JobStatus.fromJson(Map<String, dynamic> json) => JobStatus(
        id: json['job_id'] as String,
        state: json['status'] as String,
        progress: (json['progress'] as num?)?.toDouble() ?? 0,
        stage: json['stage'] as String?,
        error: json['error'] as String?,
      );
}

/// Client for the FastAPI backend that powers the "upload audio/video" feature.
class ApiClient {
  final String baseUrl;
  final http.Client _http;

  ApiClient({required this.baseUrl, http.Client? client})
      : _http = client ?? http.Client();

  /// Enforced client-side upload ceiling (bytes). Mirrors the backend limit.
  static const int maxUploadBytes = 100 * 1024 * 1024;

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  /// Submit an audio file for transcription. Returns the created job id.
  Future<String> createJob({
    required List<int> bytes,
    required String filename,
    bool removeVocals = true,
    String model = 'basic_pitch',
  }) async {
    if (bytes.length > maxUploadBytes) {
      throw ApiException('文件超过 100MB 上限 (${bytes.length ~/ (1024 * 1024)}MB)');
    }
    final req = http.MultipartRequest('POST', _u('/jobs'))
      ..fields['remove_vocals'] = removeVocals.toString()
      ..fields['model'] = model
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final streamed = await _http.send(req);
    final resp = await http.Response.fromStream(streamed);
    if (resp.statusCode != 200 && resp.statusCode != 201) {
      throw ApiException('创建任务失败 (${resp.statusCode}): ${resp.body}');
    }
    return (jsonDecode(resp.body) as Map<String, dynamic>)['job_id'] as String;
  }

  Future<JobStatus> getStatus(String id) async {
    final resp = await _http.get(_u('/jobs/$id'));
    if (resp.statusCode != 200) {
      throw ApiException('查询任务失败 (${resp.statusCode})');
    }
    return JobStatus.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<String> getMusicXml(String id) async {
    final resp = await _http.get(_u('/jobs/$id/musicxml'));
    if (resp.statusCode != 200) {
      throw ApiException('获取结果失败 (${resp.statusCode})');
    }
    return utf8.decode(resp.bodyBytes);
  }

  /// Poll [getStatus] until the job finishes, forwarding progress to [onUpdate].
  Future<JobStatus> pollUntilDone(
    String id, {
    Duration interval = const Duration(seconds: 2),
    void Function(JobStatus)? onUpdate,
  }) async {
    while (true) {
      final status = await getStatus(id);
      onUpdate?.call(status);
      if (status.isDone || status.isError) return status;
      await Future<void>.delayed(interval);
    }
  }
}

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

/// Default backend endpoint. Override via [ProviderScope] overrides in tests or
/// to point at a deployed server.
final backendBaseUrlProvider = Provider<String>((ref) => 'http://10.0.2.2:8000');

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(baseUrl: ref.watch(backendBaseUrlProvider));
});
