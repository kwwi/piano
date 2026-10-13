/// Serializes a [JianpuScore] back to the text DSL that [JianpuParser] accepts.
///
/// Used by the staff / IR editor so users can round-trip: parse → edit IR →
/// write DSL → re-parse, and by the OMR preview when the recognizer yields a
/// structured score instead of raw text.
library;

import 'jianpu_model.dart';

class JianpuDslWriter {
  const JianpuDslWriter();

  String write(JianpuScore score) {
    final buf = StringBuffer()
      ..writeln('key: 1=${score.tonic}')
      ..writeln('time: ${score.beats}/${score.beatType}')
      ..writeln('tempo: ${score.tempo}');
    if (score.title != null && score.title!.isNotEmpty) {
      buf.writeln('title: ${score.title}');
    }
    if (score.composer != null && score.composer!.isNotEmpty) {
      buf.writeln('composer: ${score.composer}');
    }
    buf.writeln('---');

    for (final measure in score.measures) {
      final tokens = <String>[];
      for (final n in measure.notes) {
        tokens.add(_note(n));
      }
      buf.writeln('${tokens.join(' ')} |');
    }
    return buf.toString();
  }

  String _note(JianpuNote n) {
    if (n.isRest) {
      return '0${_durationSuffix(n.quarterLength)}';
    }
    final acc = switch (n.accidental) {
      Accidental.sharp => '#',
      Accidental.flat => 'b',
      Accidental.natural => '=',
      Accidental.none => '',
    };
    final oct = n.octave > 0
        ? "'" * n.octave
        : (n.octave < 0 ? ',' * -n.octave : '');
    return '$acc${n.degree}$oct${_durationSuffix(n.quarterLength)}';
  }

  /// Encode duration relative to a plain quarter note (== 1.0).
  ///
  /// Underlines (halving) and dots are preferred; remaining whole beats become
  /// trailing `-` extenders so the parser round-trips cleanly.
  String _durationSuffix(double ql) {
    if (ql <= 0) return '';
    // Prefer underline / dotted forms for common values.
    if ((ql - 1.0).abs() < 1e-6) return '';
    if ((ql - 0.5).abs() < 1e-6) return '_';
    if ((ql - 0.25).abs() < 1e-6) return '__';
    if ((ql - 0.125).abs() < 1e-6) return '___';
    if ((ql - 1.5).abs() < 1e-6) return '.';
    if ((ql - 0.75).abs() < 1e-6) return '_.';
    if ((ql - 2.0).abs() < 1e-6) return ' -';
    if ((ql - 3.0).abs() < 1e-6) return ' - -';
    if ((ql - 4.0).abs() < 1e-6) return ' - - -';
    // Fallback: nearest underline chain + extenders.
    var base = 1.0;
    var unders = '';
    while (base > ql * 1.01 && unders.length < 4) {
      base /= 2;
      unders += '_';
    }
    final extenders = ((ql - base) / 1.0).round().clamp(0, 8);
    return unders + (' -' * extenders);
  }
}
