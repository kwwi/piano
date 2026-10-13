import 'dart:async';
import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';

import '../jianpu/jianpu.dart';
import 'score_preview_player.dart';

/// Shared play-state helper for listen / upload / jianpu result toolbars.
class ScoreResultController {
  ScoreResultController({ScorePreviewPlayer? player})
      : _player = player ?? ScorePreviewPlayer();

  final ScorePreviewPlayer _player;
  StreamSubscription<PlayerState>? _sub;
  bool playing = false;
  void Function(bool playing)? onPlayingChanged;

  ScorePreviewPlayer get player => _player;

  void attach() {
    _sub = _player.playerStateStream.listen((state) {
      final isPlaying = state.playing &&
          state.processingState != ProcessingState.completed &&
          state.processingState != ProcessingState.idle;
      if (isPlaying != playing) {
        playing = isPlaying;
        onPlayingChanged?.call(playing);
      }
      if (state.processingState == ProcessingState.completed) {
        playing = false;
        onPlayingChanged?.call(false);
      }
    });
  }

  Future<void> dispose() async {
    await _sub?.cancel();
    await _player.dispose();
  }

  Future<void> stop() async {
    await _player.stop();
    playing = false;
    onPlayingChanged?.call(false);
  }

  /// Prefer [score] (jianpu/listen); otherwise synthesise from [midiBytes]
  /// (upload pipeline MIDI).
  Future<void> togglePreview({
    JianpuScore? score,
    Uint8List? midiBytes,
  }) async {
    if (playing) {
      await stop();
      return;
    }
    if (score != null) {
      playing = true;
      onPlayingChanged?.call(true);
      await _player.play(score);
      return;
    }
    if (midiBytes != null && midiBytes.isNotEmpty) {
      playing = true;
      onPlayingChanged?.call(true);
      await _player.playMidi(midiBytes);
      return;
    }
    throw StateError('无可试听的谱面数据');
  }
}
