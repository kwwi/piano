import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../core/notation/verovio_renderer.dart';

/// Renders a MusicXML/MEI string to staff notation using Verovio and displays
/// the resulting SVG with pinch-to-zoom. Shows a spinner while engraving and a
/// readable error card on failure.
class ScoreView extends ConsumerStatefulWidget {
  final String musicXml;
  final EdgeInsetsGeometry padding;

  const ScoreView({
    super.key,
    required this.musicXml,
    this.padding = const EdgeInsets.all(12),
  });

  @override
  ConsumerState<ScoreView> createState() => _ScoreViewState();
}

class _ScoreViewState extends ConsumerState<ScoreView> {
  late Future<String> _svg;

  @override
  void initState() {
    super.initState();
    _svg = _render();
  }

  @override
  void didUpdateWidget(covariant ScoreView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.musicXml != widget.musicXml) {
      setState(() => _svg = _render());
    }
  }

  Future<String> _render() {
    return ref.read(verovioRendererProvider).render(widget.musicXml);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<String>(
      future: _svg,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return _ErrorCard(message: '$_engraveError\n${snapshot.error}');
        }
        final svg = snapshot.data ?? '';
        if (svg.isEmpty) {
          return const _ErrorCard(message: '未生成五线谱 (empty SVG)');
        }
        return Padding(
          padding: widget.padding,
          child: InteractiveViewer(
            minScale: 0.5,
            maxScale: 6,
            child: Center(
              child: SvgPicture.string(
                svg,
                fit: BoxFit.contain,
                theme: const SvgTheme(currentColor: Color(0xFF000000)),
              ),
            ),
          ),
        );
      },
    );
  }

  static const String _engraveError = '五线谱渲染失败 (engraving failed):';
}

class _ErrorCard extends StatelessWidget {
  final String message;
  const _ErrorCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Card(
        color: Theme.of(context).colorScheme.errorContainer,
        margin: const EdgeInsets.all(16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            message,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onErrorContainer,
            ),
          ),
        ),
      ),
    );
  }
}
