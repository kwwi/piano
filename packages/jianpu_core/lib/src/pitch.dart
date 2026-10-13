import 'jianpu_model.dart';

/// A concrete, engravable pitch: letter step + chromatic alteration + octave.
class SpelledPitch {
  final String step; // 'C'..'B'
  final int alter; // -2..+2 (flats negative, sharps positive)
  final int octave; // scientific octave (C4 = middle C)
  final int midi;

  const SpelledPitch(this.step, this.alter, this.octave, this.midi);
}

const List<String> _letters = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];

/// Natural semitone (pitch class) of each letter.
const Map<String, int> _naturalPc = {
  'C': 0,
  'D': 2,
  'E': 4,
  'F': 5,
  'G': 7,
  'A': 9,
  'B': 11,
};

/// Major-scale semitone offsets for degrees 1..7.
const List<int> _majorOffsets = [0, 2, 4, 5, 7, 9, 11];

/// Circle-of-fifths value (number of sharps positive / flats negative) for a
/// major key, used to write the MusicXML key signature.
const Map<String, int> _fifths = {
  'C': 0,
  'G': 1,
  'D': 2,
  'A': 3,
  'E': 4,
  'B': 5,
  'F#': 6,
  'C#': 7,
  'F': -1,
  'Bb': -2,
  'Eb': -3,
  'Ab': -4,
  'Db': -5,
  'Gb': -6,
  'Cb': -7,
};

/// Number of sharps (+) or flats (-) for the given tonic; defaults to 0.
int fifthsForTonic(String tonic) => _fifths[tonic] ?? 0;

/// Parse a tonic spelling like `C`, `F#`, `Bb` into (letter, alterOffset).
({String letter, int alter}) _parseTonic(String tonic) {
  final letter = tonic.substring(0, 1).toUpperCase();
  var alter = 0;
  for (final c in tonic.substring(1).split('')) {
    if (c == '#') alter += 1;
    if (c == 'b' || c == 'B') alter -= 1;
  }
  return (letter: _letters.contains(letter) ? letter : 'C', alter: alter);
}

/// Compute the MIDI note for the tonic ("degree 1", no octave marks).
/// Anchored so that `1=C` maps to C4 (MIDI 60).
int _tonicMidi(String tonic) {
  final parsed = _parseTonic(tonic);
  final pc = (_naturalPc[parsed.letter]! + parsed.alter) % 12;
  return (4 + 1) * 12 + pc; // octave 4
}

/// Resolve a jianpu [note] in the context of [tonic] into a [SpelledPitch].
///
/// Uses an absolute-MIDI approach for correctness, then chooses the diatonic
/// letter for the degree so the accidental (alter) spelling stays natural.
SpelledPitch spell(String tonic, JianpuNote note) {
  assert(!note.isRest);
  final tonicParsed = _parseTonic(tonic);
  final tonicMidi = _tonicMidi(tonic);

  final accidentalDelta = switch (note.accidental) {
    Accidental.sharp => 1,
    Accidental.flat => -1,
    Accidental.none => 0,
    Accidental.natural => 0, // handled below by forcing natural spelling
  };

  final degreeMidi = tonicMidi +
      _majorOffsets[note.degree - 1] +
      12 * note.octave +
      accidentalDelta;

  // Diatonic letter for this degree, relative to the tonic letter.
  final tonicLetterIndex = _letters.indexOf(tonicParsed.letter);
  final letter = _letters[(tonicLetterIndex + (note.degree - 1)) % 7];
  final naturalPc = _naturalPc[letter]!;

  // Choose an octave for `letter` whose natural pitch is closest to degreeMidi.
  final octave = ((degreeMidi - naturalPc) / 12).round() - 1;
  var alter = degreeMidi - ((octave + 1) * 12 + naturalPc);

  // A natural accidental forces alter to 0 (cancels the key signature).
  if (note.accidental == Accidental.natural) {
    alter = 0;
  }

  // Keep alteration within a sane range in case of enharmonic edge cases.
  if (alter > 2) alter = 2;
  if (alter < -2) alter = -2;

  return SpelledPitch(letter, alter, octave, degreeMidi);
}
