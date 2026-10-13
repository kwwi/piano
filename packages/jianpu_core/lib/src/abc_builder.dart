import 'jianpu_model.dart';
import 'pitch.dart';

/// Converts a [JianpuScore] IR into standard ABC notation text.
///
/// Uses ``L:1/4`` so a plain number = one quarter note. Output is suitable for
/// ABC players / editors and for the app's ABC export path.
class AbcBuilder {
  const AbcBuilder();

  String build(JianpuScore score) {
    final sb = StringBuffer();
    sb.writeln('X:1');
    if (score.title != null && score.title!.trim().isNotEmpty) {
      sb.writeln('T:${score.title!.trim()}');
    }
    if (score.composer != null && score.composer!.trim().isNotEmpty) {
      sb.writeln('C:${score.composer!.trim()}');
    }
    sb.writeln('M:${score.beats}/${score.beatType}');
    sb.writeln('L:1/4');
    sb.writeln('Q:1/4=${score.tempo}');
    sb.writeln('K:${_abcKey(score.tonic)}');

    final body = StringBuffer();
    for (var m = 0; m < score.measures.length; m++) {
      if (m > 0) body.write(' | ');
      final notes = score.measures[m].notes;
      for (var i = 0; i < notes.length; i++) {
        if (i > 0) body.write(' ');
        body.write(_note(score, notes[i]));
      }
    }
    if (score.measures.isNotEmpty) body.write(' |');
    sb.writeln(body.toString().trim());
    return sb.toString();
  }

  String _abcKey(String tonic) {
    // Major keys only (jianpu `1=` is major movable-do).
    final t = tonic.trim();
    if (t.isEmpty) return 'C';
    return t;
  }

  String _note(JianpuScore score, JianpuNote note) {
    final dur = _duration(note.quarterLength);
    if (note.isRest) return 'z$dur';

    final p = spell(score.tonic, note);
    final letter = _abcPitch(p);
    return '$letter$dur';
  }

  /// ABC pitch relative to middle C (= ``C``).
  String _abcPitch(SpelledPitch p) {
    final step = p.step.toUpperCase();
    final acc = switch (p.alter) {
      > 0 => '^' * p.alter,
      < 0 => '_' * (-p.alter),
      _ => '',
    };

    // Scientific octave: C4 = middle C → ABC ``C``; C5 → ``c``; C3 → ``C,``.
    if (p.octave >= 5) {
      final ticks = p.octave - 5;
      return '$acc${step.toLowerCase()}${"'" * ticks}';
    }
    final commas = 4 - p.octave;
    return '$acc$step${',' * commas}';
  }

  /// Duration suffix with ``L:1/4`` (1 = quarter).
  String _duration(double quarterLength) {
    const eps = 1e-4;
    if ((quarterLength - 1.0).abs() < eps) return '';
    if ((quarterLength - 2.0).abs() < eps) return '2';
    if ((quarterLength - 3.0).abs() < eps) return '3';
    if ((quarterLength - 4.0).abs() < eps) return '4';
    if ((quarterLength - 1.5).abs() < eps) return '3/2';
    if ((quarterLength - 0.5).abs() < eps) return '/2';
    if ((quarterLength - 0.75).abs() < eps) return '3/4';
    if ((quarterLength - 0.25).abs() < eps) return '/4';
    if ((quarterLength - 0.125).abs() < eps) return '/8';

    // Fallback: rationalize as n/d quarters.
    final n = (quarterLength * 8).round(); // eighths
    if (n <= 0) return '';
    if (n % 8 == 0) return '${n ~/ 8}';
    if (n % 4 == 0) return '${n ~/ 4}/2';
    if (n % 2 == 0) return '${n ~/ 2}/4';
    return '$n/8';
  }
}
