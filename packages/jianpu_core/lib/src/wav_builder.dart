import 'dart:math' as math;
import 'dart:typed_data';

import 'jianpu_model.dart';
import 'midi_parser.dart';
import 'pitch.dart';

/// MIDI note number → frequency in Hz (A4 = 440).
double midiToHz(int midi) => 440.0 * math.pow(2.0, (midi - 69) / 12.0);

/// Renders melody notes to a 16-bit PCM WAV (RIFF).
///
/// Used for in-app MIDI preview without a SoundFont: a soft sine + light
/// harmonic mix with a short attack and exponential decay. Pure Dart so it
/// runs on web, mobile, and desktop and is unit-testable.
class WavBuilder {
  /// Output sample rate.
  final int sampleRate;

  /// Peak amplitude in `0..1` (before 16-bit quantisation).
  final double gain;

  /// Hard cap so a pathological score cannot allocate unbounded RAM.
  final Duration maxDuration;

  const WavBuilder({
    this.sampleRate = 44100,
    this.gain = 0.32,
    this.maxDuration = const Duration(minutes: 5),
  });

  /// Build a complete WAV file for a [JianpuScore].
  Uint8List build(JianpuScore score) {
    final secondsPerQuarter = 60.0 / math.max(1, score.tempo);
    final events = <_Tone>[];
    var t = 0.0;
    for (final measure in score.measures) {
      for (final note in measure.notes) {
        final dur = note.quarterLength * secondsPerQuarter;
        if (!note.isRest && dur > 0) {
          final midi = spell(score.tonic, note).midi.clamp(0, 127);
          events.add(_Tone(start: t, duration: dur, hz: midiToHz(midi)));
        }
        t += dur;
      }
    }
    return _render(events);
  }

  /// Build a WAV from Standard MIDI File bytes (upload / listen pipelines).
  Uint8List buildFromMidi(Uint8List midiBytes) {
    final parsed = parseMidiSmf(midiBytes);
    final events = [
      for (final n in parsed.notes)
        _Tone(
          start: n.startSec,
          duration: n.durationSec,
          hz: midiToHz(n.midi.clamp(0, 127)),
        ),
    ];
    return _render(events);
  }

  Uint8List _render(List<_Tone> events) {
    var end = 0.15;
    for (final e in events) {
      end = math.max(end, e.start + e.duration + 0.05);
    }
    final totalSeconds =
        math.min(end, maxDuration.inMilliseconds / 1000.0);
    final nSamples = math.max(1, (totalSeconds * sampleRate).ceil());
    final pcm = Float64List(nSamples);
    for (final e in events) {
      _renderTone(pcm, e);
    }
    return _encodeWav(pcm);
  }

  void _renderTone(Float64List pcm, _Tone tone) {
    final start = (tone.start * sampleRate).round();
    final len = math.max(1, (tone.duration * sampleRate).round());
    final attack = math.min(len, (0.012 * sampleRate).round());
    final release = math.min(len, (0.06 * sampleRate).round());
    final twoPiF = 2 * math.pi * tone.hz / sampleRate;

    for (var i = 0; i < len; i++) {
      final idx = start + i;
      if (idx < 0 || idx >= pcm.length) break;

      final phase = twoPiF * i;
      final sample = math.sin(phase) +
          0.35 * math.sin(2 * phase) +
          0.12 * math.sin(3 * phase);

      var env = 1.0;
      if (i < attack) {
        env = i / attack;
      }
      final fromEnd = len - 1 - i;
      if (fromEnd < release) {
        env *= fromEnd / release;
      }
      env *= math.exp(-3.0 * i / len);

      pcm[idx] += sample * env * gain;
    }
  }

  Uint8List _encodeWav(Float64List pcm) {
    final dataSize = pcm.length * 2;
    final out = BytesBuilder(copy: false);
    void u16(int v) => out.add([v & 0xFF, (v >> 8) & 0xFF]);
    void u32(int v) => out.add([
          v & 0xFF,
          (v >> 8) & 0xFF,
          (v >> 16) & 0xFF,
          (v >> 24) & 0xFF,
        ]);

    out.add('RIFF'.codeUnits);
    u32(36 + dataSize);
    out.add('WAVE'.codeUnits);
    out.add('fmt '.codeUnits);
    u32(16);
    u16(1);
    u16(1);
    u32(sampleRate);
    u32(sampleRate * 2);
    u16(2);
    u16(16);
    out.add('data'.codeUnits);
    u32(dataSize);

    final bytes = ByteData(dataSize);
    for (var i = 0; i < pcm.length; i++) {
      final clipped = pcm[i].clamp(-1.0, 1.0);
      final s = (clipped * 32767.0).round();
      bytes.setInt16(i * 2, s, Endian.little);
    }
    out.add(bytes.buffer.asUint8List());
    return out.toBytes();
  }
}

class _Tone {
  final double start;
  final double duration;
  final double hz;
  const _Tone({required this.start, required this.duration, required this.hz});
}
