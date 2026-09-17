import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:just_audio/just_audio.dart';

import '../../core/backend/api_client.dart';
import '../../core/jianpu/jianpu.dart';
import '../../core/jianpu/omr.dart';
import '../../core/notation/score_export.dart';
import '../../core/notation/score_preview_player.dart';
import '../../core/notation/verovio_renderer.dart';
import '../../widgets/jianpu_view.dart';
import '../../widgets/score_result_actions.dart';
import '../../widgets/score_view.dart';

class JianpuScreen extends ConsumerStatefulWidget {
  const JianpuScreen({super.key});

  @override
  ConsumerState<JianpuScreen> createState() => _JianpuScreenState();
}

class _JianpuScreenState extends ConsumerState<JianpuScreen> {
  final _controller = TextEditingController(text: JianpuSamples.twinkle);
  final _parser = const JianpuParser();
  final _builder = const MusicXmlBuilder();
  final _dslWriter = const JianpuDslWriter();
  final _rhythmFitter = const JianpuRhythmFitter();
  final _omr = const JianpuOmr();
  final _picker = ImagePicker();
  final _previewPlayer = ScorePreviewPlayer();

  JianpuScore? _score;
  String? _musicXml;
  String? _error;
  bool _omrBusy = false;
  bool _previewPlaying = false;
  /// 0 = 简谱, 1 = 五线谱
  int _previewMode = 0;
  StreamSubscription<PlayerState>? _previewSub;

  @override
  void initState() {
    super.initState();
    _reparse();
    _controller.addListener(_reparse);
    _previewSub = _previewPlayer.playerStateStream.listen((state) {
      final playing = state.playing &&
          state.processingState != ProcessingState.completed &&
          state.processingState != ProcessingState.idle;
      if (mounted && playing != _previewPlaying) {
        setState(() => _previewPlaying = playing);
      }
      if (state.processingState == ProcessingState.completed && mounted) {
        setState(() => _previewPlaying = false);
      }
    });
  }

  @override
  void dispose() {
    _previewSub?.cancel();
    _controller.removeListener(_reparse);
    _controller.dispose();
    _previewPlayer.dispose();
    super.dispose();
  }

  void _reparse() {
    try {
      final score = _parser.parse(_controller.text);
      final xml = _builder.build(score);
      if (_previewPlaying) {
        _previewPlayer.stop();
      }
      setState(() {
        _score = score;
        _musicXml = xml;
        _error = null;
        _previewPlaying = false;
      });
    } on JianpuParseException catch (e) {
      setState(() => _error = e.toString());
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  Future<void> _togglePreview() async {
    if (_previewPlaying) {
      await _previewPlayer.stop();
      if (mounted) setState(() => _previewPlaying = false);
      return;
    }
    final score = _score;
    if (score == null) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      setState(() => _previewPlaying = true);
      await _previewPlayer.play(_scoreForExport(score));
    } catch (e) {
      if (mounted) {
        setState(() => _previewPlaying = false);
        messenger.showSnackBar(SnackBar(content: Text('试听失败: $e')));
      }
    }
  }

  Future<void> _export(String kind) async {
    if (kind == 'preview') {
      await _togglePreview();
      return;
    }
    final score = _score;
    final xml = _musicXml;
    if (score == null || xml == null) return;
    final exportScore = _scoreForExport(score);
    final exportXml = identical(exportScore, score)
        ? xml
        : _builder.build(exportScore);
    final export = const ScoreExport();
    final messenger = ScaffoldMessenger.of(context);
    try {
      switch (kind) {
        case 'musicxml':
          final where = await export.saveMusicXml(exportScore);
          messenger.showSnackBar(SnackBar(content: Text('已导出 MusicXML：$where')));
        case 'midi':
          final where = await export.saveMidi(exportScore);
          messenger.showSnackBar(SnackBar(content: Text('已导出 MIDI：$where')));
        case 'pdf':
          final renderer = ref.read(verovioRendererProvider);
          final first = await renderer.engrave(exportXml, page: 1);
          final svgs = <String>[first.svg];
          for (var p = 2; p <= first.pageCount; p++) {
            svgs.add((await renderer.engrave(exportXml, page: p)).svg);
          }
          final where = await export.sharePdfPages(svgs);
          messenger.showSnackBar(SnackBar(content: Text('已导出 PDF：$where')));
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('导出失败: $e')));
    }
  }

  /// If any measure does not fill the time signature (typical OCR pitch-only
  /// output), recover durations before export so MIDI/PDF keep a pulse.
  JianpuScore _scoreForExport(JianpuScore score) {
    final target = score.beats * (4.0 / score.beatType);
    final needsFit = score.measures.any((m) {
      final sum = m.notes.fold<double>(0, (a, n) => a + n.quarterLength);
      return (sum - target).abs() > 0.2;
    });
    if (needsFit) return _rhythmFitter.fit(score);
    // Pitch-only OCR that already packed N quarters per bar still needs a
    // pulse when bars are oddly dense relative to typical melody writing —
    // leave filled measures alone (user may have intentional quarters).
    return score;
  }

  /// OCR usually returns pitch-only tokens (all quarters). Refit durations so
  /// each measure fills the time signature before writing back to the editor —
  /// this restores rhythm for the live staff preview, MIDI and PDF exports.
  String _withRecoveredRhythm(String dsl) {
    try {
      final parsed = _parser.parse(dsl);
      final fitted = _rhythmFitter.fit(parsed);
      return _dslWriter.write(fitted);
    } catch (_) {
      return dsl;
    }
  }

  /// Image → prefer backend OCR → local deskew/glyph fallback → editable preview.
  Future<void> _importFromImage() async {
    if (_omrBusy) return;
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_library),
              title: const Text('从相册选择简谱图片'),
              onTap: () => Navigator.pop(ctx, ImageSource.gallery),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera),
              title: const Text('拍照简谱草稿'),
              onTap: () => Navigator.pop(ctx, ImageSource.camera),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;

    final file = await _picker.pickImage(source: source, imageQuality: 95);
    if (file == null) return;

    setState(() => _omrBusy = true);
    try {
      final bytes = await file.readAsBytes();
      OmrResult result;

      // Prefer the backend OCR (Pillow deskew + Tesseract). Local glyph
      // classification is only a fallback for when the API is unreachable —
      // it cannot reliably read commercial sheets with chords/lyrics.
      try {
        final api = ref.read(apiClientProvider);
        final remote = await api.recognizeJianpuImage(
          bytes: bytes,
          filename: file.name,
        );
        result = OmrResult(
          dsl: _withRecoveredRhythm(remote.dsl),
          deskewedBytes: remote.deskewedPng != null
              ? Uint8List.fromList(remote.deskewedPng!)
              : _omr.deskew(bytes),
          confidence: remote.confidence,
          message: '${remote.message}（已按拍号尝试恢复节奏，请再校对）',
        );
      } catch (e) {
        // Do not silently trust on-device digit soup for dense printed sheets.
        final local = await _omr.recognize(bytes);
        result = OmrResult(
          dsl: _withRecoveredRhythm(local.dsl),
          deskewedBytes: local.deskewedBytes,
          confidence: local.confidence,
          message:
              '后端识别失败（$e）。请确认已启动 uvicorn 且允许 CORS；复杂印刷谱请手补简谱。',
        );
      }

      if (!mounted) return;
      final edited = await showDialog<String>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => _OmrPreviewDialog(result: result),
      );
      if (edited != null && edited.trim().isNotEmpty) {
        // Fit again in case the user left pitch-only tokens while editing.
        _controller.text = _withRecoveredRhythm(edited);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('图片识别失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _omrBusy = false);
    }
  }

  /// Structured note editor over the IR, then write back to DSL.
  Future<void> _editStaffNotes() async {
    final score = _score;
    if (score == null) return;
    final edited = await showModalBottomSheet<JianpuScore>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => _StaffNoteEditor(score: score),
    );
    if (edited != null) {
      _controller.text = _dslWriter.write(edited);
    }
  }

  @override
  Widget build(BuildContext context) {
    final xml = _musicXml;
    return Scaffold(
      appBar: AppBar(
        title: const Text('简谱转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        actions: [
          ScoreResultActions(
            enabled: _score != null,
            playing: _previewPlaying,
            onPreview: _togglePreview,
            onExport: _export,
          ),
          IconButton(
            icon: _omrBusy
                ? const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.image_search),
            tooltip: '从图片识别简谱',
            onPressed: _omrBusy ? null : _importFromImage,
          ),
          IconButton(
            icon: const Icon(Icons.edit_note),
            tooltip: '编辑五线谱音符',
            onPressed: _score == null ? null : _editStaffNotes,
          ),
          IconButton(
            icon: const Icon(Icons.more_time),
            tooltip: '按拍号恢复节奏',
            onPressed: _score == null
                ? null
                : () {
                    final next = _withRecoveredRhythm(_controller.text);
                    _controller.text = next;
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('已按拍号尝试恢复节奏（请再校对 _ / -）'),
                      ),
                    );
                  },
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.library_music),
            tooltip: '示例',
            onSelected: (v) => _controller.text = JianpuSamples.all[v]!,
            itemBuilder: (context) => JianpuSamples.all.keys
                .map((k) => PopupMenuItem(value: k, child: Text(k)))
                .toList(),
          ),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth > 720;
          final editor = _buildEditor(context);
          final preview = _buildPreview(xml);
          if (wide) {
            return Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(child: editor),
                const VerticalDivider(width: 1),
                Expanded(child: preview),
              ],
            );
          }
          return Column(
            children: [
              Expanded(flex: 2, child: editor),
              const Divider(height: 1),
              Expanded(flex: 3, child: preview),
            ],
          );
        },
      ),
    );
  }

  Widget _buildEditor(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('简谱输入 (DSL)', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(
            "音符 1-7，0 休止；八度 ' 高 , 低；时值 _ 减半 . 附点；- 延长一拍；| 小节线",
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 8),
          Expanded(
            child: TextField(
              controller: _controller,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 15),
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                alignLabelWithHint: true,
                hintText: 'key: 1=C\ntime: 4/4\n---\n1 1 5 5 | 6 6 5 -',
              ),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildPreview(String? xml) {
    final score = _score;
    if (score == null) {
      return const Center(child: Text('修正简谱后显示预览'));
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
          child: SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('简谱'), icon: Icon(Icons.pin_outlined, size: 18)),
              ButtonSegment(value: 1, label: Text('五线谱'), icon: Icon(Icons.music_note, size: 18)),
            ],
            selected: {_previewMode},
            onSelectionChanged: (s) => setState(() => _previewMode = s.first),
          ),
        ),
        Expanded(
          child: _previewMode == 0
              ? JianpuView(score: score)
              : (xml == null
                  ? const Center(child: Text('无法生成五线谱'))
                  : ScoreView(musicXml: xml)),
        ),
      ],
    );
  }
}

/// Editable preview of OMR output (deskew thumbnail + DSL).
class _OmrPreviewDialog extends StatefulWidget {
  final OmrResult result;
  const _OmrPreviewDialog({required this.result});

  @override
  State<_OmrPreviewDialog> createState() => _OmrPreviewDialogState();
}

class _OmrPreviewDialogState extends State<_OmrPreviewDialog> {
  late final TextEditingController _ctrl;
  final _parser = const JianpuParser();
  JianpuScore? _previewScore;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.result.dsl);
    _reparsePreview();
    _ctrl.addListener(_reparsePreview);
  }

  void _reparsePreview() {
    try {
      final s = _parser.parse(_ctrl.text);
      if (mounted) setState(() => _previewScore = s);
    } catch (_) {
      if (mounted && _previewScore != null) {
        setState(() => _previewScore = null);
      }
    }
  }

  @override
  void dispose() {
    _ctrl.removeListener(_reparsePreview);
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final msg = widget.result.message;
    final pct = (widget.result.confidence * 100).round();
    return AlertDialog(
      title: const Text('识别结果 — 请校对后应用'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (msg != null && msg.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    '$msg（置信度 $pct%）',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  '提示：含和弦框/歌词的印刷谱无法 100% 自动对齐，请对照左侧缩略图逐行改数字后再应用。',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.tertiary,
                      ),
                ),
              ),
              if (widget.result.deskewedBytes.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Image.memory(
                      widget.result.deskewedBytes,
                      height: 120,
                      fit: BoxFit.contain,
                    ),
                  ),
                ),
              if (_previewScore != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: SizedBox(
                    height: 160,
                    width: double.infinity,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        border: Border.all(color: Theme.of(context).dividerColor),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: JianpuView(
                        score: _previewScore!,
                        padding: const EdgeInsets.all(8),
                      ),
                    ),
                  ),
                ),
              TextField(
                controller: _ctrl,
                maxLines: 12,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 14),
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  labelText: '识别出的简谱 (可编辑)',
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _ctrl.text),
          child: const Text('应用到编辑器'),
        ),
      ],
    );
  }
}

/// Flat list editor for notes in a [JianpuScore]. Saves by returning a new score.
class _StaffNoteEditor extends StatefulWidget {
  final JianpuScore score;
  const _StaffNoteEditor({required this.score});

  @override
  State<_StaffNoteEditor> createState() => _StaffNoteEditorState();
}

class _StaffNoteEditorState extends State<_StaffNoteEditor> {
  late List<JianpuNote> _notes;
  late String _tonic;
  late int _tempo;

  static const _durations = <double>[0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0];

  @override
  void initState() {
    super.initState();
    _notes = [
      for (final m in widget.score.measures) ...m.notes,
    ];
    _tonic = widget.score.tonic;
    _tempo = widget.score.tempo;
  }

  JianpuScore _buildScore() {
    // Pack notes back into measures by cumulative beats.
    final beats = widget.score.beats.toDouble();
    final measures = <JianpuMeasure>[];
    var bucket = <JianpuNote>[];
    var filled = 0.0;
    for (final n in _notes) {
      if (filled > 0 && filled + n.quarterLength > beats + 1e-6) {
        measures.add(JianpuMeasure(List.of(bucket)));
        bucket = [];
        filled = 0;
      }
      bucket.add(n);
      filled += n.quarterLength;
      if ((filled - beats).abs() < 1e-6 || filled >= beats) {
        measures.add(JianpuMeasure(List.of(bucket)));
        bucket = [];
        filled = 0;
      }
    }
    if (bucket.isNotEmpty) measures.add(JianpuMeasure(bucket));
    if (measures.isEmpty) measures.add(const JianpuMeasure([]));

    return widget.score.copyWith(
      tonic: _tonic,
      tempo: _tempo,
      measures: measures,
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.75,
        child: Column(
          children: [
            const ListTile(
              title: Text('编辑五线谱音符'),
              subtitle: Text('修改音级 / 时值后保存，将回写简谱并刷新预览'),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  const Text('调号 1='),
                  const SizedBox(width: 8),
                  DropdownButton<String>(
                    value: _tonic,
                    items: const ['C', 'G', 'D', 'A', 'E', 'F', 'Bb', 'Eb']
                        .map((t) => DropdownMenuItem(value: t, child: Text(t)))
                        .toList(),
                    onChanged: (v) => setState(() => _tonic = v ?? 'C'),
                  ),
                  const SizedBox(width: 24),
                  const Text('速度'),
                  Expanded(
                    child: Slider(
                      value: _tempo.toDouble(),
                      min: 40,
                      max: 200,
                      divisions: 160,
                      label: '$_tempo',
                      onChanged: (v) => setState(() => _tempo = v.round()),
                    ),
                  ),
                  Text('$_tempo'),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView.builder(
                itemCount: _notes.length,
                itemBuilder: (context, i) {
                  final n = _notes[i];
                  return ListTile(
                    leading: CircleAvatar(child: Text('${i + 1}')),
                    title: Row(
                      children: [
                        DropdownButton<int>(
                          value: n.degree,
                          items: List.generate(
                            8,
                            (d) => DropdownMenuItem(
                              value: d,
                              child: Text(d == 0 ? '0 休止' : '$d'),
                            ),
                          ),
                          onChanged: (v) => setState(() {
                            _notes[i] = n.copyWith(degree: v ?? n.degree);
                          }),
                        ),
                        const SizedBox(width: 12),
                        DropdownButton<int>(
                          value: n.octave.clamp(-2, 2),
                          items: const [
                            DropdownMenuItem(value: -2, child: Text(',,')),
                            DropdownMenuItem(value: -1, child: Text(',')),
                            DropdownMenuItem(value: 0, child: Text('中')),
                            DropdownMenuItem(value: 1, child: Text("'")),
                            DropdownMenuItem(value: 2, child: Text("''")),
                          ],
                          onChanged: (v) => setState(() {
                            _notes[i] = n.copyWith(octave: v ?? 0);
                          }),
                        ),
                        const SizedBox(width: 12),
                        DropdownButton<double>(
                          value: _durations.contains(n.quarterLength)
                              ? n.quarterLength
                              : 1.0,
                          items: _durations
                              .map(
                                (d) => DropdownMenuItem(
                                  value: d,
                                  child: Text('$d拍'),
                                ),
                              )
                              .toList(),
                          onChanged: (v) => setState(() {
                            _notes[i] = n.copyWith(quarterLength: v ?? 1);
                          }),
                        ),
                      ],
                    ),
                    trailing: IconButton(
                      icon: const Icon(Icons.delete_outline),
                      onPressed: () => setState(() => _notes.removeAt(i)),
                    ),
                  );
                },
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  OutlinedButton.icon(
                    onPressed: () => setState(() {
                      _notes.add(const JianpuNote(degree: 1, quarterLength: 1));
                    }),
                    icon: const Icon(Icons.add),
                    label: const Text('加音符'),
                  ),
                  const Spacer(),
                  TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, _buildScore()),
                    child: const Text('保存并刷新五线谱'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
