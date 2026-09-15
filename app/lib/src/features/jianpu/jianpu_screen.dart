import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/backend/api_client.dart';
import '../../core/jianpu/jianpu.dart';
import '../../core/jianpu/omr.dart';
import '../../core/notation/score_export.dart';
import '../../core/notation/verovio_renderer.dart';
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
  final _omr = const JianpuOmr();
  final _picker = ImagePicker();

  JianpuScore? _score;
  String? _musicXml;
  String? _error;
  bool _omrBusy = false;

  @override
  void initState() {
    super.initState();
    _reparse();
    _controller.addListener(_reparse);
  }

  @override
  void dispose() {
    _controller.removeListener(_reparse);
    _controller.dispose();
    super.dispose();
  }

  void _reparse() {
    try {
      final score = _parser.parse(_controller.text);
      final xml = _builder.build(score);
      setState(() {
        _score = score;
        _musicXml = xml;
        _error = null;
      });
    } on JianpuParseException catch (e) {
      setState(() => _error = e.toString());
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  Future<void> _export(String kind) async {
    final score = _score;
    final xml = _musicXml;
    if (score == null || xml == null) return;
    final export = const ScoreExport();
    final messenger = ScaffoldMessenger.of(context);
    try {
      switch (kind) {
        case 'musicxml':
          final f = await export.saveMusicXml(score);
          messenger.showSnackBar(SnackBar(content: Text('已保存 MusicXML: ${f.path}')));
        case 'midi':
          final f = await export.saveMidi(score);
          messenger.showSnackBar(SnackBar(content: Text('已保存 MIDI: ${f.path}')));
        case 'pdf':
          final svg = await ref.read(verovioRendererProvider).render(xml);
          await export.sharePdf(svg);
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('导出失败: $e')));
    }
  }

  /// Image → local deskew/OCR → (optional) backend OCR → editable preview.
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

    final file = await _picker.pickImage(source: source, imageQuality: 90);
    if (file == null) return;

    setState(() => _omrBusy = true);
    try {
      final bytes = await file.readAsBytes();
      var result = await _omr.recognize(bytes);

      // If on-device confidence is low, try the backend OCR (pytesseract when
      // available). Failures fall back to the local deskewed draft.
      if (result.confidence < 0.45) {
        try {
          final api = ref.read(apiClientProvider);
          final remote = await api.recognizeJianpuImage(
            bytes: bytes,
            filename: file.name,
          );
          if (remote.dsl.trim().isNotEmpty) {
            result = OmrResult(
              dsl: remote.dsl,
              deskewedBytes: remote.deskewedPng != null
                  ? Uint8List.fromList(remote.deskewedPng!)
                  : result.deskewedBytes,
              confidence: remote.confidence,
              message: remote.message,
            );
          }
        } catch (_) {
          // Keep local result; backend may be offline (common on web demos).
        }
      }

      if (!mounted) return;
      final edited = await showDialog<String>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => _OmrPreviewDialog(result: result),
      );
      if (edited != null && edited.trim().isNotEmpty) {
        _controller.text = edited;
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
          PopupMenuButton<String>(
            icon: const Icon(Icons.library_music),
            tooltip: '示例',
            onSelected: (v) => _controller.text = JianpuSamples.all[v]!,
            itemBuilder: (context) => JianpuSamples.all.keys
                .map((k) => PopupMenuItem(value: k, child: Text(k)))
                .toList(),
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.download),
            tooltip: '导出',
            onSelected: _export,
            itemBuilder: (context) => const [
              PopupMenuItem(value: 'musicxml', child: Text('导出 MusicXML')),
              PopupMenuItem(value: 'midi', child: Text('导出 MIDI')),
              PopupMenuItem(value: 'pdf', child: Text('导出 / 分享 PDF')),
            ],
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
    if (xml == null) {
      return const Center(child: Text('修正简谱后显示五线谱预览'));
    }
    return ScoreView(musicXml: xml);
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

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.result.dsl);
  }

  @override
  void dispose() {
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
