import 'jianpu_model.dart';

/// Recovers plausible note durations when OCR / transcription only produced
/// pitch sequences (every note defaulting to a quarter).
///
/// Two common OCR failure modes are handled:
///   1. **Missing barlines** — a run of N quarters where N is a multiple of the
///      time-signature numerator is packed into N/beats measures.
///   2. **Missing underlines / extenders** — within a measure, durations are
///      scaled (×1/2, ×1/4, ×2, …) or proportionally fitted so the measure
///      sums to the expected number of quarter notes.
class JianpuRhythmFitter {
  const JianpuRhythmFitter();

  /// Grid used when snapping (sixteenth-note resolution via 0.25 quarters…;
  /// also allows 0.125 after an extra scale step).
  static const double grid = 0.125;

  JianpuScore fit(JianpuScore score) {
    final target = _measureTarget(score);
    final packed = <JianpuMeasure>[];
    for (final m in score.measures) {
      packed.addAll(_packIfNeeded(m.notes, score.beats, target));
    }
    final fitted = [
      for (final m in packed) JianpuMeasure(_fitNotes(m.notes, target)),
    ];
    return score.copyWith(measures: fitted);
  }

  double _measureTarget(JianpuScore score) {
    return score.beats * (4.0 / score.beatType);
  }

  /// Split a long all-quarter run into bar-sized chunks when barlines were lost.
  ///
  /// Exact 2× / 4× beat counts are left alone so [_fitNotes] can scale them to
  /// eighths / sixteenths (OCR usually drops `_` underlines but keeps `|`).
  /// Longer multiples (12, 20, …) are packed as missing barlines instead.
  List<JianpuMeasure> _packIfNeeded(
    List<JianpuNote> notes,
    int beats,
    double target,
  ) {
    if (notes.isEmpty) return [const JianpuMeasure([])];
    final allQuarters =
        notes.every((n) => (n.quarterLength - 1.0).abs() < 1e-6);
    if (!allQuarters || notes.length <= beats || notes.length % beats != 0) {
      return [JianpuMeasure(notes)];
    }
    // Dense single bar of eighths/sixteenths misread as quarters.
    if (notes.length == beats * 2 || notes.length == beats * 4) {
      return [JianpuMeasure(notes)];
    }
    final out = <JianpuMeasure>[];
    for (var i = 0; i < notes.length; i += beats) {
      out.add(JianpuMeasure(notes.sublist(i, i + beats)));
    }
    return out;
  }

  List<JianpuNote> _fitNotes(List<JianpuNote> notes, double target) {
    if (notes.isEmpty) return notes;
    final sum = notes.fold<double>(0, (a, n) => a + n.quarterLength);
    if (sum <= 0) return notes;
    if ((sum - target).abs() < 0.08) return notes;

    // Prefer exact power-of-two scales (missed underlines / extenders).
    for (final factor in const [0.5, 0.25, 0.125, 2.0, 4.0]) {
      final scaled = sum * factor;
      if ((scaled - target).abs() <= target * 0.12) {
        return [
          for (final n in notes)
            n.copyWith(quarterLength: _snap(n.quarterLength * factor)),
        ];
      }
    }

    // Few notes undershooting the bar → extend the last note (missing "-").
    if (sum < target && notes.length <= target + 1) {
      final out = List<JianpuNote>.of(notes);
      final last = out.removeLast();
      out.add(last.copyWith(
        quarterLength: _snap(last.quarterLength + (target - sum)),
      ));
      return out;
    }

    // Proportional fit to the bar, then fix residual on the last note.
    final ratio = target / sum;
    final out = <JianpuNote>[
      for (final n in notes)
        n.copyWith(
          quarterLength: _snap(n.quarterLength * ratio).clamp(grid, target),
        ),
    ];
    var filled = out.fold<double>(0, (a, n) => a + n.quarterLength);
    final delta = target - filled;
    if (delta.abs() >= grid / 2 && out.isNotEmpty) {
      final last = out.removeLast();
      out.add(last.copyWith(
        quarterLength: _snap((last.quarterLength + delta).clamp(grid, target)),
      ));
    }
    return out;
  }

  double _snap(double ql) {
    final q = (ql / grid).round() * grid;
    return q < grid ? grid : q;
  }
}
