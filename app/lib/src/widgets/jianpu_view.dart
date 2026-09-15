import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/jianpu/jianpu.dart';

/// Renders a [JianpuScore] as authentic numbered notation (简谱):
/// digits, octave dots, underlines, extension dashes, barlines, header.
class JianpuView extends StatelessWidget {
  final JianpuScore score;
  final EdgeInsetsGeometry padding;
  final Color ink;

  const JianpuView({
    super.key,
    required this.score,
    this.padding = const EdgeInsets.all(16),
    this.ink = const Color(0xFF111111),
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = math.max(280.0, constraints.maxWidth - 8);
        final layout = _JianpuLayout.layout(score, pageWidth: width);
        return Padding(
          padding: padding,
          child: InteractiveViewer(
            minScale: 0.6,
            maxScale: 4,
            child: SingleChildScrollView(
              child: CustomPaint(
                size: Size(width, layout.height),
                painter: _JianpuPainter(layout: layout, ink: ink),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _JianpuLayout {
  final JianpuScore score;
  final double pageWidth;
  final double height;
  final List<_LaidRow> rows;
  final Rect headerRect;

  const _JianpuLayout({
    required this.score,
    required this.pageWidth,
    required this.height,
    required this.rows,
    required this.headerRect,
  });

  static const double noteSlot = 28;
  static const double barGap = 10;
  static const double rowGap = 52;
  static const double headerH = 64;
  static const double leftPad = 12;
  static const double rightPad = 12;

  static _JianpuLayout layout(JianpuScore score, {required double pageWidth}) {
    final usable = pageWidth - leftPad - rightPad;
    final rows = <_LaidRow>[];
    var x = 0.0;
    var rowItems = <_LaidItem>[];

    void flush() {
      if (rowItems.isEmpty) return;
      rows.add(_LaidRow(List.of(rowItems)));
      rowItems = [];
      x = 0;
    }

    for (var mi = 0; mi < score.measures.length; mi++) {
      final measure = score.measures[mi];
      final measureWidth = _measureWidth(measure);
      if (x > 0 && x + measureWidth > usable) {
        flush();
      }
      var localX = x;
      for (final note in measure.notes) {
        final w = _noteWidth(note);
        rowItems.add(
          _LaidItem.note(
            note: note,
            x: leftPad + localX,
            width: w,
          ),
        );
        localX += w;
      }
      rowItems.add(
        _LaidItem.bar(
          x: leftPad + localX,
          measureIndex: mi + 1,
        ),
      );
      x = localX + barGap;
    }
    flush();

    final height = headerH +
        (rows.isEmpty ? rowGap : rows.length * rowGap) +
        24;
    return _JianpuLayout(
      score: score,
      pageWidth: pageWidth,
      height: height,
      rows: rows,
      headerRect: Rect.fromLTWH(0, 0, pageWidth, headerH),
    );
  }

  static double _noteWidth(JianpuNote n) {
    // Base slot + space for extenders (each added quarter ≈ half slot).
    final extras = math.max(0, (n.quarterLength - 1.0).floor());
    return noteSlot + extras * (noteSlot * 0.55);
  }

  static double _measureWidth(JianpuMeasure m) {
    var w = 0.0;
    for (final n in m.notes) {
      w += _noteWidth(n);
    }
    return w + barGap;
  }
}

class _LaidRow {
  final List<_LaidItem> items;
  const _LaidRow(this.items);
}

enum _ItemKind { note, bar }

class _LaidItem {
  final _ItemKind kind;
  final JianpuNote? note;
  final double x;
  final double width;
  final int? measureIndex;

  const _LaidItem._({
    required this.kind,
    this.note,
    required this.x,
    this.width = 0,
    this.measureIndex,
  });

  factory _LaidItem.note({
    required JianpuNote note,
    required double x,
    required double width,
  }) =>
      _LaidItem._(kind: _ItemKind.note, note: note, x: x, width: width);

  factory _LaidItem.bar({required double x, required int measureIndex}) =>
      _LaidItem._(kind: _ItemKind.bar, x: x, measureIndex: measureIndex);
}

class _JianpuPainter extends CustomPainter {
  final _JianpuLayout layout;
  final Color ink;

  _JianpuPainter({required this.layout, required this.ink});

  @override
  void paint(Canvas canvas, Size size) {
    final score = layout.score;
    _paintHeader(canvas, score);

    for (var ri = 0; ri < layout.rows.length; ri++) {
      final baseline =
          _JianpuLayout.headerH + ri * _JianpuLayout.rowGap + 28;
      for (final item in layout.rows[ri].items) {
        if (item.kind == _ItemKind.bar) {
          _paintBar(canvas, item.x, baseline);
        } else if (item.note != null) {
          _paintNote(canvas, item.note!, item.x, item.width, baseline);
        }
      }
    }
  }

  void _paintHeader(Canvas canvas, JianpuScore score) {
    final title = score.title?.trim();
    if (title != null && title.isNotEmpty) {
      final tp = TextPainter(
        text: TextSpan(
          text: title,
          style: TextStyle(
            color: ink,
            fontSize: 22,
            fontWeight: FontWeight.w600,
            fontFamily: 'NotoSansSC',
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: layout.pageWidth - 24);
      tp.paint(
        canvas,
        Offset((layout.pageWidth - tp.width) / 2, 6),
      );
    }

    final meta = TextPainter(
      text: TextSpan(
        text: '1=${score.tonic}    ${score.beats}/${score.beatType}    ♩=${score.tempo}',
        style: TextStyle(
          color: ink,
          fontSize: 13,
          fontFamily: 'Roboto',
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    meta.paint(canvas, const Offset(_JianpuLayout.leftPad, 40));
  }

  void _paintBar(Canvas canvas, double x, double baseline) {
    final paint = Paint()
      ..color = ink
      ..strokeWidth = 1.4;
    canvas.drawLine(
      Offset(x + 2, baseline - 16),
      Offset(x + 2, baseline + 14),
      paint,
    );
  }

  void _paintNote(
    Canvas canvas,
    JianpuNote note,
    double x,
    double width,
    double baseline,
  ) {
    final centerX = x + _JianpuLayout.noteSlot / 2;

    // Accidental
    final acc = switch (note.accidental) {
      Accidental.sharp => '#',
      Accidental.flat => 'b',
      Accidental.natural => '♮',
      Accidental.none => '',
    };
    if (acc.isNotEmpty) {
      final ap = TextPainter(
        text: TextSpan(
          text: acc,
          style: TextStyle(color: ink, fontSize: 11, fontFamily: 'Roboto'),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      ap.paint(canvas, Offset(centerX - ap.width / 2 - 10, baseline - 22));
    }

    // Octave dots above
    if (note.octave > 0) {
      for (var i = 0; i < note.octave; i++) {
        canvas.drawCircle(
          Offset(centerX, baseline - 20 - i * 6.0),
          1.6,
          Paint()..color = ink,
        );
      }
    }

    // Degree / rest
    final glyph = note.isRest ? '0' : '${note.degree}';
    final digit = TextPainter(
      text: TextSpan(
        text: glyph,
        style: TextStyle(
          color: ink,
          fontSize: 22,
          fontWeight: FontWeight.w500,
          fontFamily: 'Roboto',
          height: 1.0,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    digit.paint(
      canvas,
      Offset(centerX - digit.width / 2, baseline - digit.height + 2),
    );

    // Octave dots below
    if (note.octave < 0) {
      for (var i = 0; i < -note.octave; i++) {
        canvas.drawCircle(
          Offset(centerX, baseline + 10 + i * 6.0),
          1.6,
          Paint()..color = ink,
        );
      }
    }

    // Duration: underlines (halves) + extension dashes + augmentation dots
    final marks = _durationMarks(note.quarterLength);
    final underlinePaint = Paint()
      ..color = ink
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round;
    for (var u = 0; u < marks.underlines; u++) {
      final y = baseline + 8 + u * 3.5 + (note.octave < 0 ? 6.0 * -note.octave : 0);
      canvas.drawLine(
        Offset(centerX - 8, y),
        Offset(centerX + 8, y),
        underlinePaint,
      );
    }

    // Extension dashes for held beats (after the digit)
    if (marks.extenders > 0) {
      final dashPaint = Paint()
        ..color = ink
        ..strokeWidth = 1.6
        ..strokeCap = StrokeCap.round;
      for (var e = 0; e < marks.extenders; e++) {
        final dx = _JianpuLayout.noteSlot * 0.7 + e * _JianpuLayout.noteSlot * 0.55;
        canvas.drawLine(
          Offset(x + dx, baseline - 6),
          Offset(x + dx + 12, baseline - 6),
          dashPaint,
        );
      }
    }

    // Augmentation dot to the right of the digit
    if (marks.dotted) {
      canvas.drawCircle(
        Offset(centerX + digit.width / 2 + 5, baseline - 4),
        1.8,
        Paint()..color = ink,
      );
    }
  }

  /// Decompose quarterLength into underline count, extender dashes, dotted.
  ({int underlines, int extenders, bool dotted}) _durationMarks(double ql) {
    if (ql <= 0) return (underlines: 0, extenders: 0, dotted: false);

    // Match common jianpu values.
    const eps = 0.08;
    if ((ql - 4.0).abs() < eps) {
      return (underlines: 0, extenders: 3, dotted: false);
    }
    if ((ql - 3.0).abs() < eps) {
      return (underlines: 0, extenders: 2, dotted: false);
    }
    if ((ql - 2.0).abs() < eps) {
      return (underlines: 0, extenders: 1, dotted: false);
    }
    if ((ql - 1.5).abs() < eps) {
      return (underlines: 0, extenders: 0, dotted: true);
    }
    if ((ql - 1.0).abs() < eps) {
      return (underlines: 0, extenders: 0, dotted: false);
    }
    if ((ql - 0.75).abs() < eps) {
      return (underlines: 1, extenders: 0, dotted: true);
    }
    if ((ql - 0.5).abs() < eps) {
      return (underlines: 1, extenders: 0, dotted: false);
    }
    if ((ql - 0.375).abs() < eps) {
      return (underlines: 2, extenders: 0, dotted: true);
    }
    if ((ql - 0.25).abs() < eps) {
      return (underlines: 2, extenders: 0, dotted: false);
    }
    if ((ql - 0.125).abs() < eps) {
      return (underlines: 3, extenders: 0, dotted: false);
    }

    // Generic: peel off whole quarters as dashes, then underlines for remainder.
    var remain = ql;
    var extenders = 0;
    while (remain > 1.0 + eps) {
      extenders++;
      remain -= 1.0;
    }
    var dotted = false;
    if (remain > 0.5 + eps && remain < 1.0 - eps) {
      // e.g. 0.75 with no exact match path
      dotted = true;
      remain /= 1.5;
    }
    var underlines = 0;
    var unit = 1.0;
    while (remain + eps < unit && underlines < 4) {
      unit /= 2;
      underlines++;
    }
    if ((remain - unit * 1.5).abs() < eps) {
      dotted = true;
    }
    return (underlines: underlines, extenders: extenders, dotted: dotted);
  }

  @override
  bool shouldRepaint(covariant _JianpuPainter oldDelegate) {
    return oldDelegate.layout != layout || oldDelegate.ink != ink;
  }
}
