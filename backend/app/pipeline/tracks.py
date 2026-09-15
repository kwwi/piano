"""Inspect / subset multi-instrument MIDI (MT3 often emits one track per program)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class TrackError(RuntimeError):
    pass


# GM family → short label (aligned with common MusicXML / Verovio abbreviations).
_GM_ABBREV: list[tuple[range, str]] = [
    (range(0, 8), "Pno"),
    (range(8, 16), "Chrom"),
    (range(16, 24), "Org"),
    (range(24, 32), "Guit"),
    (range(32, 40), "Bass"),
    (range(40, 48), "Str"),
    (range(48, 56), "Ens"),
    (range(56, 64), "Bras"),
    (range(64, 72), "Reed"),
    (range(72, 80), "Pipe"),
    (range(80, 88), "Lead"),
    (range(88, 96), "Pad"),
    (range(96, 104), "Fx"),
    (range(104, 112), "Eth"),
    (range(112, 120), "Perc"),
    (range(120, 128), "SFX"),
]


def _abbrev_for(program: int, *, is_drum: bool) -> str:
    if is_drum:
        return "Drum"
    for rng, label in _GM_ABBREV:
        if program in rng:
            return label
    return f"P{program}"


def _midi_track_meta_names(midi_path: Path) -> list[str]:
    """Best-effort MIDI track_name meta events (mido), excluding the tempo track."""
    try:
        import mido
    except Exception:
        return []
    try:
        mid = mido.MidiFile(str(midi_path))
    except Exception:
        return []
    names: list[str] = []
    for i, tr in enumerate(mid.tracks):
        if i == 0 and len(mid.tracks) > 1:
            # Type-1 tempo/conductor track — skip unless it is the only track.
            continue
        found = ""
        for msg in tr:
            if msg.type == "track_name":
                found = (msg.name or "").strip()
                if found:
                    break
        names.append(found)
    return names


def list_midi_tracks(midi_path: str | Path) -> list[dict]:
    """Return metadata for each pretty_midi instrument in ``midi_path``.

    Display names prefer MIDI track_name / instrument name; otherwise use a short
    family label with an index (``Pno0``, ``Pno1``, …) so the UI matches typical
    engraved staff abbreviations.
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    if not midi_path.is_file():
        raise TrackError(f"MIDI not found: {midi_path}")

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    meta_names = _midi_track_meta_names(midi_path)

    # First pass: collect base fields + preferred raw name.
    pending: list[dict] = []
    for i, inst in enumerate(pm.instruments):
        program = int(inst.program)
        if inst.is_drum:
            program_name = "Drums"
        else:
            try:
                program_name = pretty_midi.program_to_instrument_name(program)
            except Exception:
                program_name = f"Program {program}"
        abbrev = _abbrev_for(program, is_drum=bool(inst.is_drum))
        raw = (inst.name or "").strip()
        if not raw and i < len(meta_names) and meta_names[i]:
            raw = meta_names[i]
        starts = [n.start for n in inst.notes]
        ends = [n.end for n in inst.notes]
        pending.append(
            {
                "index": i,
                "raw_name": raw,
                "program": program,
                "program_name": program_name,
                "abbreviation": abbrev,
                "is_drum": bool(inst.is_drum),
                "note_count": len(inst.notes),
                "duration_sec": round(max(ends) - min(starts), 3) if starts else 0.0,
            }
        )

    # Assign unique display names: keep explicit MIDI names; else Abbrev+index.
    abbrev_counts: dict[str, int] = {}
    tracks: list[dict] = []
    for item in pending:
        raw = item.pop("raw_name")
        abbrev = item["abbreviation"]
        seq = abbrev_counts.get(abbrev, 0)
        abbrev_counts[abbrev] = seq + 1
        if raw:
            display = raw
        else:
            display = f"{abbrev}{seq}"
        item["name"] = display
        tracks.append(item)
    return tracks


def annotate_instrument_names(midi_path: str | Path) -> Path:
    """Write computed display names back onto empty instrument.name fields."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    tracks = list_midi_tracks(midi_path)
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    changed = False
    for t, inst in zip(tracks, pm.instruments):
        name = str(t["name"])
        if (inst.name or "").strip() != name:
            inst.name = name
            changed = True
    if changed:
        pm.write(str(midi_path))
    return midi_path


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

    labels = {t["index"]: t["name"] for t in list_midi_tracks(midi_path)}

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
            name=labels.get(i) or inst.name or f"Track{i}",
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
