import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/backend/api_client.dart';
import '../../widgets/score_view.dart';

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});

  @override
  ConsumerState<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends ConsumerState<UploadScreen> {
  bool _removeVocals = true;
  String _model = 'basic_pitch';
  bool _busy = false;
  String _statusText = '';
  double _progress = 0;
  String? _musicXml;
  String? _error;

  static const int _maxBytes = ApiClient.maxUploadBytes;

  Future<void> _pickAndUpload() async {
    setState(() {
      _error = null;
      _musicXml = null;
    });

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const [
        'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', // audio
        'mp4', 'mov', 'mkv', 'webm', // video (audio extracted server-side)
      ],
      withData: true,
    );
    if (result == null || result.files.isEmpty) return;

    final file = result.files.first;
    final bytes = file.bytes;
    if (bytes == null) {
      setState(() => _error = '无法读取文件内容');
      return;
    }
    if (bytes.length > _maxBytes) {
      setState(() => _error =
          '文件 ${(bytes.length / (1024 * 1024)).toStringAsFixed(1)}MB 超过 100MB 上限，请先压缩或裁剪');
      return;
    }

    final api = ref.read(apiClientProvider);
    setState(() {
      _busy = true;
      _statusText = '上传中…';
      _progress = 0;
    });

    try {
      final jobId = await api.createJob(
        bytes: bytes,
        filename: file.name,
        removeVocals: _removeVocals,
        model: _model,
      );
      final status = await api.pollUntilDone(
        jobId,
        onUpdate: (s) {
          if (!mounted) return;
          setState(() {
            _statusText = '处理中: ${s.stage ?? s.state}';
            _progress = s.progress;
          });
        },
      );
      if (status.isError) {
        setState(() => _error = '处理失败: ${status.error}');
      } else {
        final xml = await api.getMusicXml(jobId);
        setState(() => _musicXml = xml);
      }
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('上传音频/视频转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
      ),
      body: Column(
        children: [
          SwitchListTile(
            title: const Text('先去除人声 (保留伴奏/乐器)'),
            subtitle: const Text('HT-Demucs 源分离'),
            value: _removeVocals,
            onChanged: _busy ? null : (v) => setState(() => _removeVocals = v),
          ),
          ListTile(
            title: const Text('转录模型'),
            trailing: DropdownButton<String>(
              value: _model,
              items: const [
                DropdownMenuItem(value: 'basic_pitch', child: Text('Basic Pitch (默认)')),
                DropdownMenuItem(value: 'mt3', child: Text('MT3 (高精度)')),
              ],
              onChanged: _busy ? null : (v) => setState(() => _model = v ?? 'basic_pitch'),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(
              onPressed: _busy ? null : _pickAndUpload,
              icon: const Icon(Icons.upload_file),
              label: const Text('选择文件并上传 (≤100MB)'),
            ),
          ),
          if (_busy) ...[
            LinearProgressIndicator(value: _progress == 0 ? null : _progress),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(_statusText),
            ),
          ],
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          Expanded(
            child: _musicXml == null
                ? const Center(child: Text('上传后在此显示五线谱结果'))
                : ScoreView(musicXml: _musicXml!),
          ),
        ],
      ),
    );
  }
}
