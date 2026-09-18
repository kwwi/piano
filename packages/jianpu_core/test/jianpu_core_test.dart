import 'package:jianpu_core/jianpu_core.dart';
import 'package:test/test.dart';

void main() {
  const parser = JianpuParser();
  const builder = MusicXmlBuilder();

  group('JianpuParser', () {
    test('parses headers and body (Twinkle)', () {
      const src = '''
key: 1=C
time: 4/4
tempo: 120
title: Twinkle
---
1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
''';
      final score = parser.parse(src);
      expect(score.tonic, 'C');
      expect(score.beats, 4);
      expect(score.beatType, 4);
      expect(score.tempo, 120);
      expect(score.title, 'Twinkle');
      expect(score.measures.length, 4);
      expect(score.measures.first.notes.length, 4);
      expect(score.measures.first.notes.first.degree, 1);
    });

    test('beat extension "-" lengthens the previous note', () {
      final score = parser.parse('1 -');
      expect(score.measures.first.notes.length, 1);
      expect(score.measures.first.notes.first.quarterLength, 2.0);
    });

    test('orphan leading "-" is ignored (OCR noise)', () {
      final score = parser.parse('- 1 2 3 |');
      expect(score.measures.first.notes.map((n) => n.degree).toList(), [1, 2, 3]);
    });

    test('"-" after barline extends previous measure last note', () {
      final score = parser.parse('1 2 |\n- 3 |');
      expect(score.measures.length, 2);
      expect(score.measures.first.notes.last.quarterLength, 2.0);
      expect(score.measures[1].notes.first.degree, 3);
    });

    test('comment lines starting with # are skipped', () {
      final score = parser.parse('# draft\n1 2 3 |');
      expect(score.measures.first.notes.length, 3);
    });

    test('underlines halve duration; dot adds half', () {
      final score = parser.parse('1_ 1__ 1.');
      final notes = score.measures.first.notes;
      expect(notes[0].quarterLength, 0.5); // eighth
      expect(notes[1].quarterLength, 0.25); // sixteenth
      expect(notes[2].quarterLength, 1.5); // dotted quarter
    });

    test('parses octave marks and accidentals', () {
      final score = parser.parse("1' 1, #4 b7 0");
      final notes = score.measures.first.notes;
      expect(notes[0].octave, 1);
      expect(notes[1].octave, -1);
      expect(notes[2].accidental, Accidental.sharp);
      expect(notes[3].accidental, Accidental.flat);
      expect(notes[4].isRest, true);
    });

    test('skips invalid OCR tokens but keeps valid notes', () {
      final score = parser.parse('1 xyz 2 |');
      expect(score.measures.first.notes.map((n) => n.degree).toList(), [1, 2]);
    });

    test('throws when body has no valid notes', () {
      expect(
        () => parser.parse('9 8 xyz'),
        throwsA(isA<JianpuParseException>()),
      );
    });
  });

  group('pitch spelling', () {
    test('1=C: degree 1 -> C4, degree 3 -> E4', () {
      final c = spell('C', const JianpuNote(degree: 1, quarterLength: 1));
      expect(c.step, 'C');
      expect(c.octave, 4);
      expect(c.midi, 60);
      final e = spell('C', const JianpuNote(degree: 3, quarterLength: 1));
      expect(e.step, 'E');
      expect(e.midi, 64);
    });

    test('1=G: degree 4 -> C5 (natural)', () {
      final p = spell('G', const JianpuNote(degree: 4, quarterLength: 1));
      expect(p.step, 'C');
      expect(p.octave, 5);
      expect(p.alter, 0);
    });

    test('sharp raises: #4 in C -> F#4', () {
      final p = spell('C',
          const JianpuNote(degree: 4, accidental: Accidental.sharp, quarterLength: 1));
      expect(p.step, 'F');
      expect(p.alter, 1);
      expect(p.octave, 4);
    });

    test('octave marks shift by 12 semitones', () {
      final up = spell('C', const JianpuNote(degree: 1, octave: 1, quarterLength: 1));
      expect(up.midi, 72);
      final down = spell('C', const JianpuNote(degree: 1, octave: -1, quarterLength: 1));
      expect(down.midi, 48);
    });

    test('fifths for tonic', () {
      expect(fifthsForTonic('C'), 0);
      expect(fifthsForTonic('G'), 1);
      expect(fifthsForTonic('F'), -1);
      expect(fifthsForTonic('Bb'), -2);
    });
  });

  group('MusicXmlBuilder', () {
    test('produces a valid-looking partwise document', () {
      final score = parser.parse('key: 1=C\ntime: 4/4\n---\n1 2 3 4 | 5 - - -');
      final xml = builder.build(score);
      expect(xml, contains('<score-partwise'));
      expect(xml, contains('<fifths>0</fifths>'));
      expect(xml, contains('<beats>4</beats>'));
      expect(xml, contains('<step>C</step>'));
      expect(xml, contains('<type>whole</type>'));
    });

    test('ties multi-segment durations (2.5 beats -> half + eighth)', () {
      const score = JianpuScore(measures: [
        JianpuMeasure([JianpuNote(degree: 1, quarterLength: 2.5)]),
      ]);
      final xml = builder.build(score);
      expect(xml, contains('<tie type="start"/>'));
      expect(xml, contains('<tie type="stop"/>'));
      expect(xml, contains('<type>half</type>'));
      expect(xml, contains('<type>eighth</type>'));
    });

    test('rest renders as <rest/>', () {
      final score = parser.parse('0 1');
      final xml = builder.build(score);
      expect(xml, contains('<rest/>'));
    });
  });

  group('IR round-trips through JSON', () {
    test('score toJson/fromJson', () {
      final score = parser.parse('key: 1=D\ntime: 3/4\n---\n1 2 3 | 4 5 6');
      final restored = JianpuScore.fromJson(score.toJson());
      expect(restored.tonic, 'D');
      expect(restored.beats, 3);
      expect(restored.measures.length, 2);
      expect(restored.measures[1].notes[2].degree, 6);
    });
  });

  group('JianpuDslWriter', () {
    test('round-trips parse → write → parse for Twinkle', () {
      final original = parser.parse(JianpuSamples.twinkle);
      const writer = JianpuDslWriter();
      final dsl = writer.write(original);
      final again = parser.parse(dsl);
      expect(again.tonic, original.tonic);
      expect(again.beats, original.beats);
      expect(again.measures.length, original.measures.length);
      expect(
        again.measures.first.notes.map((n) => n.degree).toList(),
        original.measures.first.notes.map((n) => n.degree).toList(),
      );
    });
  });
  group('JianpuRhythmFitter', () {
    test('packs long missing-barline runs into 4/4 measures', () {
      // 12 quarters → 3 bars (8 would scale to eighths instead).
      final score = JianpuScore(
        measures: [
          JianpuMeasure([
            for (var i = 0; i < 12; i++)
              JianpuNote(degree: (i % 7) + 1, quarterLength: 1),
          ]),
        ],
      );
      final fitted = const JianpuRhythmFitter().fit(score);
      expect(fitted.measures.length, 3);
      expect(
        fitted.measures.every(
          (m) =>
              (m.notes.fold<double>(0, (a, n) => a + n.quarterLength) - 4).abs() <
              0.1,
        ),
        isTrue,
      );
    });

    test('scales eight quarters in one bar down to eighths', () {
      final eight = JianpuScore(
        measures: [
          JianpuMeasure([
            for (var i = 0; i < 8; i++)
              JianpuNote(degree: 1, quarterLength: 1),
          ]),
        ],
      );
      final fitted = const JianpuRhythmFitter().fit(eight);
      expect(fitted.measures.length, 1);
      expect(
        fitted.measures.first.notes.every(
          (n) => (n.quarterLength - 0.5).abs() < 1e-6,
        ),
        isTrue,
      );
    });

    test('scales six quarters in one bar to fill 4/4', () {
      final six = JianpuScore(
        measures: [
          JianpuMeasure([
            for (var i = 0; i < 6; i++)
              JianpuNote(degree: 1, quarterLength: 1),
          ]),
        ],
      );
      final fitted = const JianpuRhythmFitter().fit(six);
      final sum = fitted.measures.first.notes
          .fold<double>(0, (a, n) => a + n.quarterLength);
      expect((sum - 4.0).abs() < 0.15, isTrue);
    });

    test('extends last note when a beat is missing', () {
      final score = parser.parse('6 6 5 |');
      final fitted = const JianpuRhythmFitter().fit(score);
      expect(fitted.measures.first.notes.last.quarterLength, 2.0);
    });
  });

  group('WavBuilder', () {
    test('midiToHz A4 is 440', () {
      expect(midiToHz(69), closeTo(440, 0.01));
    });

    test('builds a valid RIFF/WAVE header for Twinkle', () {
      final score = parser.parse(JianpuSamples.twinkle);
      final wav = const WavBuilder().build(score);
      expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
      expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
      // At least one second of audio at 44.1kHz mono 16-bit.
      expect(wav.length, greaterThan(44100 * 2));
    });

    test('round-trips MidiBuilder bytes through parseMidiSmf + WavBuilder', () {
      final score = parser.parse(JianpuSamples.twinkle);
      final mid = const MidiBuilder().build(score);
      final parsed = parseMidiSmf(mid);
      expect(parsed.notes, isNotEmpty);
      expect(parsed.notes.first.midi, 60); // C4 for degree 1 in C
      final wav = const WavBuilder().buildFromMidi(mid);
      expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
      expect(wav.length, greaterThan(1000));
    });
  });
}
