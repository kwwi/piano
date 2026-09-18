import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:verovio_flutter/verovio_flutter.dart';

/// One engraved Verovio page plus total page count for the loaded score.
class EngravedPage {
  const EngravedPage({
    required this.svg,
    required this.page,
    required this.pageCount,
  });

  final String svg;
  final int page;
  final int pageCount;
}

/// Thin wrapper around [VerovioAsyncService] that lazily boots the toolkit on a
/// worker isolate and engraves MusicXML/MEI into SVG on-device (offline).
class VerovioRenderer {
  VerovioAsyncService? _service;
  Future<VerovioAsyncService>? _boot;
  String? _loadedData;

  Future<VerovioAsyncService> _ensure() {
    return _boot ??= _spawn();
  }

  Future<VerovioAsyncService> _spawn() async {
    final resourcePath = await VerovioResourceManager.ensureVerovioAssetsReady();
    final service = await VerovioAsyncService.spawn(resourcePath: resourcePath);
    _service = service;
    return service;
  }

  Future<void> _loadIfNeeded(VerovioAsyncService service, String data) async {
    if (_loadedData == data) return;
    await service.loadData(data);
    _loadedData = data;
  }

  /// Load [data] (MusicXML, MEI, ABC, …) and return the SVG for [page].
  ///
  /// The raw SVG is normalized (see [normalizeVerovioSvg]) so that `flutter_svg`
  /// renders it correctly on every platform.
  Future<String> render(String data, {int page = 1}) async {
    final engraved = await engrave(data, page: page);
    return engraved.svg;
  }

  /// Load [data] once (cached) and engrave [page], returning SVG + page count.
  Future<EngravedPage> engrave(String data, {int page = 1}) async {
    final service = await _ensure();
    await _loadIfNeeded(service, data);
    final pageCount = await service.pageCount;
    final total = pageCount < 1 ? 1 : pageCount;
    final safePage = page.clamp(1, total);
    final svg = await service.renderToSvg(safePage);
    return EngravedPage(
      svg: normalizeVerovioSvg(svg),
      page: safePage,
      pageCount: total,
    );
  }

  void dispose() {
    _service?.dispose();
    _service = null;
    _boot = null;
    _loadedData = null;
  }
}

/// Rewrites a Verovio SVG so it renders correctly under `flutter_svg`.
///
/// Verovio wraps the engraved page in a nested `<svg class="definition-scale"
/// viewBox="0 0 W*10 H*10">` element. `flutter_svg` does not honor the viewBox of
/// nested `<svg>` elements, so the content (drawn in 10x user units) ends up far
/// outside the visible canvas and the widget appears blank. This converts every
/// non-root `<svg>` into an equivalent `<g transform="…">` that reproduces the
/// viewBox mapping with plain transforms, and guarantees the root `<svg>` carries
/// a viewBox so `BoxFit.contain` can scale it.
String normalizeVerovioSvg(String svg) {
  final openTag = RegExp(r'<svg\b[^>]*>', caseSensitive: false);
  final matches = openTag.allMatches(svg).toList();
  if (matches.isEmpty) return svg;

  // --- 1. Ensure the root <svg> has a viewBox. ---
  final root = matches.first;
  var result = svg;
  final rootTag = root.group(0)!;
  if (!RegExp(r'viewBox\s*=', caseSensitive: false).hasMatch(rootTag)) {
    final w = _lengthAttr(rootTag, 'width');
    final h = _lengthAttr(rootTag, 'height');
    if (w != null && h != null) {
      final withViewBox = rootTag.replaceFirst(
        '<svg',
        '<svg viewBox="0 0 $w $h"',
      );
      result = result.replaceRange(root.start, root.end, withViewBox);
    }
  }

  // --- 2. Flatten nested <svg> into <g transform="…"> using a depth stack. ---
  // Re-scan the (possibly edited) string so indices stay valid.
  final buffer = StringBuffer();
  var cursor = 0;
  // Stack of parent user-space dimensions; root uses its own width/height.
  final parentDims = <List<double>>[];
  final rootDims = _rootDims(result) ?? [0, 0];

  final tokenRe = RegExp(r'<svg\b[^>]*>|</svg>', caseSensitive: false);
  var depth = 0;
  for (final m in tokenRe.allMatches(result)) {
    buffer.write(result.substring(cursor, m.start));
    cursor = m.end;
    final token = m.group(0)!;
    final isOpen = !token.startsWith('</');
    if (isOpen) {
      final selfClosing = RegExp(r'/>\s*$').hasMatch(token);
      if (depth == 0) {
        if (selfClosing) {
          // Invalid as root, but keep as empty svg rather than breaking depth.
          buffer.write(token);
        } else {
          buffer.write(token); // keep the root <svg> as-is
          parentDims.add(rootDims);
          depth++;
        }
      } else if (selfClosing) {
        // Nested self-closing <svg …/> → empty <g …></g> (no depth change).
        final parent = parentDims.last;
        final g = _svgOpenToGroup(token, parent[0], parent[1]);
        buffer.write('${g.tag}</g>');
      } else {
        final parent = parentDims.last;
        final g = _svgOpenToGroup(token, parent[0], parent[1]);
        buffer.write(g.tag);
        parentDims.add(g.childDims);
        depth++;
      }
    } else {
      if (depth <= 0) {
        buffer.write('</svg>');
        continue;
      }
      depth--;
      if (depth == 0) {
        buffer.write('</svg>');
      } else {
        buffer.write('</g>');
      }
      if (parentDims.isNotEmpty) parentDims.removeLast();
    }
  }
  buffer.write(result.substring(cursor));

  // --- 3. Inline the `stroke:currentColor` CSS rule. ---
  // Verovio only sets the stroke color of staff lines, stems, barlines, beams,
  // slurs, ties, etc. through a `<style>` selector. `flutter_svg` ignores CSS
  // selector blocks, so those shapes would draw with no stroke and disappear.
  // Mirror the rule by adding an explicit `stroke="currentColor"` to every
  // stroke-bearing shape that lacks an inline stroke; `SvgTheme.currentColor`
  // (set by the widget) then resolves it to a concrete color.
  var withStroke = _inlineStroke(buffer.toString());

  // --- 4. Drop the unused `<style>` block. ---
  // After inlining strokes, the CSS is redundant. Leaving it makes flutter_svg
  // log: "unhandled element <style/>".
  withStroke = withStroke.replaceAll(
    RegExp(r'<style\b[^>]*>[\s\S]*?</style>', caseSensitive: false),
    '',
  );
  return withStroke;
}

final _shapeTag =
    RegExp(r'<(path|rect|ellipse|polygon|polyline|line)\b([^>]*?)(/?)>');
final _hasStroke = RegExp(r'\bstroke\s*=');

String _inlineStroke(String svg) {
  return svg.replaceAllMapped(_shapeTag, (m) {
    final attrs = m.group(2)!;
    if (_hasStroke.hasMatch(attrs)) return m.group(0)!;
    return '<${m.group(1)}$attrs stroke="currentColor"${m.group(3)}>';
  });
}

class _GroupTag {
  _GroupTag(this.tag, this.childDims);
  final String tag;
  final List<double> childDims;
}

/// Converts a nested `<svg …>` opening tag into a `<g transform="…">` opening tag
/// that reproduces its `viewBox`/`x`/`y`/`width`/`height` mapping. [parentW]/
/// [parentH] are the user-space dimensions of the containing element, used when
/// the nested svg omits width/height (it then fills the parent).
_GroupTag _svgOpenToGroup(String tag, double parentW, double parentH) {
  final vb = _viewBox(tag);
  final x = _lengthAttr(tag, 'x') ?? 0;
  final y = _lengthAttr(tag, 'y') ?? 0;
  final targetW = _lengthAttr(tag, 'width') ?? parentW;
  final targetH = _lengthAttr(tag, 'height') ?? parentH;

  final transforms = <String>[];
  if (x != 0 || y != 0) transforms.add('translate($x, $y)');
  var childW = targetW;
  var childH = targetH;
  if (vb != null && vb[2] != 0 && vb[3] != 0) {
    final sx = targetW / vb[2];
    final sy = targetH / vb[3];
    if (sx != 1 || sy != 1) transforms.add('scale($sx, $sy)');
    if (vb[0] != 0 || vb[1] != 0) {
      transforms.add('translate(${-vb[0]}, ${-vb[1]})');
    }
    // Inside this element the user-space is the viewBox extent.
    childW = vb[2];
    childH = vb[3];
  }

  // Preserve style-bearing attributes that affect descendants.
  final carried = <String>[];
  for (final name in const ['class', 'color', 'font-family', 'style']) {
    final v = _rawAttr(tag, name);
    if (v != null) carried.add('$name="$v"');
  }

  final t = transforms.isEmpty ? '' : ' transform="${transforms.join(' ')}"';
  final extra = carried.isEmpty ? '' : ' ${carried.join(' ')}';
  return _GroupTag('<g$t$extra>', [childW, childH]);
}

List<double>? _rootDims(String svg) {
  final root = RegExp(r'<svg\b[^>]*>', caseSensitive: false).firstMatch(svg);
  if (root == null) return null;
  final tag = root.group(0)!;
  final vb = _viewBox(tag);
  if (vb != null && vb[2] != 0 && vb[3] != 0) return [vb[2], vb[3]];
  final w = _lengthAttr(tag, 'width');
  final h = _lengthAttr(tag, 'height');
  if (w != null && h != null) return [w, h];
  return null;
}

List<double>? _viewBox(String tag) {
  final m = RegExp(r'viewBox\s*=\s*"([^"]*)"', caseSensitive: false)
      .firstMatch(tag);
  if (m == null) return null;
  final parts = m
      .group(1)!
      .trim()
      .split(RegExp(r'[\s,]+'))
      .map(double.tryParse)
      .toList();
  if (parts.length != 4 || parts.any((e) => e == null)) return null;
  return parts.cast<double>();
}

/// Reads a numeric length attribute, tolerating a trailing `px` unit.
double? _lengthAttr(String tag, String name) {
  final raw = _rawAttr(tag, name);
  if (raw == null) return null;
  final cleaned = raw.replaceAll(RegExp(r'px$', caseSensitive: false), '').trim();
  return double.tryParse(cleaned);
}

String? _rawAttr(String tag, String name) {
  final m = RegExp('$name\\s*=\\s*"([^"]*)"', caseSensitive: false)
      .firstMatch(tag);
  return m?.group(1);
}

/// App-wide singleton renderer. Kept alive for the whole session so the toolkit
/// isolate is only spawned once.
final verovioRendererProvider = Provider<VerovioRenderer>((ref) {
  final renderer = VerovioRenderer();
  ref.onDispose(renderer.dispose);
  return renderer;
});
