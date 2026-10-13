"""Rule-based piano arrangement: RH melody + LH chord pads."""
from __future__ import annotations

from pathlib import Path


def arrange_rule(lead_midi: Path, out_midi: Path) -> Path:
    """Simple playable piano from Melody + Chords lead sheet."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pretty_midi is required") from exc

    lead_midi = Path(lead_midi)
    out_midi = Path(out_midi)
    pm = pretty_midi.PrettyMIDI(str(lead_midi))

    tempo = 120.0
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass

    melody = _notes_named(pm, "melody")
    chords = _notes_named(pm, "chords")
    if not melody:
        for inst in pm.instruments:
            if not inst.is_drum:
                melody.extend(inst.notes)
                break

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    rh = pretty_midi.Instrument(program=0, name="Piano RH")
    lh = pretty_midi.Instrument(program=0, name="Piano LH")

    for n in melody:
        pitch = _fold_into(int(n.pitch), 48, 84)  # C3–C6
        rh.notes.append(
            pretty_midi.Note(
                velocity=max(50, min(110, int(n.velocity))),
                pitch=pitch,
                start=float(n.start),
                end=float(n.end),
            )
        )

    # Group chord notes by onset windows (~beat).
    beat = 60.0 / max(tempo, 1e-6)
    windows = _group_by_window(chords, beat)
    if not windows and melody:
        # Invent sparse tonic-ish pads under melody onsets.
        for n in melody[:: max(1, len(melody) // 8 or 1)]:
            root = _fold_into(int(n.pitch) % 12 + 48, 36, 55)
            windows.append(
                (float(n.start), float(n.start) + beat, [root, root + 4, root + 7])
            )

    for start, end, pcs in windows:
        voicing = _compact_voicing(pcs, low=36, high=60)
        dur = max(0.12, float(end) - float(start))
        for p in voicing[:4]:
            lh.notes.append(
                pretty_midi.Note(
                    velocity=62,
                    pitch=int(p),
                    start=float(start),
                    end=float(start) + dur,
                )
            )

    out.instruments.extend([rh, lh])
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(out_midi))
    return out_midi


def _notes_named(pm, name: str) -> list:
    key = name.strip().lower()
    out = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        if key in (inst.name or "").strip().lower():
            out.extend(inst.notes)
    return out


def _fold_into(pitch: int, lo: int, hi: int) -> int:
    p = int(pitch)
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return max(21, min(108, p))


def _group_by_window(notes: list, window: float) -> list[tuple[float, float, list[int]]]:
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: n.start)
    groups: list[tuple[float, float, list[int]]] = []
    cur_start = float(sorted_notes[0].start)
    cur_end = float(sorted_notes[0].end)
    pcs: set[int] = set()
    for n in sorted_notes:
        if float(n.start) - cur_start > window * 0.85 and pcs:
            groups.append((cur_start, max(cur_end, cur_start + window * 0.9), sorted(pcs)))
            cur_start = float(n.start)
            cur_end = float(n.end)
            pcs = {int(n.pitch)}
        else:
            pcs.add(int(n.pitch))
            cur_end = max(cur_end, float(n.end))
    if pcs:
        groups.append((cur_start, max(cur_end, cur_start + window * 0.9), sorted(pcs)))
    return groups


def _compact_voicing(pitches: list[int], *, low: int, high: int) -> list[int]:
    if not pitches:
        return []
    pcs = sorted({p % 12 for p in pitches})
    # Prefer root-ish lowest pitch class from original.
    root_pc = min(pitches) % 12
    ordered = [root_pc] + [p for p in pcs if p != root_pc]
    voicing: list[int] = []
    base = low + (root_pc - low % 12) % 12
    if base < low:
        base += 12
    cursor = base
    for i, pc in enumerate(ordered[:4]):
        p = cursor - (cursor % 12) + pc
        if i == 0:
            p = base if base % 12 == pc else cursor - cursor % 12 + pc
        while p < low:
            p += 12
        while p > high:
            p -= 12
        if voicing and p <= voicing[-1]:
            p += 12
        if p > high:
            p -= 12
        voicing.append(max(21, min(108, p)))
        cursor = voicing[-1]
    # Enforce one-hand span ~9 semitones by dropping outliers.
    voicing = sorted(set(voicing))
    while len(voicing) > 1 and voicing[-1] - voicing[0] > 9:
        voicing.pop()
    return voicing
