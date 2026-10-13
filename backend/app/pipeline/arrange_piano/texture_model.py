"""Texture-retrieval piano arranger (AccoMontage / Structured-Arrangement Stage-1 style).

Selects accompaniment textures from a compact pattern bank using chord quality
and local melody density, then re-harmonizes patterns onto the lead-sheet
chords while keeping the melody in the right hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Pattern:
    """One bar of LH relative to chord root (semitone offsets) + onset fractions."""

    name: str
    # list of (onset_frac_in_bar 0..1, dur_frac, [pc_offsets relative to root])
    events: tuple[tuple[float, float, tuple[int, ...]], ...]
    # Ideal melody-note density per bar for matching (notes/bar).
    density: float
    qualities: tuple[str, ...]  # maj min dom7 dim sus


# Compact learned-style bank (POP/ballad-ish textures).
_BANK: tuple[_Pattern, ...] = (
    _Pattern(
        "block_pop",
        (
            (0.0, 1.0, (0, 4, 7)),
        ),
        density=2.0,
        qualities=("maj", "min", "sus"),
    ),
    _Pattern(
        "block_7",
        (
            (0.0, 1.0, (0, 4, 7, 10)),
        ),
        density=2.0,
        qualities=("dom7",),
    ),
    _Pattern(
        "alberti",
        (
            (0.0, 0.25, (0,)),
            (0.25, 0.25, (7,)),
            (0.5, 0.25, (4,)),
            (0.75, 0.25, (7,)),
        ),
        density=4.0,
        qualities=("maj", "min"),
    ),
    _Pattern(
        "broken_up",
        (
            (0.0, 0.33, (0,)),
            (0.33, 0.33, (4,)),
            (0.66, 0.34, (7,)),
        ),
        density=3.0,
        qualities=("maj", "min", "sus"),
    ),
    _Pattern(
        "waltz",
        (
            (0.0, 0.34, (0,)),
            (0.34, 0.33, (4, 7)),
            (0.67, 0.33, (4, 7)),
        ),
        density=2.5,
        qualities=("maj", "min"),
    ),
    _Pattern(
        "ballad_arp",
        (
            (0.0, 0.25, (0,)),
            (0.25, 0.25, (7,)),
            (0.5, 0.25, (12,)),
            (0.75, 0.25, (7,)),
        ),
        density=1.5,
        qualities=("maj", "min", "dim"),
    ),
    _Pattern(
        "power_drive",
        (
            (0.0, 0.5, (0, 7)),
            (0.5, 0.5, (0, 7)),
        ),
        density=5.0,
        qualities=("maj", "min", "dom7", "sus"),
    ),
    _Pattern(
        "dim_cluster",
        (
            (0.0, 1.0, (0, 3, 6)),
        ),
        density=2.0,
        qualities=("dim",),
    ),
)


def arrange_texture(
    lead_midi: Path,
    out_midi: Path,
    *,
    style: str = "pop",
) -> Path:
    """Retrieve + reharmonize accompaniment textures onto the lead sheet."""
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
    bar_sec = (60.0 / max(tempo, 1e-6)) * 4.0

    melody = _named_notes(pm, "melody")
    chords = _named_notes(pm, "chords")
    if not melody:
        for inst in pm.instruments:
            if not inst.is_drum and inst.notes:
                melody = list(inst.notes)
                break
    if not melody:
        raise RuntimeError("texture arranger: empty melody")

    t_end = max(n.end for n in melody)
    if chords:
        t_end = max(t_end, max(n.end for n in chords))

    segments = _chord_segments(chords, t_end, bar_sec / 4.0)
    if not segments:
        # One bar per 4 beats from melody outline.
        t = 0.0
        while t < t_end:
            segs_pitch = [
                int(n.pitch)
                for n in melody
                if n.start < t + bar_sec and n.end > t
            ]
            root = (segs_pitch[0] % 12) if segs_pitch else 0
            segments.append((t, min(t_end, t + bar_sec), root, "maj", {root, (root + 4) % 12, (root + 7) % 12}))
            t += bar_sec

    style_key = (style or "pop").strip().lower()
    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    rh = pretty_midi.Instrument(program=0, name="Piano RH")
    lh = pretty_midi.Instrument(program=0, name="Piano LH")

    for n in melody:
        pitch = _fold(int(n.pitch), 55, 88)
        rh.notes.append(
            pretty_midi.Note(
                velocity=max(55, min(115, int(n.velocity))),
                pitch=pitch,
                start=float(n.start),
                end=float(n.end),
            )
        )

    for start, end, root_pc, quality, _pcs in segments:
        dens = _melody_density(melody, start, end, bar_sec)
        pat = _select_pattern(quality, dens, style_key)
        dur = max(0.2, float(end) - float(start))
        root_midi = 36 + int(root_pc)  # C2 octave
        for onset_f, dur_f, offsets in pat.events:
            n_start = float(start) + onset_f * dur
            n_end = min(float(end), n_start + max(0.08, dur_f * dur))
            for off in offsets:
                pitch = _fold(root_midi + int(off), 33, 64)
                # Avoid colliding with RH melody register.
                while pitch >= 60:
                    pitch -= 12
                lh.notes.append(
                    pretty_midi.Note(
                        velocity=58 if style_key == "ballad" else 64,
                        pitch=pitch,
                        start=n_start,
                        end=n_end,
                    )
                )

    out.instruments.extend([rh, lh])
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(out_midi))
    return out_midi


def _named_notes(pm, name: str) -> list:
    key = name.strip().lower()
    out = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        if key in (inst.name or "").strip().lower():
            out.extend(inst.notes)
    return out


def _fold(pitch: int, lo: int, hi: int) -> int:
    p = int(pitch)
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return max(21, min(108, p))


def _melody_density(notes: list, start: float, end: float, bar_sec: float) -> float:
    count = sum(1 for n in notes if n.start < end and n.end > start)
    bars = max(0.25, (end - start) / max(bar_sec, 1e-6))
    return count / bars


def _chord_segments(
    chord_notes: list, t_end: float, beat_sec: float
) -> list[tuple[float, float, int, str, set[int]]]:
    if not chord_notes:
        return []
    sorted_notes = sorted(chord_notes, key=lambda n: n.start)
    segs: list[tuple[float, float, int, str, set[int]]] = []
    cur_t = float(sorted_notes[0].start)
    bucket: list = []
    window = max(0.2, beat_sec)

    def flush(start: float, end: float, bucket_notes: list) -> None:
        if not bucket_notes:
            return
        pcs = {int(n.pitch) % 12 for n in bucket_notes}
        root = min(bucket_notes, key=lambda n: n.pitch).pitch % 12
        quality = _guess_quality(pcs, root)
        segs.append((start, end, root, quality, pcs))

    for n in sorted_notes:
        if bucket and float(n.start) - cur_t > window * 0.9:
            flush(cur_t, max(float(n.start), cur_t + window * 0.9), bucket)
            cur_t = float(n.start)
            bucket = [n]
        else:
            if not bucket:
                cur_t = float(n.start)
            bucket.append(n)
    if bucket:
        flush(cur_t, min(t_end, cur_t + window * 2), bucket)
    return segs


def _guess_quality(pcs: set[int], root: int) -> str:
    rel = {(p - root) % 12 for p in pcs}
    if 3 in rel and 6 in rel:
        return "dim"
    if 4 in rel and 10 in rel:
        return "dom7"
    if 3 in rel:
        return "min"
    if 5 in rel and 4 not in rel and 3 not in rel:
        return "sus"
    return "maj"


def _select_pattern(quality: str, density: float, style: str) -> _Pattern:
    candidates = [p for p in _BANK if quality in p.qualities] or list(_BANK)
    if style == "ballad":
        candidates = sorted(candidates, key=lambda p: abs(p.density - 1.5))
    elif style == "drive":
        candidates = sorted(candidates, key=lambda p: abs(p.density - 5.0))
    else:
        candidates = sorted(candidates, key=lambda p: abs(p.density - density))
    return candidates[0]
