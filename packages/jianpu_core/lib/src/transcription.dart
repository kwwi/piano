import 'dart:math' as math;

import 'jianpu_model.dart';
import 'pitch.dart';

/// Converts a frequency in Hz to an exact (fractional) MIDI note number.
double frequencyToMidiExact(double hz) => 69 + 12 * (math.log(hz / 440) / math.ln2);

/// Converts a frequency in Hz to the nearest integer MIDI note number.
int frequencyToMidi(double hz) => frequencyToMidiExact(hz).round();

const List<int> _majorOffsets = [0, 2, 4, 5, 7, 9, 11];

/// Anchor: tonic "1" (no octave marks) sits at octave 4, matching [spell].
int _tonicMidi(String tonic) {
  // Reuse the spell() mapping for degree 1 to stay consistent.
  final p = spell(tonic, const JianpuNote(degree: 1, quarterLength: 1));
  return p.midi;
}

/// Map an absolute [midi] pitch back to a movable-do jianpu note in [tonic],
/// choosing accidentals for out-of-scale (chromatic) pitches.
JianpuNote midiToJianpuNote(int midi, String tonic, double quarterLength) {
  final tonicMidi = _tonicMidi(tonic);
  final diff = midi - tonicMidi;
  final rel = ((diff % 12) + 12) % 12;
  final octave = ((diff - rel) / 12).round();

  final scaleIndex = _majorOffsets.indexOf(rel);
  if (scaleIndex >= 0) {
    return JianpuNote(
      degree: scaleIndex + 1,
      octave: octave,
      quarterLength: quarterLength,
    );
  }
  // Chromatic: prefer sharp of the degree just below, else flat of the one above.
  final below = _majorOffsets.indexOf(rel - 1);
  if (below >= 0) {
    return JianpuNote(
      degree: below + 1,
      octave: octave,
      accidental: Accidental.sharp,
      quarterLength: quarterLength,
    );
  }
  final above = _majorOffsets.indexOf(rel + 1);
  return JianpuNote(
    degree: (above >= 0 ? above : 0) + 1,
    octave: octave,
    accidental: Accidental.flat,
    quarterLength: quarterLength,
  );
}

/// One analysis frame: detected pitch in Hz, or null when unvoiced/silent.
class PitchFrame {
  final double? hz;
  const PitchFrame(this.hz);
}

/// Turns a stream of monophonic [PitchFrame]s into a quantized [JianpuScore].
///
/// Pipeline: MIDI rounding → run-length segmentation (pitch/voicing changes are
/// onsets) → seconds→beats using [tempo] → quantize to a grid → pack into
/// measures of [beats]/[beatType].
class MelodyTranscriber {
  final String tonic;
  final int tempo;
  final int beats;
  final int beatType;

  /// Quantization grid in quarter notes (0.25 == sixteenth).
  final double grid;

  /// Minimum voiced frames to accept a note (rejects blips).
  final int minRunFrames;

  const MelodyTranscriber({
    this.tonic = 'C',
    this.tempo = 90,
    this.beats = 4,
    this.beatType = 4,
    this.grid = 0.25,
    this.minRunFrames = 2,
  });

  double _quantize(double ql) {
    final q = (ql / grid).round() * grid;
    return q < grid ? grid : q;
  }

  JianpuScore transcribe(List<PitchFrame> frames, double frameSeconds) {
    // 1. Reduce frames to runs of (midi|null, frameCount).
    final runs = <({int? midi, int count})>[];
    int? currentMidi;
    var haveCurrent = false;
    var count = 0;

    void flush() {
      if (haveCurrent) runs.add((midi: currentMidi, count: count));
    }

    for (final f in frames) {
      final midi = (f.hz != null && f.hz! > 0) ? frequencyToMidi(f.hz!) : null;
      if (!haveCurrent) {
        currentMidi = midi;
        count = 1;
        haveCurrent = true;
      } else if (midi == currentMidi) {
        count++;
      } else {
        flush();
        currentMidi = midi;
        count = 1;
      }
    }
    flush();

    // 2. Runs -> quantized notes/rests.
    final notes = <JianpuNote>[];
    final beatsPerSecond = tempo / 60.0;
    for (final run in runs) {
      final seconds = run.count * frameSeconds;
      final ql = _quantize(seconds * beatsPerSecond);
      if (run.midi == null) {
        notes.add(JianpuNote(degree: 0, quarterLength: ql));
      } else {
        if (run.count < minRunFrames) continue; // drop blips
        notes.add(midiToJianpuNote(run.midi!, tonic, ql));
      }
    }

    // 3. Pack notes into measures.
    final measureQuarters = beats * (4.0 / beatType);
    final measures = <JianpuMeasure>[];
    var bucket = <JianpuNote>[];
    var acc = 0.0;
    for (final n in notes) {
      bucket.add(n);
      acc += n.quarterLength;
      if (acc >= measureQuarters - 1e-6) {
        measures.add(JianpuMeasure(bucket));
        bucket = <JianpuNote>[];
        acc = 0.0;
      }
    }
    if (bucket.isNotEmpty) measures.add(JianpuMeasure(bucket));
    if (measures.isEmpty) measures.add(const JianpuMeasure([]));

    return JianpuScore(
      tonic: tonic,
      beats: beats,
      beatType: beatType,
      tempo: tempo,
      measures: measures,
    );
  }
}
