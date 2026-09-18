"""Post-process arranged piano MIDI into playable RH/LH grand-staff parts."""
from __future__ import annotations

from pathlib import Path

PIANO_LO = 21  # A0
PIANO_HI = 108  # C8
SPLIT = 60  # Middle C
MAX_HAND_SPAN = 9
MAX_SIMUL = 4


def postprocess_piano_midi(midi_path: Path, out_midi: Path) -> Path:
    """Clamp range, split hands, thin polyphony → Piano RH / Piano LH."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    tempo = 120.0
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass

    rh_notes: list = []
    lh_notes: list = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        name = (inst.name or "").strip().lower()
        for n in inst.notes:
            pitch = _clamp_fold(int(n.pitch))
            note = pretty_midi.Note(
                velocity=max(40, min(120, int(n.velocity))),
                pitch=pitch,
                start=float(n.start),
                end=max(float(n.start) + 0.05, float(n.end)),
            )
            if "lh" in name or "left" in name or "bass" in name:
                lh_notes.append(note)
            elif "rh" in name or "right" in name or "melody" in name:
                rh_notes.append(note)
            elif pitch >= SPLIT:
                rh_notes.append(note)
            else:
                lh_notes.append(note)

    if not rh_notes and not lh_notes:
        raise RuntimeError("postprocess: empty piano MIDI")

    rh_notes = _thin_hand(rh_notes, prefer_high=True)
    lh_notes = _thin_hand(lh_notes, prefer_high=False)

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    rh = pretty_midi.Instrument(program=0, name="Piano RH")
    lh = pretty_midi.Instrument(program=0, name="Piano LH")
    rh.notes.extend(rh_notes)
    lh.notes.extend(lh_notes)
    out.instruments.extend([rh, lh])
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(out_midi))
    return out_midi


def _clamp_fold(pitch: int) -> int:
    p = int(pitch)
    while p < PIANO_LO:
        p += 12
    while p > PIANO_HI:
        p -= 12
    return max(PIANO_LO, min(PIANO_HI, p))


def _thin_hand(notes: list, *, prefer_high: bool) -> list:
    if not notes:
        return []
    # Bucket by quantized onset (30 ms).
    buckets: dict[int, list] = {}
    for n in notes:
        key = int(round(n.start / 0.03))
        buckets.setdefault(key, []).append(n)

    kept: list = []
    for key in sorted(buckets):
        group = buckets[key]
        group.sort(key=lambda n: n.pitch, reverse=prefer_high)
        chosen = group[:MAX_SIMUL]
        chosen.sort(key=lambda n: n.pitch)
        while len(chosen) > 1 and chosen[-1].pitch - chosen[0].pitch > MAX_HAND_SPAN:
            if prefer_high:
                chosen.pop(0)
            else:
                chosen.pop()
        kept.extend(chosen)
    return kept
