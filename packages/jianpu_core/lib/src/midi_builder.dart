import 'dart:typed_data';

import 'jianpu_model.dart';
import 'pitch.dart';

/// Builds a Standard MIDI File (format 0) from a [JianpuScore].
///
/// Pure Dart with no dependencies so it can be unit-tested and reused. The
/// melody is written as a single monophonic track using the resolved MIDI
/// pitches from [spell].
class MidiBuilder {
  /// Ticks per quarter note.
  static const int division = 480;

  /// MIDI velocity for note-on events.
  final int velocity;

  const MidiBuilder({this.velocity = 90});

  Uint8List build(JianpuScore score) {
    final track = <int>[];

    // Tempo meta event (microseconds per quarter note).
    final usPerQuarter = (60000000 / score.tempo).round();
    _writeVarLen(track, 0);
    track.addAll([0xFF, 0x51, 0x03]);
    track.addAll([
      (usPerQuarter >> 16) & 0xFF,
      (usPerQuarter >> 8) & 0xFF,
      usPerQuarter & 0xFF,
    ]);

    // Time signature meta event.
    _writeVarLen(track, 0);
    final denomPow = _log2(score.beatType);
    track.addAll([0xFF, 0x58, 0x04, score.beats & 0xFF, denomPow, 24, 8]);

    var pendingDelta = 0;
    for (final measure in score.measures) {
      for (final note in measure.notes) {
        final ticks = (note.quarterLength * division).round();
        if (note.isRest) {
          pendingDelta += ticks;
          continue;
        }
        final key = spell(score.tonic, note).midi.clamp(0, 127);
        _writeVarLen(track, pendingDelta);
        track.addAll([0x90, key, velocity]); // note on
        pendingDelta = 0;
        _writeVarLen(track, ticks);
        track.addAll([0x80, key, 0]); // note off
      }
    }

    // End of track.
    _writeVarLen(track, 0);
    track.addAll([0xFF, 0x2F, 0x00]);

    final out = BytesBuilder();
    // MThd header.
    out.add(_ascii('MThd'));
    out.add(_uint32(6));
    out.add(_uint16(0)); // format 0
    out.add(_uint16(1)); // one track
    out.add(_uint16(division));
    // MTrk chunk.
    out.add(_ascii('MTrk'));
    out.add(_uint32(track.length));
    out.add(Uint8List.fromList(track));
    return out.toBytes();
  }

  int _log2(int v) {
    var n = 0;
    var x = v;
    while (x > 1) {
      x >>= 1;
      n++;
    }
    return n;
  }

  void _writeVarLen(List<int> out, int value) {
    var buffer = value & 0x7F;
    var v = value >> 7;
    final stack = <int>[];
    while (v > 0) {
      stack.add((v & 0x7F) | 0x80);
      v >>= 7;
    }
    for (final b in stack.reversed) {
      out.add(b);
    }
    out.add(buffer);
  }

  List<int> _ascii(String s) => s.codeUnits;
  List<int> _uint16(int v) => [(v >> 8) & 0xFF, v & 0xFF];
  List<int> _uint32(int v) =>
      [(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF];
}
