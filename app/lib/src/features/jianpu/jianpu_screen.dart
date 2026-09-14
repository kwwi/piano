import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/jianpu/jianpu.dart';
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

  JianpuScore? _score;
  String? _musicXml;
  String? _error;

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
