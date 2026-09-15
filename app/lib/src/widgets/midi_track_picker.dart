import 'package:flutter/material.dart';

import '../core/backend/api_client.dart';

/// Checkbox / chip strip for selecting MIDI instrument tracks by name.
class MidiTrackPicker extends StatelessWidget {
  const MidiTrackPicker({
    super.key,
    required this.tracks,
    required this.selected,
    required this.onToggle,
    required this.onSelectAll,
    this.enabled = true,
  });

  final List<MidiTrackInfo> tracks;
  final Set<int> selected;
  final void Function(int index, bool checked) onToggle;
  final void Function(bool all) onSelectAll;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    if (tracks.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final n = selected.length;
    return Material(
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.55),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.queue_music, size: 20, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'MIDI 音轨（勾选后预览 / 导出）· 已选 $n/${tracks.length}',
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                TextButton(
                  onPressed: enabled ? () => onSelectAll(true) : null,
                  child: const Text('全选'),
                ),
                TextButton(
                  onPressed: enabled ? () => onSelectAll(false) : null,
                  child: const Text('清空'),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '名称与谱表标签对应（如 Pno0）。取消勾选可隐藏该轨。',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 168),
              child: SingleChildScrollView(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final t in tracks)
                      FilterChip(
                        selected: selected.contains(t.index),
                        showCheckmark: true,
                        label: Text(t.chipLabel),
                        tooltip: t.detailLabel.isEmpty
                            ? t.chipLabel
                            : '${t.chipLabel}\n${t.detailLabel}',
                        onSelected: enabled
                            ? (v) => onToggle(t.index, v)
                            : null,
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
