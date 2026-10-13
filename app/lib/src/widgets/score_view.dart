import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../core/notation/verovio_renderer.dart';

/// Renders a MusicXML/MEI string to staff notation using Verovio and displays
/// the resulting SVG with pinch-to-zoom and page navigation.
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
  late Future<EngravedPage> _pageFuture;
  int _page = 1;
  int _pageCount = 1;
  int _loadToken = 0;

  @override
  void initState() {
    super.initState();
    _pageFuture = _engrave(1);
  }

  @override
  void didUpdateWidget(covariant ScoreView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.musicXml != widget.musicXml) {
      _page = 1;
      _pageCount = 1;
      setState(() {
        _pageFuture = _engrave(1);
      });
    }
  }

  Future<EngravedPage> _engrave(int page) {
    final token = ++_loadToken;
    return ref
        .read(verovioRendererProvider)
        .engrave(widget.musicXml, page: page)
        .then((engraved) {
      if (mounted && token == _loadToken) {
        setState(() {
          _page = engraved.page;
          _pageCount = engraved.pageCount;
        });
      }
      return engraved;
    });
  }

  void _goToPage(int page) {
    if (page < 1 || page > _pageCount || page == _page) return;
    setState(() {
      _page = page;
      _pageFuture = _engrave(page);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: FutureBuilder<EngravedPage>(
            future: _pageFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return _ErrorCard(
                  message: '$_engraveError\n${snapshot.error}',
                );
              }
              final engraved = snapshot.data;
              final svg = engraved?.svg ?? '';
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
          ),
        ),
        if (_pageCount > 1) _PageBar(
          page: _page,
          pageCount: _pageCount,
          onPrev: () => _goToPage(_page - 1),
          onNext: () => _goToPage(_page + 1),
        ),
      ],
    );
  }

  static const String _engraveError = '五线谱渲染失败 (engraving failed):';
}

class _PageBar extends StatelessWidget {
  const _PageBar({
    required this.page,
    required this.pageCount,
    required this.onPrev,
    required this.onNext,
  });

  final int page;
  final int pageCount;
  final VoidCallback onPrev;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.7),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                tooltip: '上一页',
                onPressed: page > 1 ? onPrev : null,
                icon: const Icon(Icons.chevron_left),
              ),
              Text(
                '$page / $pageCount',
                style: theme.textTheme.titleSmall,
              ),
              IconButton(
                tooltip: '下一页',
                onPressed: page < pageCount ? onNext : null,
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
        ),
      ),
    );
  }
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
