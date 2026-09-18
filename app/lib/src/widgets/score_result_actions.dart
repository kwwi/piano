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
  });

  final bool enabled;
  final bool playing;
  final VoidCallback onPreview;
  final ValueChanged<String> onExport;
  final bool includeAbc;
  final bool includeRawMidi;

  @override
  Widget build(BuildContext context) {
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
            const PopupMenuItem(value: 'preview', child: Text('试听选中音轨')),
            const PopupMenuItem(value: 'musicxml', child: Text('导出 MusicXML（选中轨）')),
            const PopupMenuItem(value: 'midi', child: Text('导出 MIDI（选中轨）')),
            if (includeRawMidi)
              const PopupMenuItem(
                value: 'midi_raw',
                child: Text('导出原始 MIDI（全轨）'),
              ),
            if (includeAbc)
              const PopupMenuItem(value: 'abc', child: Text('导出 ABC（选中轨）')),
            const PopupMenuItem(value: 'pdf', child: Text('导出 / 分享 PDF（选中轨）')),
          ],
        ),
      ],
    );
  }
}
