import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/backend/api_client.dart';
import '../../core/notation/score_export.dart';
import '../../core/notation/score_result_controller.dart';
import '../../core/notation/verovio_renderer.dart';
import '../../widgets/midi_track_picker.dart';
import '../../widgets/score_result_actions.dart';
import '../../widgets/score_view.dart';

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});

  @override
  ConsumerState<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends ConsumerState<UploadScreen> {
  final _result = ScoreResultController();

  bool _extractMelody = true;
  String _model = 'mt3';
  bool _busy = false;
  bool _previewPlaying = false;
  bool _trackLoading = false;
  String _statusText = '';
  double _progress = 0;
  String? _jobId;
  String? _musicXml;
  Uint8List? _midiBytes;
  String? _abcText;
  String? _error;
  List<MidiTrackInfo> _tracks = const [];
  final Set<int> _selected = {};
  int _reloadToken = 0;
  Timer? _reloadDebounce;

  static const int _maxBytes = ApiClient.maxUploadBytes;

  @override
  void initState() {
    super.initState();
    _result.onPlayingChanged = (playing) {
      if (mounted) setState(() => _previewPlaying = playing);
    };
    _result.attach();
  }

  @override
  void dispose() {
    _reloadDebounce?.cancel();
    _result.dispose();
    super.dispose();
  }

  List<int>? get _tracksQuery {
    if (_tracks.isEmpty) return null;
    if (_selected.length == _tracks.length) return null;
    final ids = _selected.toList()..sort();
    return ids;
  }

  Future<void> _pickAndUpload() async {
    await _result.stop();
    setState(() {
      _error = null;
      _musicXml = null;
      _midiBytes = null;
      _abcText = null;
      _jobId = null;
      _tracks = const [];
      _selected.clear();
    });

    final file = await FilePicker.pickFile(
      type: FileType.custom,
      allowedExtensions: const [
        'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', // audio
        'mp4', 'mov', 'mkv', 'webm', // video (audio extracted server-side)
      ],
    );
    if (file == null) return;

    final size = await file.length();
    if (size > _maxBytes) {
      setState(() => _error =
          '文件 ${(size / (1024 * 1024)).toStringAsFixed(1)}MB 超过 100MB 上限，请先压缩或裁剪');
      return;
    }
    final bytes = await file.readAsBytes();

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
        removeVocals: false,
        extractMelody: _extractMelody,
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
        List<MidiTrackInfo> tracks = const [];
        String? trackErr;
        try {
          tracks = (await api.getTracks(jobId)).tracks;
        } catch (e) {
          trackErr = '音轨列表加载失败: $e';
        }
        setState(() {
          _jobId = jobId;
          _tracks = tracks;
          _selected
            ..clear()
            ..addAll(tracks.map((t) => t.index));
          if (trackErr != null) {
            _error = trackErr;
          }
        });
        await _loadSelection(immediate: true);
      }
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loadSelection({bool immediate = false}) async {
    final jobId = _jobId;
    if (jobId == null) return;
    if (_tracks.isNotEmpty && _selected.isEmpty) {
      setState(() => _error = '请至少勾选一条音轨');
      return;
    }

    if (!immediate) {
      _reloadDebounce?.cancel();
      _reloadDebounce = Timer(const Duration(milliseconds: 280), () {
        _loadSelection(immediate: true);
      });
      return;
    }

    final token = ++_reloadToken;
    final api = ref.read(apiClientProvider);
    final q = _tracksQuery;
    setState(() {
      _trackLoading = true;
      _error = null;
    });
    try {
      final xml = await api.getMusicXml(jobId, tracks: q);
      Uint8List? midi;
      String? abc;
      try {
        midi = Uint8List.fromList(await api.getMidi(jobId, tracks: q));
      } catch (_) {
        midi = null;
      }
      try {
        abc = await api.getAbc(jobId, tracks: q);
      } catch (_) {
        abc = null;
      }
      if (!mounted || token != _reloadToken) return;
      await _result.stop();
      setState(() {
        _musicXml = xml;
        _midiBytes = midi;
        _abcText = abc;
      });
    } catch (e) {
      if (mounted && token == _reloadToken) {
        setState(() => _error = '加载选中音轨失败: $e');
      }
    } finally {
      if (mounted && token == _reloadToken) {
        setState(() => _trackLoading = false);
      }
    }
  }

  void _toggleTrack(int index, bool? checked) {
    setState(() {
      if (checked == true) {
        _selected.add(index);
      } else {
        _selected.remove(index);
      }
    });
    _loadSelection();
  }

  void _selectAllTracks(bool all) {
    setState(() {
      _selected.clear();
      if (all) {
        _selected.addAll(_tracks.map((t) => t.index));
      }
    });
    _loadSelection();
  }

  Future<void> _togglePreview() async {
    final midi = _midiBytes;
    if (midi == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('当前结果没有 MIDI，无法试听（请升级后端）')),
      );
      return;
    }
    if (_tracks.isNotEmpty && _selected.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请至少勾选一条音轨再试听')),
      );
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    try {
      await _result.togglePreview(midiBytes: midi);
    } catch (e) {
      if (mounted) {
        messenger.showSnackBar(SnackBar(content: Text('试听失败: $e')));
      }
    }
  }

  Future<void> _export(String kind) async {
    if (kind == 'preview') {
      await _togglePreview();
      return;
    }
    final export = const ScoreExport();
    final messenger = ScaffoldMessenger.of(context);
    final api = ref.read(apiClientProvider);
    final jobId = _jobId;
    try {
      switch (kind) {
        case 'musicxml':
          final xml = _musicXml;
          if (xml == null) return;
          final where = await export.saveMusicXmlText(xml, name: 'upload');
          messenger.showSnackBar(SnackBar(content: Text('已导出 MusicXML：$where')));
        case 'midi':
          final midi = _midiBytes;
          if (midi == null) {
            messenger.showSnackBar(
              const SnackBar(content: Text('当前结果没有 MIDI')),
            );
            return;
          }
          final where = await export.saveMidiBytes(midi, name: 'upload');
          messenger.showSnackBar(SnackBar(content: Text('已导出 MIDI：$where')));
        case 'midi_raw':
          if (jobId == null) return;
          final raw = Uint8List.fromList(await api.getMidiRaw(jobId));
          final where =
              await export.saveMidiBytes(raw, name: 'transcription_raw');
          messenger.showSnackBar(SnackBar(content: Text('已导出原始 MIDI：$where')));
        case 'abc':
          var abc = _abcText;
          if (abc == null || abc.trim().isEmpty) {
            messenger.showSnackBar(
              const SnackBar(content: Text('当前结果没有 ABC')),
            );
            return;
          }
          final where = await export.saveAbcText(abc, name: 'upload');
          messenger.showSnackBar(SnackBar(content: Text('已导出 ABC：$where')));
        case 'pdf':
          final xml = _musicXml;
          if (xml == null) return;
          final svg = await ref.read(verovioRendererProvider).render(xml);
          await export.sharePdf(svg, name: 'upload');
          messenger.showSnackBar(const SnackBar(content: Text('已导出 PDF')));
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('导出失败: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasResult = _musicXml != null && !_busy;
    return Scaffold(
      appBar: AppBar(
        title: const Text('上传音频/视频转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        actions: [
          ScoreResultActions(
            enabled: hasResult && !_trackLoading,
            playing: _previewPlaying,
            includeAbc: true,
            includeRawMidi: _jobId != null,
            onPreview: _togglePreview,
            onExport: _export,
          ),
        ],
      ),
      body: Column(
        children: [
          SwitchListTile(
            title: const Text('只提取主旋律（人声）'),
            subtitle: const Text('Demucs 分离人声后转录；关闭则转完整混音'),
            value: _extractMelody,
            onChanged: _busy ? null : (v) => setState(() => _extractMelody = v),
          ),
          ListTile(
            title: const Text('转录模型'),
            trailing: DropdownButton<String>(
              value: _model,
              items: const [
                DropdownMenuItem(value: 'mt3', child: Text('MT3 (默认)')),
                DropdownMenuItem(
                    value: 'basic_pitch', child: Text('Basic Pitch (轻量)')),
              ],
              onChanged:
                  _busy ? null : (v) => setState(() => _model = v ?? 'mt3'),
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
          if (_tracks.isNotEmpty)
            MidiTrackPicker(
              tracks: _tracks,
              selected: _selected,
              enabled: !_busy && !_trackLoading,
              onToggle: _toggleTrack,
              onSelectAll: _selectAllTracks,
            ),
          if (_trackLoading) const LinearProgressIndicator(minHeight: 2),
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
