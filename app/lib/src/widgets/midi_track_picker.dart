import 'package:flutter/material.dart';

import '../core/backend/api_client.dart';

/// Per-track chips: original / 主调 / 和弦. Selection uses tokens
/// ``0``, ``m0``, ``c0``, … matching the backend ``tracks`` query.
class MidiTrackPicker extends StatelessWidget {
  const MidiTrackPicker({
    super.key,
    required this.tracks,
    required this.selected,
    required this.onToggleToken,
    required this.onSelectAllSources,
    required this.onConfirm,
    this.dirty = false,
    this.enabled = true,
    this.confirming = false,
    this.arrangePiano = false,
    this.onArrangePianoChanged,
    this.scoreMode = ScoreMode.perTrack,
    this.onScoreModeChanged,
  });

  final List<MidiTrackInfo> tracks;
  final Set<String> selected;
  final void Function(String token, bool checked) onToggleToken;
  final void Function(bool all) onSelectAllSources;
  final VoidCallback onConfirm;
  final bool dirty;
  final bool enabled;
  final bool confirming;
  final bool arrangePiano;
  final ValueChanged<bool>? onArrangePianoChanged;
  final ScoreMode scoreMode;
  final ValueChanged<ScoreMode>? onScoreModeChanged;

  static String _scoreModeHint(ScoreMode mode) => switch (mode) {
        ScoreMode.perTrack =>
          '每个非鼓音轨各自生成大谱表；试听按勾选的多轨播放。',
        ScoreMode.pianoOnly =>
          '仅钢琴类音轨用模型排谱；确认后试听只播放钢琴类音轨。',
        ScoreMode.reduceAll =>
          '所有非鼓音轨合并成一份钢琴谱；确认后试听播放合并后的钢琴 MIDI。',
      };

  static String sourceToken(int index) => '$index';
  static String melodyToken(int index) => 'm$index';
  static String chordsToken(int index) => 'c$index';

  @override
  Widget build(BuildContext context) {
    if (tracks.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final n = selected.length;
    final canConfirm = enabled && dirty && n > 0 && !confirming;
    return Material(
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.55),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.queue_music,
                    size: 20, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'MIDI 音轨 · 已选 $n 项${dirty ? '（未应用）' : ''}',
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                TextButton(
                  onPressed: enabled && !confirming
                      ? () => onSelectAllSources(true)
                      : null,
                  child: const Text('全选原轨'),
                ),
                TextButton(
                  onPressed: enabled && !confirming
                      ? () => onSelectAllSources(false)
                      : null,
                  child: const Text('清空'),
                ),
                const SizedBox(width: 4),
                FilledButton(
                  onPressed: canConfirm ? onConfirm : null,
                  child: confirming
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('确认'),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              arrangePiano
                  ? '钢琴谱模式：用勾选的主调（±和弦）编配为双手可弹大谱表；未勾主调时从原轨自动抽主调。'
                  : '每轨可勾选「原轨 / 主调 / 和弦」；确认后更新谱面与导出，试听按当前勾选在客户端播放。',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            if (onArrangePianoChanged != null) ...[
              const SizedBox(height: 4),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('钢琴谱'),
                subtitle: const Text('吉他等乐器 → 钢琴可演奏五线谱'),
                value: arrangePiano,
                onChanged: enabled && !confirming ? onArrangePianoChanged : null,
              ),
            ],
            if (onScoreModeChanged != null && !arrangePiano) ...[
              const SizedBox(height: 4),
              Row(
                children: [
                  Text('谱面生成', style: theme.textTheme.bodyMedium),
                  const SizedBox(width: 12),
                  Expanded(
                    child: SegmentedButton<ScoreMode>(
                      showSelectedIcon: false,
                      segments: [
                        for (final m in ScoreMode.values)
                          ButtonSegment(value: m, label: Text(m.label)),
                      ],
                      selected: {scoreMode},
                      onSelectionChanged: enabled && !confirming
                          ? (s) => onScoreModeChanged!(s.first)
                          : null,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                _scoreModeHint(scoreMode),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 280),
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: tracks.length,
                separatorBuilder: (_, __) => const SizedBox(height: 8),
                itemBuilder: (context, i) {
                  final t = tracks[i];
                  final src = sourceToken(t.index);
                  final mel = melodyToken(t.index);
                  final ch = chordsToken(t.index);
                  final drum = t.isDrum;
                  final canDerive = !drum && t.noteCount > 0;
                  return Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: theme.colorScheme.outlineVariant,
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          t.chipLabel,
                          style: theme.textTheme.titleSmall,
                        ),
                        if (t.detailLabel.isNotEmpty)
                          Text(
                            t.detailLabel,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        const SizedBox(height: 6),
                        Wrap(
                          spacing: 8,
                          runSpacing: 6,
                          children: [
                            FilterChip(
                              selected: selected.contains(src),
                              showCheckmark: true,
                              label: const Text('原轨'),
                              onSelected: enabled && !confirming
                                  ? (v) => onToggleToken(src, v)
                                  : null,
                            ),
                            FilterChip(
                              selected: selected.contains(mel),
                              showCheckmark: true,
                              label: const Text('主调'),
                              tooltip: !canDerive
                                  ? (drum
                                      ? '鼓轨无法提取主调'
                                      : '该轨没有音符，无法提取主调')
                                  : '从该轨提取主旋律（skyline）',
                              onSelected: enabled && !confirming && canDerive
                                  ? (v) => onToggleToken(mel, v)
                                  : null,
                            ),
                            FilterChip(
                              selected: selected.contains(ch),
                              showCheckmark: true,
                              label: const Text('和弦'),
                              tooltip: !canDerive
                                  ? (drum
                                      ? '鼓轨无法提取和弦'
                                      : '该轨没有音符，无法提取和弦')
                                  : '从该轨估计和弦垫音',
                              onSelected: enabled && !confirming && canDerive
                                  ? (v) => onToggleToken(ch, v)
                                  : null,
                            ),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
