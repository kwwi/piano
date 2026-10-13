import 'package:jianpu_core/jianpu_core.dart';
import 'package:test/test.dart';

void main() {
  group('frequency <-> midi', () {
    test('A4 = 440Hz -> MIDI 69', () {
      expect(frequencyToMidi(440), 69);
    });
    test('C4 ~ 261.63Hz -> MIDI 60', () {
      expect(frequencyToMidi(261.63), 60);
    });
  });

  group('midiToJianpuNote', () {
    test('C major: 60 -> degree 1, 62 -> degree 2', () {
      final n1 = midiToJianpuNote(60, 'C', 1);
      expect(n1.degree, 1);
      expect(n1.octave, 0);
      expect(n1.accidental, Accidental.none);

      final n2 = midiToJianpuNote(62, 'C', 1);
      expect(n2.degree, 2);
    });

    test('C major: 72 -> degree 1 up one octave', () {
      final n = midiToJianpuNote(72, 'C', 1);
      expect(n.degree, 1);
      expect(n.octave, 1);
    });

    test('C major: 61 (C#) -> sharp of degree 1', () {
      final n = midiToJianpuNote(61, 'C', 1);
      expect(n.degree, 1);
      expect(n.accidental, Accidental.sharp);
    });
  });

  group('MelodyTranscriber', () {
    test('constant pitch produces one held note', () {
      final frames = List.generate(20, (_) => const PitchFrame(440));
      const t = MelodyTranscriber(tonic: 'A', tempo: 90);
      final score = t.transcribe(frames, 2048 / 44100);
      final notes = score.measures.expand((m) => m.notes).toList();
      expect(notes.length, 1);
      expect(notes.first.degree, 1); // A is degree 1 when tonic = A
      expect(notes.first.quarterLength, greaterThan(0));
    });

    test('silence then pitch yields a rest then a note', () {
      final frames = <PitchFrame>[
        ...List.generate(10, (_) => const PitchFrame(null)),
        ...List.generate(10, (_) => const PitchFrame(440)),
      ];
      const t = MelodyTranscriber(tonic: 'A', tempo: 90);
      final score = t.transcribe(frames, 2048 / 44100);
      final notes = score.measures.expand((m) => m.notes).toList();
      expect(notes.first.isRest, true);
      expect(notes.any((n) => !n.isRest && n.degree == 1), true);
    });

    test('two distinct pitches segment into two notes', () {
      final frames = <PitchFrame>[
        ...List.generate(8, (_) => const PitchFrame(440)), // A4
        ...List.generate(8, (_) => const PitchFrame(523.25)), // C5
      ];
      const t = MelodyTranscriber(tonic: 'C', tempo: 90);
      final score = t.transcribe(frames, 2048 / 44100);
      final notes =
          score.measures.expand((m) => m.notes).where((n) => !n.isRest).toList();
      expect(notes.length, 2);
    });
  });

  group('MidiBuilder', () {
    test('produces a valid SMF header', () {
      const parser = JianpuParser();
      final score = parser.parse('key: 1=C\n---\n1 2 3 | 4 5 6');
      final bytes = const MidiBuilder().build(score);
      expect(bytes.sublist(0, 4), [0x4D, 0x54, 0x68, 0x64]); // 'MThd'
      final asList = bytes.toList();
      var found = false;
      for (var i = 0; i < asList.length - 3; i++) {
        if (asList[i] == 0x4D &&
            asList[i + 1] == 0x54 &&
            asList[i + 2] == 0x72 &&
            asList[i + 3] == 0x6B) {
          found = true;
          break;
        }
      }
      expect(found, true); // 'MTrk'
    });
  });
}
