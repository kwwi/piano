import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:pitch_detector_dart/pitch_detector.dart';
import 'package:record/record.dart';

import '../../core/jianpu/jianpu.dart';
import '../../widgets/score_view.dart';

class ListenScreen extends ConsumerStatefulWidget {
  const ListenScreen({super.key});

  @override
  ConsumerState<ListenScreen> createState() => _ListenScreenState();
}

class _ListenScreenState extends ConsumerState<ListenScreen> {
  static const int _sampleRate = 44100;
  static const int _bufferSize = 2048;

  final _recorder = AudioRecorder();
  final _detector = PitchDetector(
    audioSampleRate: _sampleRate.toDouble(),
    bufferSize: _bufferSize,
  );
  final _builder = const MusicXmlBuilder();

  StreamSubscription<Uint8List>? _sub;
  final _byteBuffer = BytesBuilder();
  final List<PitchFrame> _frames = [];

  bool _recording = false;
  double? _currentHz;
  String _tonic = 'C';
  double _tempo = 90;
  String? _musicXml;

  static const List<String> _tonics = ['C', 'G', 'D', 'A', 'E', 'F', 'Bb', 'Eb'];

  double get _frameSeconds => _bufferSize / _sampleRate;

  @override
  void dispose() {
    _sub?.cancel();
    _recorder.dispose();
    super.dispose();
  }

  Future<void> _toggle() async {
    if (_recording) {
      await _stop();
    } else {
      await _start();
    }
  }

  Future<void> _start() async {
    if (!await _recorder.hasPermission()) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('需要麦克风权限')));
      }
      return;
    }
    _frames.clear();
    _byteBuffer.clear();
    setState(() {
      _recording = true;
      _musicXml = null;
    });

    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _sampleRate,
        numChannels: 1,
      ),
    );
    _sub = stream.listen(_onAudio);
  }

  void _onAudio(Uint8List data) {
    _byteBuffer.add(data);
    const chunkBytes = _bufferSize * 2; // 16-bit samples
    while (_byteBuffer.length >= chunkBytes) {
      final all = _byteBuffer.toBytes();
      final chunk = all.sublist(0, chunkBytes);
      final rest = all.sublist(chunkBytes);
      _byteBuffer.clear();
      _byteBuffer.add(rest);
      _process(chunk);
    }
  }

  Future<void> _process(Uint8List chunk) async {
    final result = await _detector.getPitchFromIntBuffer(chunk);
    final hz = result.pitched ? result.pitch : null;
    _frames.add(PitchFrame(hz));
    if (mounted && hz != _currentHz) {
      setState(() => _currentHz = hz);
    }
  }

  Future<void> _stop() async {
    await _recorder.stop();
    await _sub?.cancel();
    _sub = null;
    setState(() => _recording = false);
    _transcribe();
  }

  void _transcribe() {
    final transcriber = MelodyTranscriber(
      tonic: _tonic,
      tempo: _tempo.round(),
    );
    final score = transcriber.transcribe(_frames, _frameSeconds);
    setState(() => _musicXml = _builder.build(score));
  }

  String get _currentNoteLabel {
    final hz = _currentHz;
    if (hz == null) return '—';
    final note = midiToJianpuNote(frequencyToMidi(hz), _tonic, 1);
    final oct = note.octave > 0
        ? "'" * note.octave
        : (note.octave < 0 ? ',' * -note.octave : '');
    return '${hz.toStringAsFixed(1)} Hz · ${note.degree}$oct';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('听音转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                const Text('调号 1='),
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: _tonic,
                  items: _tonics
                      .map((t) => DropdownMenuItem(value: t, child: Text(t)))
                      .toList(),
                  onChanged: _recording
                      ? null
                      : (v) => setState(() => _tonic = v ?? 'C'),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Row(
                    children: [
                      const Text('速度'),
                      Expanded(
                        child: Slider(
                          value: _tempo,
                          min: 40,
                          max: 200,
                          divisions: 160,
                          label: '${_tempo.round()}',
                          onChanged: _recording
                              ? null
                              : (v) => setState(() => _tempo = v),
                        ),
                      ),
                      Text('${_tempo.round()}'),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8),
            alignment: Alignment.center,
            child: Text(
              _recording ? '识别中: $_currentNoteLabel' : '按下按钮开始录音',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          Expanded(
            child: _musicXml == null
                ? Center(
                    child: Text(
                      _recording ? '正在采集音高…' : '录音结束后在此显示五线谱',
                    ),
                  )
                : ScoreView(musicXml: _musicXml!),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _toggle,
        backgroundColor: _recording ? Colors.red : null,
        icon: Icon(_recording ? Icons.stop : Icons.mic),
        label: Text(_recording ? '停止' : '录音'),
      ),
    );
  }
}
