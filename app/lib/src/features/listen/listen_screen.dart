import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:pitch_detector_dart/pitch_detector.dart';
import 'package:record/record.dart';

import '../../core/jianpu/jianpu.dart';
import '../../core/notation/score_export.dart';
import '../../core/notation/score_result_controller.dart';
import '../../core/notation/verovio_renderer.dart';
import '../../widgets/jianpu_view.dart';
import '../../widgets/score_result_actions.dart';
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
  final _result = ScoreResultController();

  StreamSubscription<Uint8List>? _sub;
  final _byteBuffer = BytesBuilder();
  final List<PitchFrame> _frames = [];

  bool _recording = false;
  bool _previewPlaying = false;
  double? _currentHz;
  String _tonic = 'C';
  double _tempo = 90;
  JianpuScore? _score;
  String? _musicXml;
  int _previewMode = 0;

  static const List<String> _tonics = ['C', 'G', 'D', 'A', 'E', 'F', 'Bb', 'Eb'];

  double get _frameSeconds => _bufferSize / _sampleRate;

  @override
  void initState() {
    super.initState();
    _result.onPlayingChanged = (playing) {
      if (mounted) setState(() => _previewPlaying = playing);
    };
    _result.attach();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _result.dispose();
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
    await _result.stop();
    _frames.clear();
    _byteBuffer.clear();
    setState(() {
      _recording = true;
      _musicXml = null;
      _score = null;
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
    setState(() {
      _score = score;
      _musicXml = _builder.build(score);
    });
  }

  Future<void> _togglePreview() async {
    final score = _score;
    if (score == null) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await _result.togglePreview(score: score);
    } catch (e) {
      if (mounted) {
        messenger.showSnackBar(SnackBar(content: Text('试听失败: $e')));
      }
    }
  }

  Future<void> _export(String kind) async {
    if (kind == 'preview') {
      await _togglePreview();
      return;
    }
    final score = _score;
    final xml = _musicXml;
    if (score == null || xml == null) return;
    final export = const ScoreExport();
    final messenger = ScaffoldMessenger.of(context);
    try {
      switch (kind) {
        case 'musicxml':
          final where = await export.saveMusicXml(score);
          messenger.showSnackBar(SnackBar(content: Text('已导出 MusicXML：$where')));
        case 'midi':
          final where = await export.saveMidi(score);
          messenger.showSnackBar(SnackBar(content: Text('已导出 MIDI：$where')));
        case 'pdf':
          final svg = await ref.read(verovioRendererProvider).render(xml);
          await export.sharePdf(svg);
          messenger.showSnackBar(const SnackBar(content: Text('已导出 PDF')));
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('导出失败: $e')));
    }
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
    final hasScore = _score != null && !_recording;
    return Scaffold(
      appBar: AppBar(
        title: const Text('听音转五线谱'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        actions: [
          ScoreResultActions(
            enabled: hasScore,
            playing: _previewPlaying,
            onPreview: _togglePreview,
            onExport: _export,
          ),
        ],
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
                : Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
                        child: SegmentedButton<int>(
                          segments: const [
                            ButtonSegment(
                              value: 0,
                              label: Text('简谱'),
                              icon: Icon(Icons.pin_outlined, size: 18),
                            ),
                            ButtonSegment(
                              value: 1,
                              label: Text('五线谱'),
                              icon: Icon(Icons.music_note, size: 18),
                            ),
                          ],
                          selected: {_previewMode},
                          onSelectionChanged: (s) =>
                              setState(() => _previewMode = s.first),
                        ),
                      ),
                      Expanded(
                        child: _previewMode == 0 && _score != null
                            ? JianpuView(score: _score!)
                            : ScoreView(musicXml: _musicXml!),
                      ),
                    ],
                  ),
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
