import 'dart:math' as math;
import 'dart:typed_data';

import 'package:image/image.dart' as img;

/// Optical Music Recognition for Jianpu images.
///
/// Pipeline:
///   1. Decode → grayscale → **deskew** (projection-profile angle search)
///   2. Adaptive threshold → row split → connected-component glyphs
///   3. Classify each glyph as digit `0-7`, bar `|`, extender `-`, or noise
///   4. Emit Jianpu DSL for the editable preview
///
/// This is a lightweight on-device recognizer aimed at **printed / neat**
/// Jianpu. Handwritten drafts still need user correction in the preview
/// dialog (by design).
class JianpuOmr {
  const JianpuOmr();

  /// Deskew [imageBytes] (JPEG/PNG) and return re-encoded PNG bytes.
  Uint8List deskew(Uint8List imageBytes) {
    final decoded = img.decodeImage(imageBytes);
    if (decoded == null) return Uint8List.fromList(imageBytes);
    final gray = img.grayscale(decoded);
    final angle = _estimateSkewDegrees(gray);
    final fixed = angle.abs() < 0.3
        ? gray
        : img.copyRotate(gray, angle: -angle, interpolation: img.Interpolation.linear);
    return Uint8List.fromList(img.encodePng(fixed));
  }

  /// Full recognize: deskew → glyph OCR → Jianpu DSL.
  Future<OmrResult> recognize(Uint8List imageBytes) async {
    final decoded = img.decodeImage(imageBytes);
    if (decoded == null) {
      return OmrResult(
        dsl: _emptyDraft('(无法解码图片)'),
        deskewedBytes: imageBytes,
        confidence: 0,
        isStub: false,
        message: '无法解码图片，请换一张更清晰的照片',
      );
    }

    final gray = img.grayscale(decoded);
    final angle = _estimateSkewDegrees(gray);
    final deskewed = angle.abs() < 0.3
        ? gray
        : img.copyRotate(gray, angle: -angle, interpolation: img.Interpolation.linear);
    final deskewedBytes = Uint8List.fromList(img.encodePng(deskewed));

    final binary = _otsuThreshold(deskewed);
    final rows = _splitRows(binary);
    if (rows.isEmpty) {
      return OmrResult(
        dsl: _emptyDraft('(未检测到谱行)'),
        deskewedBytes: deskewedBytes,
        confidence: 0,
        message: '未检测到简谱行，请保证纸面平整、对比清晰后重试',
      );
    }

    final lines = <String>[];
    var classified = 0;
    var total = 0;
    for (final row in rows) {
      final glyphs = _connectedComponents(binary, row);
      final tokens = <String>[];
      for (final g in glyphs) {
        total++;
        final t = _classifyGlyph(binary, g);
        if (t != null) {
          classified++;
          tokens.add(t);
        }
      }
      final line = _tokensToLine(tokens);
      if (line.isNotEmpty) lines.add(line);
    }

    if (lines.isEmpty) {
      return OmrResult(
        dsl: _emptyDraft('(未能识别音符)'),
        deskewedBytes: deskewedBytes,
        confidence: 0,
        message: '纠偏已完成，但未能识别出音符。请在下方按图片手补简谱。',
      );
    }

    final confidence = total == 0 ? 0.0 : classified / total;
    final dsl = StringBuffer()
      ..writeln('key: 1=C')
      ..writeln('time: 4/4')
      ..writeln('tempo: 100')
      ..writeln('title: (从图片识别 — 请校对)')
      ..writeln('---');
    for (final line in lines) {
      dsl.writeln(line);
    }

    return OmrResult(
      dsl: dsl.toString(),
      deskewedBytes: deskewedBytes,
      confidence: confidence.clamp(0.0, 1.0),
      message: confidence < 0.4
          ? '识别置信度偏低，请仔细校对后再转五线谱'
          : '已完成纠偏与识别，请校对后应用',
    );
  }

  String _emptyDraft(String titleHint) => '''key: 1=C
time: 4/4
tempo: 100
title: $titleHint
---
1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
''';

  /// Search skew angle in ±15° by maximizing horizontal projection variance.
  double _estimateSkewDegrees(img.Image gray) {
    // Downscale for speed.
    final small = gray.width > 800
        ? img.copyResize(gray, width: 800,
            interpolation: img.Interpolation.average)
        : gray;
    var bestAngle = 0.0;
    var bestScore = -1.0;
    for (var a = -15.0; a <= 15.0; a += 0.5) {
      final rotated = a.abs() < 1e-6
          ? small
          : img.copyRotate(small, angle: a, interpolation: img.Interpolation.nearest);
      final score = _projectionVariance(rotated);
      if (score > bestScore) {
        bestScore = score;
        bestAngle = a;
      }
    }
    // Fine search around best.
    for (var a = bestAngle - 0.5; a <= bestAngle + 0.5; a += 0.1) {
      final rotated = img.copyRotate(small, angle: a, interpolation: img.Interpolation.nearest);
      final score = _projectionVariance(rotated);
      if (score > bestScore) {
        bestScore = score;
        bestAngle = a;
      }
    }
    return bestAngle;
  }

  double _projectionVariance(img.Image gray) {
    final h = gray.height;
    final w = gray.width;
    final proj = List<int>.filled(h, 0);
    for (var y = 0; y < h; y++) {
      var sum = 0;
      for (var x = 0; x < w; x++) {
        final p = gray.getPixel(x, y);
        // Ink is dark.
        if (p.luminance < 128) sum++;
      }
      proj[y] = sum;
    }
    final mean = proj.reduce((a, b) => a + b) / h;
    var varSum = 0.0;
    for (final v in proj) {
      final d = v - mean;
      varSum += d * d;
    }
    return varSum / h;
  }

  img.Image _otsuThreshold(img.Image gray) {
    final hist = List<int>.filled(256, 0);
    final total = gray.width * gray.height;
    for (var y = 0; y < gray.height; y++) {
      for (var x = 0; x < gray.width; x++) {
        hist[gray.getPixel(x, y).luminance.toInt().clamp(0, 255)]++;
      }
    }
    var sum = 0.0;
    for (var i = 0; i < 256; i++) {
      sum += i * hist[i];
    }
    var sumB = 0.0;
    var wB = 0;
    var maxVar = -1.0;
    var threshold = 128;
    for (var t = 0; t < 256; t++) {
      wB += hist[t];
      if (wB == 0) continue;
      final wF = total - wB;
      if (wF == 0) break;
      sumB += t * hist[t];
      final mB = sumB / wB;
      final mF = (sum - sumB) / wF;
      final between = wB * wF * (mB - mF) * (mB - mF);
      if (between > maxVar) {
        maxVar = between;
        threshold = t;
      }
    }
    final out = img.Image(width: gray.width, height: gray.height);
    for (var y = 0; y < gray.height; y++) {
      for (var x = 0; x < gray.width; x++) {
        final v = gray.getPixel(x, y).luminance < threshold ? 0 : 255;
        out.setPixelRgb(x, y, v, v, v);
      }
    }
    return out;
  }

  /// Row bands where horizontal ink density exceeds a fraction of the max.
  List<_RowBand> _splitRows(img.Image binary) {
    final h = binary.height;
    final w = binary.width;
    final proj = List<int>.filled(h, 0);
    var maxP = 0;
    for (var y = 0; y < h; y++) {
      var s = 0;
      for (var x = 0; x < w; x++) {
        if (binary.getPixel(x, y).r == 0) s++;
      }
      proj[y] = s;
      if (s > maxP) maxP = s;
    }
    if (maxP == 0) return const [];
    final cutoff = math.max(3, (maxP * 0.08).round());
    final bands = <_RowBand>[];
    var inBand = false;
    var start = 0;
    for (var y = 0; y < h; y++) {
      final ink = proj[y] >= cutoff;
      if (ink && !inBand) {
        inBand = true;
        start = y;
      } else if (!ink && inBand) {
        inBand = false;
        if (y - start >= 8) bands.add(_RowBand(start, y));
      }
    }
    if (inBand && h - start >= 8) bands.add(_RowBand(start, h));
    // Drop tiny noise bands; merge near neighbours.
    final merged = <_RowBand>[];
    for (final b in bands) {
      if (merged.isNotEmpty && b.top - merged.last.bottom < 6) {
        merged[merged.length - 1] = _RowBand(merged.last.top, b.bottom);
      } else if (b.bottom - b.top >= 10) {
        merged.add(b);
      }
    }
    return merged;
  }

  List<_Glyph> _connectedComponents(img.Image binary, _RowBand row) {
    final w = binary.width;
    final h = row.bottom - row.top;
    final visited = List<bool>.filled(w * h, false);
    bool ink(int x, int y) =>
        x >= 0 &&
        x < w &&
        y >= row.top &&
        y < row.bottom &&
        binary.getPixel(x, y).r == 0;

    final glyphs = <_Glyph>[];
    for (var y = row.top; y < row.bottom; y++) {
      for (var x = 0; x < w; x++) {
        final idx = (y - row.top) * w + x;
        if (visited[idx] || !ink(x, y)) continue;
        // BFS flood fill.
        var minX = x, maxX = x, minY = y, maxY = y, count = 0;
        final qx = <int>[x];
        final qy = <int>[y];
        visited[idx] = true;
        while (qx.isNotEmpty) {
          final cx = qx.removeLast();
          final cy = qy.removeLast();
          count++;
          if (cx < minX) minX = cx;
          if (cx > maxX) maxX = cx;
          if (cy < minY) minY = cy;
          if (cy > maxY) maxY = cy;
          for (final d in const [
            [-1, 0],
            [1, 0],
            [0, -1],
            [0, 1],
          ]) {
            final nx = cx + d[0];
            final ny = cy + d[1];
            if (!ink(nx, ny)) continue;
            final nIdx = (ny - row.top) * w + nx;
            if (visited[nIdx]) continue;
            visited[nIdx] = true;
            qx.add(nx);
            qy.add(ny);
          }
        }
        final bw = maxX - minX + 1;
        final bh = maxY - minY + 1;
        // Filter dust.
        if (count < 12 || bw < 2 || bh < 4) continue;
        glyphs.add(_Glyph(minX, minY, maxX, maxY, count));
      }
    }
    glyphs.sort((a, b) => a.minX.compareTo(b.minX));
    return glyphs;
  }

  /// Classify a glyph into a Jianpu token, or null if noise.
  String? _classifyGlyph(img.Image binary, _Glyph g) {
    final bw = g.width;
    final bh = g.height;
    final aspect = bw / bh;
    final density = g.inkCount / (bw * bh);

    // Vertical barline: tall and thin.
    if (aspect < 0.35 && bh > bw * 2.2 && density > 0.25) return '|';
    // Horizontal extender / dash: wide and flat.
    if (aspect > 2.2 && bw > bh * 2 && density > 0.2 && bh < 18) return '-';

    // Digit-like: sample a normalized 8x12 grid and match templates.
    final grid = _sampleGrid(binary, g, 8, 12);
    final holes = _countHoles(grid, 8, 12);
    final best = _matchDigit(grid, holes, aspect);
    return best;
  }

  List<int> _sampleGrid(img.Image binary, _Glyph g, int gw, int gh) {
    final out = List<int>.filled(gw * gh, 0);
    for (var gy = 0; gy < gh; gy++) {
      for (var gx = 0; gx < gw; gx++) {
        final x = g.minX + ((gx + 0.5) * g.width / gw).floor();
        final y = g.minY + ((gy + 0.5) * g.height / gh).floor();
        if (binary.getPixel(x.clamp(0, binary.width - 1), y.clamp(0, binary.height - 1)).r == 0) {
          out[gy * gw + gx] = 1;
        }
      }
    }
    return out;
  }

  int _countHoles(List<int> grid, int gw, int gh) {
    // Count background components that do not touch the border → holes.
    final vis = List<bool>.filled(gw * gh, false);
    var holes = 0;
    bool isBg(int i) => grid[i] == 0;

    for (var i = 0; i < grid.length; i++) {
      if (!isBg(i) || vis[i]) continue;
      var touchesBorder = false;
      final stack = <int>[i];
      vis[i] = true;
      while (stack.isNotEmpty) {
        final cur = stack.removeLast();
        final x = cur % gw;
        final y = cur ~/ gw;
        if (x == 0 || y == 0 || x == gw - 1 || y == gh - 1) touchesBorder = true;
        for (final d in const [
          [1, 0],
          [-1, 0],
          [0, 1],
          [0, -1],
        ]) {
          final nx = x + d[0];
          final ny = y + d[1];
          if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
          final ni = ny * gw + nx;
          if (vis[ni] || !isBg(ni)) continue;
          vis[ni] = true;
          stack.add(ni);
        }
      }
      if (!touchesBorder) holes++;
    }
    return holes;
  }

  String? _matchDigit(List<int> grid, int holes, double aspect) {
    // Hand-tuned heuristics + tiny template scores for printed digits.
    final ink = grid.where((v) => v == 1).length;
    if (ink < 6) return null;

    // Prefer hole-based cues first.
    if (holes >= 1 && aspect > 0.35 && aspect < 1.2) {
      // 0, 4, 6, 8(not used), 9(not used) — jianpu uses 0-7.
      final topInk = grid.sublist(0, 8 * 4).where((v) => v == 1).length;
      final botInk = grid.sublist(8 * 8).where((v) => v == 1).length;
      if (topInk < botInk * 0.7) return '6';
      if ((topInk - botInk).abs() < 4) return '0';
      return '4';
    }

    // No hole → 1,2,3,5,7
    if (aspect < 0.45) return '1';

    // Score against crude templates (row-major 8x12 ink masks).
    final scores = <String, double>{};
    for (final e in _digitTemplates.entries) {
      var agree = 0;
      var total = 0;
      for (var i = 0; i < grid.length; i++) {
        if (e.value[i] == 1 || grid[i] == 1) {
          total++;
          if (e.value[i] == grid[i]) agree++;
        }
      }
      scores[e.key] = total == 0 ? 0 : agree / total;
    }
    final ranked = scores.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    if (ranked.first.value < 0.42) return null;
    return ranked.first.key;
  }

  /// Merge classified tokens into a DSL line with barlines.
  String _tokensToLine(List<String> tokens) {
    if (tokens.isEmpty) return '';
    final parts = <String>[];
    for (var i = 0; i < tokens.length; i++) {
      final t = tokens[i];
      if (t == '|') {
        if (parts.isNotEmpty && parts.last != '|') {
          parts.add('|');
        }
      } else if (t == '-') {
        // Attach as extender after previous note when possible.
        if (parts.isNotEmpty && RegExp(r'^[0-7]').hasMatch(parts.last)) {
          parts[parts.length - 1] = '${parts.last} -';
        } else {
          parts.add('-');
        }
      } else {
        parts.add(t);
      }
    }
    var line = parts.join(' ').replaceAll(RegExp(r'\s+\|\s+'), ' | ');
    if (!line.trimRight().endsWith('|')) line = '$line |';
    return line;
  }
}

class _RowBand {
  final int top;
  final int bottom;
  const _RowBand(this.top, this.bottom);
}

class _Glyph {
  final int minX, minY, maxX, maxY, inkCount;
  const _Glyph(this.minX, this.minY, this.maxX, this.maxY, this.inkCount);
  int get width => maxX - minX + 1;
  int get height => maxY - minY + 1;
}

/// Very small 8×12 digit templates (1 = ink). Good enough for neat print.
final Map<String, List<int>> _digitTemplates = {
  '1': _t([
    '00110000',
    '01110000',
    '00110000',
    '00110000',
    '00110000',
    '00110000',
    '00110000',
    '00110000',
    '00110000',
    '00110000',
    '01111000',
    '01111000',
  ]),
  '2': _t([
    '01111100',
    '11000110',
    '00000110',
    '00001100',
    '00011000',
    '00110000',
    '01100000',
    '11000000',
    '11000000',
    '11000000',
    '11111110',
    '11111110',
  ]),
  '3': _t([
    '01111100',
    '11000110',
    '00000110',
    '00001100',
    '00111100',
    '00111100',
    '00001100',
    '00000110',
    '00000110',
    '11000110',
    '01111100',
    '00111000',
  ]),
  '5': _t([
    '11111110',
    '11111110',
    '11000000',
    '11000000',
    '11111100',
    '11111110',
    '00000110',
    '00000110',
    '00000110',
    '11000110',
    '01111100',
    '00111000',
  ]),
  '7': _t([
    '11111110',
    '11111110',
    '00000110',
    '00001100',
    '00001100',
    '00011000',
    '00011000',
    '00110000',
    '00110000',
    '01100000',
    '01100000',
    '01100000',
  ]),
};

List<int> _t(List<String> rows) {
  final out = <int>[];
  for (final r in rows) {
    for (var i = 0; i < r.length; i++) {
      out.add(r.codeUnitAt(i) == 49 ? 1 : 0); // '1'
    }
  }
  return out;
}

/// Outcome of a Jianpu OMR pass.
class OmrResult {
  final String dsl;
  final Uint8List deskewedBytes;
  final double confidence;
  final bool isStub;
  final String? message;

  const OmrResult({
    required this.dsl,
    required this.deskewedBytes,
    required this.confidence,
    this.isStub = false,
    this.message,
  });
}
