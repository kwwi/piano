"""Extract a single main-melody line from polyphonic MIDI.

Basic Pitch / MT3 often emit chords and accompaniment. For the app we only
want one singable line: at each time, keep the highest sounding pitch
("skyline"), then merge into contiguous notes.
"""
from __future__ import annotations

from pathlib import Path


def extract_main_melody(
    midi_path: str | Path,
    out_midi: str | Path,
    *,
    hop: float = 0.02,
    min_dur: float = 0.06,
) -> Path:
    """Write a monophonic skyline MIDI to ``out_midi`` (in-place safe)."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pretty_midi is required for melody extraction") from exc

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    notes: list = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        notes.extend(inst.notes)

    if not notes:
        out_midi.write_bytes(midi_path.read_bytes())
        return out_midi

    t0 = min(n.start for n in notes)
    t1 = max(n.end for n in notes)
    frames: list[tuple[float, int | None, int]] = []
    t = t0
    while t < t1 + hop:
        active = [n for n in notes if n.start - 1e-6 <= t < n.end]
        if active:
            best = max(active, key=lambda n: (n.pitch, n.velocity))
            frames.append((t, int(best.pitch), int(best.velocity)))
        else:
            frames.append((t, None, 0))
        t += hop

    merged: list[tuple[float, float, int, int]] = []
    i = 0
    while i < len(frames):
        start, pitch, vel = frames[i]
        if pitch is None:
            i += 1
            continue
        j = i + 1
        while j < len(frames) and frames[j][1] == pitch:
            j += 1
        end = frames[j - 1][0] + hop
        if end - start >= min_dur:
            merged.append((start, end, pitch, max(40, vel)))
        i = j

    out = pretty_midi.PrettyMIDI(initial_tempo=_estimate_tempo(pm))
    inst = pretty_midi.Instrument(program=0, name="melody")
    for start, end, pitch, vel in merged:
        inst.notes.append(
            pretty_midi.Note(velocity=vel, pitch=pitch, start=start, end=end)
        )
    out.instruments.append(inst)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(out_midi))
    return out_midi


def _estimate_tempo(pm) -> float:
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            return float(tempos[0])
    except Exception:
        pass
    return 120.0
