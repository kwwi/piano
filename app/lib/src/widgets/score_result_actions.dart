import 'package:flutter/material.dart';

/// AppBar actions: MIDI preview toggle + export menu (MusicXML / MIDI / PDF).
class ScoreResultActions extends StatelessWidget {
  const ScoreResultActions({
    super.key,
    required this.enabled,
    required this.playing,
    required this.onPreview,
    required this.onExport,
    this.includeAbc = false,
    this.includeRawMidi = false,
    this.trackScoped = true,
  });

  final bool enabled;
  final bool playing;
  final VoidCallback onPreview;
  final ValueChanged<String> onExport;
  final bool includeAbc;
  final bool includeRawMidi;

  /// When true, export labels mention「选中轨」(audio upload). Jianpu / listen
  /// pass false for plain MusicXML / ABC / MIDI labels.
  final bool trackScoped;

  @override
  Widget build(BuildContext context) {
    final suffix = trackScoped ? '（选中轨）' : '';
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          icon: Icon(
            playing ? Icons.stop_circle_outlined : Icons.play_circle_outline,
          ),
          tooltip: playing ? '停止试听' : '试听 MIDI',
          onPressed: enabled ? onPreview : null,
        ),
        PopupMenuButton<String>(
          icon: const Icon(Icons.download),
          tooltip: '导出',
          onSelected: onExport,
          enabled: enabled,
          itemBuilder: (context) => [
            PopupMenuItem(
              value: 'preview',
              child: Text(trackScoped ? '试听选中音轨' : '试听'),
            ),
            PopupMenuItem(
              value: 'musicxml',
              child: Text('导出 MusicXML$suffix'),
            ),
            PopupMenuItem(
              value: 'midi',
              child: Text('导出 MIDI$suffix'),
            ),
            if (includeRawMidi)
              const PopupMenuItem(
                value: 'midi_raw',
                child: Text('导出原始 MIDI（全轨）'),
              ),
            if (includeAbc)
              PopupMenuItem(
                value: 'abc',
                child: Text('导出 ABC$suffix'),
              ),
            PopupMenuItem(
              value: 'pdf',
              child: Text('导出 / 分享 PDF$suffix'),
            ),
          ],
        ),
      ],
    );
  }
}
