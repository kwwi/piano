"""Inspect / subset multi-instrument MIDI (MT3 often emits one track per program)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class TrackError(RuntimeError):
    pass


def list_midi_tracks(midi_path: str | Path) -> list[dict]:
    """Return metadata for each pretty_midi instrument in ``midi_path``."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    if not midi_path.is_file():
        raise TrackError(f"MIDI not found: {midi_path}")

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    tracks: list[dict] = []
    for i, inst in enumerate(pm.instruments):
        program = int(inst.program)
        if inst.is_drum:
            program_name = "Drums"
            display = inst.name.strip() or "Drums"
        else:
            try:
                program_name = pretty_midi.program_to_instrument_name(program)
            except Exception:
                program_name = f"Program {program}"
            display = inst.name.strip() or program_name
        starts = [n.start for n in inst.notes]
        ends = [n.end for n in inst.notes]
        tracks.append(
            {
                "index": i,
                "name": display,
                "program": program,
                "program_name": program_name,
                "is_drum": bool(inst.is_drum),
                "note_count": len(inst.notes),
                "duration_sec": round(max(ends) - min(starts), 3) if starts else 0.0,
            }
        )
    return tracks


def write_tracks_manifest(
    midi_path: str | Path,
    out_json: str | Path,
    *,
    source_name: str = "transcription_raw.mid",
) -> Path:
    """Write ``tracks.json`` next to the job artifacts."""
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source_name,
        "tracks": list_midi_tracks(midi_path),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_json


def write_per_track_midis(
    midi_path: str | Path,
    out_dir: str | Path,
) -> list[Path]:
    """Write one MIDI file per instrument under ``out_dir`` (track_00.mid …)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracks = list_midi_tracks(midi_path)
    written: list[Path] = []
    for t in tracks:
        dest = out_dir / f"track_{t['index']:02d}.mid"
        write_track_subset(midi_path, dest, [t["index"]])
        written.append(dest)
    return written


def parse_track_indices(raw: str | None, *, track_count: int) -> list[int] | None:
    """Parse ``tracks`` query: ``None`` / empty → all tracks; else unique sorted indices.

    Returns ``None`` meaning “use the full original file” (all tracks, no rewrite).
    """
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    if not parts:
        return None
    indices: list[int] = []
    for p in parts:
        try:
            idx = int(p)
        except ValueError as exc:
            raise TrackError(f"invalid track index: {p!r}") from exc
        if idx < 0 or idx >= track_count:
            raise TrackError(f"track index out of range: {idx} (0..{track_count - 1})")
        if idx not in indices:
            indices.append(idx)
    if len(indices) == track_count and indices == list(range(track_count)):
        return None
    return indices


def write_track_subset(
    midi_path: str | Path,
    out_midi: str | Path,
    indices: Iterable[int],
) -> Path:
    """Write a new MIDI containing only the selected instrument indices."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)

    want = list(indices)
    if not want:
        raise TrackError("at least one track index is required")

    src = pretty_midi.PrettyMIDI(str(midi_path))
    if max(want) >= len(src.instruments):
        raise TrackError(
            f"track index out of range (have {len(src.instruments)} instruments)"
        )

    tempo = 120.0
    try:
        tempos = src.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    for i in want:
        inst = src.instruments[i]
        clone = pretty_midi.Instrument(
            program=inst.program,
            is_drum=inst.is_drum,
            name=inst.name,
        )
        for n in inst.notes:
            clone.notes.append(
                pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start,
                    end=n.end,
                )
            )
        for pb in inst.pitch_bends:
            clone.pitch_bends.append(
                pretty_midi.PitchBend(pitch=pb.pitch, time=pb.time)
            )
        for cc in inst.control_changes:
            clone.control_changes.append(
                pretty_midi.ControlChange(
                    number=cc.number, value=cc.value, time=cc.time
                )
            )
        out.instruments.append(clone)

    out.write(str(out_midi))
    return out_midi


def resolve_raw_midi(job_dir: Path) -> Path:
    raw = job_dir / "transcription_raw.mid"
    if raw.is_file():
        return raw
    legacy = job_dir / "transcription.mid"
    if legacy.is_file():
        return legacy
    raise TrackError("transcription_raw.mid not found")
