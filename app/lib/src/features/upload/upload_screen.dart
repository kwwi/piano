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

  bool _extractMelody = false;
  bool _splitAudio = false;
  double _splitSeconds = 30;
  String _model = 'muscriptor';
  bool _busy = false;
  bool _previewPlaying = false;
  bool _trackLoading = false;
  bool _previewLoading = false;
  String _statusText = '';
  double _progress = 0;
  String? _jobId;
  String? _musicXml;
  Uint8List? _midiBytes;
  String? _abcText;
  String? _error;
  List<MidiTrackInfo> _tracks = const [];
  /// Draft selection tokens: ``0``, ``m0``, ``c0``, …
  final Set<String> _selected = {};
  /// Last selection applied to MusicXML / export MIDI / ABC.
  final Set<String> _applied = {};
  int _reloadToken = 0;
  int _previewToken = 0;

  static const int _maxBytes = ApiClient.maxUploadBytes;

  bool get _selectionDirty {
    if (_tracks.isEmpty) return false;
    if (_selected.length != _applied.length) return true;
    return !_selected.containsAll(_applied);
  }

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
    _result.dispose();
    super.dispose();
  }

  List<String>? _tracksQueryFor(Set<String> ids) {
    if (_tracks.isEmpty) return null;
    final allSources = _tracks
        .map((t) => MidiTrackPicker.sourceToken(t.index))
        .toSet();
    // Full original multi-track only (no derived) → omit query.
    if (ids.length == allSources.length &&
        ids.containsAll(allSources) &&
        ids.every((t) => !t.startsWith('m') && !t.startsWith('c'))) {
      return null;
    }
    final sorted = ids.toList()
      ..sort((a, b) {
        int rank(String t) {
          if (t.startsWith('m')) return 1000000 + int.parse(t.substring(1));
          if (t.startsWith('c')) return 2000000 + int.parse(t.substring(1));
          return int.parse(t);
        }

        return rank(a).compareTo(rank(b));
      });
    return sorted;
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
      _applied.clear();
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
        extractMelody: _model == 'muscriptor' ? false : _extractMelody,
        model: _model,
        splitAudio: _model == 'muscriptor' || _model == 'crepe'
            ? false
            : _splitAudio,
        splitSeconds: _splitSeconds,
        arrangement: 'full',
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
            ..addAll(tracks.map((t) => MidiTrackPicker.sourceToken(t.index)));
          _applied
            ..clear()
            ..addAll(tracks.map((t) => MidiTrackPicker.sourceToken(t.index)));
          if (trackErr != null) {
            _error = trackErr;
          }
        });
        await _applySelection();
      }
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Regenerate MusicXML / MIDI for the current draft selection.
  /// ABC is fetched lazily on export (it is slow and unused by the preview).
  Future<void> _applySelection() async {
    final jobId = _jobId;
    if (jobId == null) return;
    if (_tracks.isNotEmpty && _selected.isEmpty) {
      setState(() => _error = '请至少勾选一条音轨');
      return;
    }

    final token = ++_reloadToken;
    final api = ref.read(apiClientProvider);
    final q = _tracksQueryFor(_selected);
    setState(() {
      _trackLoading = true;
      _error = null;
      _abcText = null; // invalidate until next export
    });
    try {
      final xmlFuture = api.getMusicXml(jobId, tracks: q);
      final midiFuture = () async {
        try {
          return Uint8List.fromList(await api.getMidi(jobId, tracks: q));
        } catch (_) {
          return null;
        }
      }();
      final xml = await xmlFuture;
      final midi = await midiFuture;
      if (!mounted || token != _reloadToken) return;
      await _result.stop();
      setState(() {
        _musicXml = xml;
        _midiBytes = midi;
        _applied
          ..clear()
          ..addAll(_selected);
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

  void _toggleToken(String token, bool? checked) {
    setState(() {
      if (checked == true) {
        _selected.add(token);
      } else {
        _selected.remove(token);
      }
      _error = null;
    });
  }

  void _selectAllSources(bool all) {
    setState(() {
      _selected.clear();
      if (all) {
        _selected.addAll(
          _tracks.map((t) => MidiTrackPicker.sourceToken(t.index)),
        );
      }
      _error = null;
    });
  }

  /// Preview uses the current checkbox selection (not only last-confirmed).
  Future<void> _togglePreview() async {
    if (_previewPlaying) {
      await _result.stop();
      return;
    }
    if (_tracks.isNotEmpty && _selected.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请至少勾选一条音轨再试听')),
      );
      return;
    }

    final jobId = _jobId;
    final messenger = ScaffoldMessenger.of(context);
    final token = ++_previewToken;

    try {
      late final Uint8List midi;
      final cached = _midiBytes;
      if (!_selectionDirty && cached != null && cached.isNotEmpty) {
        midi = cached;
      } else {
        if (jobId == null) {
          messenger.showSnackBar(
            const SnackBar(content: Text('当前结果没有 MIDI，无法试听')),
          );
          return;
        }
        setState(() => _previewLoading = true);
        final api = ref.read(apiClientProvider);
        final q = _tracksQueryFor(_selected);
        final fetched =
            Uint8List.fromList(await api.getMidi(jobId, tracks: q));
        if (!mounted || token != _previewToken) return;
        if (fetched.isEmpty) {
          messenger.showSnackBar(
            const SnackBar(content: Text('当前结果没有 MIDI，无法试听（请升级后端）')),
          );
          return;
        }
        midi = fetched;
      }
      await _result.togglePreview(midiBytes: midi);
    } catch (e) {
      if (mounted) {
        messenger.showSnackBar(SnackBar(content: Text('试听失败: $e')));
      }
    } finally {
      if (mounted && token == _previewToken) {
        setState(() => _previewLoading = false);
      }
    }
  }

  Future<void> _export(String kind) async {
    if (kind == 'preview') {
      await _togglePreview();
      return;
    }
    if (_selectionDirty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('音轨选择已变更，请先点「确认」再导出谱子')),
      );
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
            if (jobId == null) {
              messenger.showSnackBar(
                const SnackBar(content: Text('当前结果没有 ABC')),
              );
              return;
            }
            try {
              final fetched = await api.getAbc(
                jobId,
                tracks: _tracksQueryFor(_applied),
              );
              abc = fetched;
              if (mounted) setState(() => _abcText = fetched);
            } catch (e) {
              messenger.showSnackBar(SnackBar(content: Text('生成 ABC 失败: $e')));
              return;
            }
          }
          if (abc.trim().isEmpty) {
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
          final renderer = ref.read(verovioRendererProvider);
          final first = await renderer.engrave(xml, page: 1);
          final svgs = <String>[first.svg];
          for (var p = 2; p <= first.pageCount; p++) {
            svgs.add((await renderer.engrave(xml, page: p)).svg);
          }
          final where = await export.sharePdfPages(svgs, name: 'upload');
          messenger.showSnackBar(SnackBar(content: Text('已导出 PDF：$where')));
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('导出失败: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasResult = _musicXml != null && !_busy;
    final actionsEnabled =
        hasResult && !_trackLoading && !_previewLoading;
    return Scaffold(
      appBar: AppBar(
        title: const Text('上传音频/视频转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        actions: [
          ScoreResultActions(
            enabled: actionsEnabled,
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
          if (_model != 'muscriptor')
            SwitchListTile(
              title: const Text('只提取主旋律（人声）'),
              subtitle: const Text('Demucs 分离人声后转录；关闭则转完整混音'),
              value: _extractMelody,
              onChanged:
                  _busy ? null : (v) => setState(() => _extractMelody = v),
            ),
          if (_model != 'muscriptor' && _model != 'crepe') ...[
            SwitchListTile(
              title: const Text('分段转录'),
              subtitle: Text(
                _splitAudio
                    ? '先按 ${_splitSeconds.toInt()} 秒切段，再逐段转谱并合并（适合长音频 / MT3）'
                    : '整段一次转录',
              ),
              value: _splitAudio,
              onChanged:
                  _busy ? null : (v) => setState(() => _splitAudio = v),
            ),
            if (_splitAudio)
              ListTile(
                title: const Text('分段时长'),
                trailing: DropdownButton<double>(
                  value: _splitSeconds,
                  items: const [
                    DropdownMenuItem(value: 15, child: Text('15 秒')),
                    DropdownMenuItem(value: 30, child: Text('30 秒')),
                    DropdownMenuItem(value: 45, child: Text('45 秒')),
                    DropdownMenuItem(value: 60, child: Text('60 秒')),
                  ],
                  onChanged: _busy
                      ? null
                      : (v) => setState(() => _splitSeconds = v ?? 30),
                ),
              ),
          ],
          ListTile(
            title: const Text('转录模型'),
            subtitle: _model == 'muscriptor'
                ? const Text('完整混音 → 多轨 MIDI；下方勾选音轨后导出/试听')
                : null,
            trailing: DropdownButton<String>(
              value: _model,
              items: const [
                DropdownMenuItem(
                    value: 'muscriptor',
                    child: Text('MuScriptor (多乐器混音)')),
                DropdownMenuItem(value: 'mt3', child: Text('MT3 (多轨)')),
                DropdownMenuItem(
                    value: 'crepe', child: Text('CREPE (人声主旋律)')),
                DropdownMenuItem(
                    value: 'basic_pitch', child: Text('Basic Pitch (轻量)')),
              ],
              onChanged: _busy
                  ? null
                  : (v) => setState(() => _model = v ?? 'muscriptor'),
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
              dirty: _selectionDirty,
              enabled: !_busy,
              confirming: _trackLoading,
              onToggleToken: _toggleToken,
              onSelectAllSources: _selectAllSources,
              onConfirm: _applySelection,
            ),
          if (_trackLoading || _previewLoading)
            const LinearProgressIndicator(minHeight: 2),
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
