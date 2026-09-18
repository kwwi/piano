import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';

import '../jianpu/jianpu.dart';

/// In-app audition of a score or MIDI file (same pitches/rhythm as export).
///
/// Renders a short WAV with [WavBuilder] and plays it through [AudioPlayer],
/// so preview works on web and mobile without a SoundFont.
class ScorePreviewPlayer {
  ScorePreviewPlayer({WavBuilder? wavBuilder})
      : _wav = wavBuilder ?? const WavBuilder();

  final WavBuilder _wav;
  final AudioPlayer _player = AudioPlayer();

  bool get playing => _player.playing;

  Stream<PlayerState> get playerStateStream => _player.playerStateStream;

  /// Stop any current playback and start auditioning [score].
  Future<void> play(JianpuScore score) async {
    await _playWav(_wav.build(score));
  }

  /// Audition a Standard MIDI File (e.g. backend transcription.mid).
  Future<void> playMidi(Uint8List midiBytes) async {
    await _playWav(_wav.buildFromMidi(midiBytes));
  }

  Future<void> _playWav(Uint8List bytes) async {
    await _player.stop();
    await _player.setAudioSource(_WavBytesSource(bytes));
    await _player.play();
  }

  Future<void> stop() => _player.stop();

  Future<void> dispose() async {
    await _player.dispose();
  }
}

/// Feeds an in-memory WAV to just_audio (works on web + IO).
// ignore: experimental_member_use
class _WavBytesSource extends StreamAudioSource {
  _WavBytesSource(this.bytes);

  final Uint8List bytes;

  @override
  // ignore: experimental_member_use
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    start ??= 0;
    end ??= bytes.length;
    // ignore: experimental_member_use
    return StreamAudioResponse(
      sourceLength: bytes.length,
      contentLength: end - start,
      offset: start,
      stream: Stream.value(bytes.sublist(start, end)),
      contentType: 'audio/wav',
    );
  }
}
