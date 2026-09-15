import 'jianpu_model.dart';

/// Thrown when the jianpu DSL cannot be parsed.
class JianpuParseException implements Exception {
  final String message;
  final int? line;
  JianpuParseException(this.message, {this.line});
  @override
  String toString() =>
      'JianpuParseException${line != null ? ' (line $line)' : ''}: $message';
}

/// Parser for a small, ASCII-friendly jianpu DSL.
///
/// Header (one directive per line, before an optional `---` separator):
///   key: 1=C          // tonic; also accepts `key: G`
///   time: 4/4
///   tempo: 90
///   title: Twinkle
///   composer: Trad.
///
/// Body: whitespace-separated tokens, `|` as barline.
///   Note token grammar:  [# | b | n] DIGIT [octave marks] [duration marks]
///     DIGIT           1..7 (pitch) or 0 (rest)
///     octave up       '   (one or more, each +1 octave)
///     octave down     ,   (one or more, each -1 octave)
///     underline       _   (each halves the duration: 1_ = eighth, 1__ = 16th)
///     dot             .   (dotted: multiplies duration by 1.5)
///   beat extension    -   standalone token; adds one beat to the previous note
///
/// Example body:  1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
class JianpuParser {
  const JianpuParser();

  JianpuScore parse(String source) {
    final rawLines = source.split('\n');

    String tonic = 'C';
    int beats = 4;
    int beatType = 4;
    int tempo = 90;
    String? title;
    String? composer;

    final bodyLines = <({String text, int number})>[];
    var inBody = false;

    for (var i = 0; i < rawLines.length; i++) {
      final line = rawLines[i].trim();
      final lineNo = i + 1;
      if (line.isEmpty) continue;
      if (line == '---') {
        inBody = true;
        continue;
      }

      final colon = line.indexOf(':');
      final isDirective = !inBody &&
          colon > 0 &&
          RegExp(r'^[a-zA-Z]+$').hasMatch(line.substring(0, colon).trim());

      if (isDirective) {
        final key = line.substring(0, colon).trim().toLowerCase();
        final value = line.substring(colon + 1).trim();
        switch (key) {
          case 'key':
            tonic = _parseKey(value);
          case 'time':
            final ts = _parseTime(value, lineNo);
            beats = ts.$1;
            beatType = ts.$2;
          case 'tempo':
            tempo = int.tryParse(value) ?? tempo;
          case 'title':
            title = value.isEmpty ? null : value;
          case 'composer':
            composer = value.isEmpty ? null : value;
          default:
            throw JianpuParseException('Unknown directive "$key"', line: lineNo);
        }
      } else {
        inBody = true;
        bodyLines.add((text: line, number: lineNo));
      }
    }

    final measures = _parseBody(bodyLines);
    return JianpuScore(
      tonic: tonic,
      beats: beats,
      beatType: beatType,
      tempo: tempo,
      title: title,
      composer: composer,
      measures: measures,
    );
  }

  String _parseKey(String value) {
    // Accept "1=C" or plain "C".
    final eq = value.indexOf('=');
    final t = (eq >= 0 ? value.substring(eq + 1) : value).trim();
    return t.isEmpty ? 'C' : t;
  }

  (int, int) _parseTime(String value, int lineNo) {
    final parts = value.split('/');
    if (parts.length != 2) {
      throw JianpuParseException('Invalid time signature "$value"',
          line: lineNo);
    }
    final n = int.tryParse(parts[0].trim());
    final d = int.tryParse(parts[1].trim());
    if (n == null || d == null || n <= 0 || d <= 0) {
      throw JianpuParseException('Invalid time signature "$value"',
          line: lineNo);
    }
    return (n, d);
  }

  List<JianpuMeasure> _parseBody(List<({String text, int number})> bodyLines) {
    final measures = <JianpuMeasure>[];
    var current = <JianpuNote>[];

    void closeMeasure() {
      if (current.isNotEmpty) {
        measures.add(JianpuMeasure(current));
        current = <JianpuNote>[];
      }
    }

    void extendLastNote() {
      if (current.isNotEmpty) {
        final last = current.removeLast();
        current.add(last.copyWith(quarterLength: last.quarterLength + 1.0));
        return;
      }
      // "-" at the start of a line after a barline: attach to the previous
      // measure's last note (common in multi-line DSL / OCR output).
      if (measures.isNotEmpty && measures.last.notes.isNotEmpty) {
        final prev = measures.removeLast();
        final notes = List<JianpuNote>.of(prev.notes);
        final last = notes.removeLast();
        notes.add(last.copyWith(quarterLength: last.quarterLength + 1.0));
        measures.add(JianpuMeasure(notes));
        return;
      }
      // Orphan extender (OCR noise) — ignore rather than hard-fail the score.
    }

    for (final entry in bodyLines) {
      final text = entry.text.trim();
      // Allow comment lines from OMR drafts / user annotations.
      if (text.startsWith('#')) continue;

      final tokens = text
          .replaceAll('|', ' | ')
          .split(RegExp(r'\s+'))
          .where((t) => t.isNotEmpty);

      for (final token in tokens) {
        if (token == '|') {
          closeMeasure();
          continue;
        }
        if (token == '-') {
          extendLastNote();
          continue;
        }
        try {
          current.add(_parseNoteToken(token, entry.number));
        } on JianpuParseException {
          // Skip unrecognised OCR debris tokens instead of aborting the whole
          // score (e.g. stray punctuation that survived sanitisation).
          continue;
        }
      }
    }
    closeMeasure();

    if (measures.isEmpty) {
      throw JianpuParseException('No notes found in body');
    }
    return measures;
  }

  JianpuNote _parseNoteToken(String token, int lineNo) {
    var i = 0;
    Accidental accidental = Accidental.none;

    // Leading accidental.
    switch (token[i]) {
      case '#':
        accidental = Accidental.sharp;
        i++;
      case 'b':
        accidental = Accidental.flat;
        i++;
      case 'n':
        accidental = Accidental.natural;
        i++;
    }

    if (i >= token.length || !RegExp(r'[0-7]').hasMatch(token[i])) {
      throw JianpuParseException('Invalid note token "$token"', line: lineNo);
    }
    final degree = int.parse(token[i]);
    i++;

    int octave = 0;
    double quarterLength = 1.0;
    var dots = 0;
    var underlines = 0;

    for (; i < token.length; i++) {
      switch (token[i]) {
        case "'":
          octave += 1;
        case ',':
          octave -= 1;
        case '_':
          underlines += 1;
        case '.':
          dots += 1;
        default:
          throw JianpuParseException(
              'Invalid modifier "${token[i]}" in token "$token"',
              line: lineNo);
      }
    }

    for (var u = 0; u < underlines; u++) {
      quarterLength /= 2.0;
    }
    // Apply dots: each dot adds half of the running value (standard for 1 dot;
    // reasonable approximation for multiple dots).
    var dotted = quarterLength;
    var add = quarterLength;
    for (var d = 0; d < dots; d++) {
      add /= 2.0;
      dotted += add;
    }
    quarterLength = dotted;

    return JianpuNote(
      degree: degree,
      octave: octave,
      accidental: accidental,
      quarterLength: quarterLength,
    );
  }
}
