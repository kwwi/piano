import 'jianpu_model.dart';
import 'pitch.dart';

/// Converts a [JianpuScore] IR into a MusicXML 3.1 (partwise) document string,
/// suitable for engraving with Verovio.
class MusicXmlBuilder {
  /// Divisions per quarter note. 480 supports up to 128th and common tuplets.
  static const int divisions = 480;

  const MusicXmlBuilder();

  String build(JianpuScore score) {
    final sb = StringBuffer();
    sb.writeln('<?xml version="1.0" encoding="UTF-8"?>');
    sb.writeln(
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">');
    sb.writeln('<score-partwise version="3.1">');

    if (score.title != null) {
      sb.writeln('  <work><work-title>${_esc(score.title!)}</work-title></work>');
    }
    if (score.composer != null) {
      sb.writeln('  <identification>');
      sb.writeln(
          '    <creator type="composer">${_esc(score.composer!)}</creator>');
      sb.writeln('  </identification>');
    }

    sb.writeln('  <part-list>');
    sb.writeln('    <score-part id="P1"><part-name>Melody</part-name></score-part>');
    sb.writeln('  </part-list>');
    sb.writeln('  <part id="P1">');

    for (var m = 0; m < score.measures.length; m++) {
      _writeMeasure(sb, score, m);
    }

    sb.writeln('  </part>');
    sb.writeln('</score-partwise>');
    return sb.toString();
  }

  void _writeMeasure(StringBuffer sb, JianpuScore score, int index) {
    sb.writeln('    <measure number="${index + 1}">');

    if (index == 0) {
      sb.writeln('      <attributes>');
      sb.writeln('        <divisions>$divisions</divisions>');
      sb.writeln(
          '        <key><fifths>${fifthsForTonic(score.tonic)}</fifths></key>');
      sb.writeln(
          '        <time><beats>${score.beats}</beats><beat-type>${score.beatType}</beat-type></time>');
      sb.writeln('        <clef><sign>G</sign><line>2</line></clef>');
      sb.writeln('      </attributes>');
      sb.writeln('      <direction placement="above">');
      sb.writeln('        <direction-type><metronome>'
          '<beat-unit>quarter</beat-unit><per-minute>${score.tempo}</per-minute>'
          '</metronome></direction-type>');
      sb.writeln('        <sound tempo="${score.tempo}"/>');
      sb.writeln('      </direction>');
    }

    for (final note in score.measures[index].notes) {
      _writeNote(sb, score, note);
    }

    sb.writeln('    </measure>');
  }

  void _writeNote(StringBuffer sb, JianpuScore score, JianpuNote note) {
    final segments = _decompose(note.quarterLength);
    if (segments.isEmpty) return;

    for (var s = 0; s < segments.length; s++) {
      final seg = segments[s];
      final durationDivs = (seg.quarterLength * divisions).round();
      final tieStart = !note.isRest && s < segments.length - 1;
      final tieStop = !note.isRest && s > 0;

      sb.writeln('      <note>');
      if (note.isRest) {
        sb.writeln('        <rest/>');
      } else {
        final p = spell(score.tonic, note);
        sb.writeln('        <pitch>');
        sb.writeln('          <step>${p.step}</step>');
        if (p.alter != 0) sb.writeln('          <alter>${p.alter}</alter>');
        sb.writeln('          <octave>${p.octave}</octave>');
        sb.writeln('        </pitch>');
        if (tieStart) sb.writeln('        <tie type="start"/>');
        if (tieStop) sb.writeln('        <tie type="stop"/>');
      }
      sb.writeln('        <duration>$durationDivs</duration>');
      sb.writeln('        <type>${seg.type}</type>');
      for (var d = 0; d < seg.dots; d++) {
        sb.writeln('        <dot/>');
      }
      if (!note.isRest && (tieStart || tieStop)) {
        sb.writeln('        <notations>');
        if (tieStop) sb.writeln('          <tied type="stop"/>');
        if (tieStart) sb.writeln('          <tied type="start"/>');
        sb.writeln('        </notations>');
      }
      sb.writeln('      </note>');
    }
  }

  /// Representable note values (quarterLength, MusicXML type, dot count),
  /// ordered from longest to shortest for greedy decomposition.
  static const List<_NoteValue> _values = [
    _NoteValue(4.0, 'whole', 0),
    _NoteValue(3.0, 'half', 1),
    _NoteValue(2.0, 'half', 0),
    _NoteValue(1.5, 'quarter', 1),
    _NoteValue(1.0, 'quarter', 0),
    _NoteValue(0.75, 'eighth', 1),
    _NoteValue(0.5, 'eighth', 0),
    _NoteValue(0.375, '16th', 1),
    _NoteValue(0.25, '16th', 0),
    _NoteValue(0.1875, '32nd', 1),
    _NoteValue(0.125, '32nd', 0),
  ];

  /// Decompose an arbitrary quarter-length into representable segments that are
  /// tied together (e.g. 2.5 -> half + eighth).
  List<_NoteValue> _decompose(double quarterLength) {
    const eps = 1e-4;
    var remaining = quarterLength;
    final out = <_NoteValue>[];
    var guard = 0;
    while (remaining > eps && guard < 64) {
      guard++;
      final match = _values.firstWhere(
        (v) => v.quarterLength <= remaining + eps,
        orElse: () => _values.last,
      );
      out.add(match);
      remaining -= match.quarterLength;
    }
    return out;
  }

  String _esc(String s) => s
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
}

class _NoteValue {
  final double quarterLength;
  final String type;
  final int dots;
  const _NoteValue(this.quarterLength, this.type, this.dots);
}
