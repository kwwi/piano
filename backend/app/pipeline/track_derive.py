"""Per-source-track melody / chord derivation and selection assembly.

Selection tokens in the ``tracks`` query:
  - ``0``, ``1``, … — original instrument tracks
  - ``m0``, ``m1``, … — skyline main melody extracted from that source track
  - ``c0``, ``c1``, … — chord pads estimated from that source track
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .tracks import TrackError, resolve_score_midi, write_track_subset

_TOKEN_RE = re.compile(r"^(?:m|c)?\d+$", re.IGNORECASE)


@dataclass
class TrackSelection:
    """Parsed ``tracks`` query (order preserved, duplicates dropped)."""

    sources: list[int] = field(default_factory=list)
    melodies: list[int] = field(default_factory=list)
    chords: list[int] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.sources or self.melodies or self.chords)

    @property
    def has_derived(self) -> bool:
        return bool(self.melodies or self.chords)

    @property
    def cache_key(self) -> str:
        return "_".join(self.tokens) if self.tokens else "all"


def parse_track_selection(raw: str | None, *, track_count: int) -> TrackSelection | None:
    """Parse mixed selection. ``None`` means “full original score, no rewrite”."""
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    if not parts:
        return None

    sel = TrackSelection()
    seen: set[str] = set()
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        if not _TOKEN_RE.match(key):
            raise TrackError(f"invalid track token: {p!r} (use 0, m0, c0, …)")
        if key.startswith("m"):
            idx = int(key[1:])
            _check_index(idx, track_count)
            sel.melodies.append(idx)
            sel.tokens.append(f"m{idx}")
        elif key.startswith("c"):
            idx = int(key[1:])
            _check_index(idx, track_count)
            sel.chords.append(idx)
            sel.tokens.append(f"c{idx}")
        else:
            idx = int(key)
            _check_index(idx, track_count)
            sel.sources.append(idx)
            sel.tokens.append(str(idx))
        seen.add(key)

    if (
        not sel.has_derived
        and len(sel.sources) == track_count
        and sel.sources == list(range(track_count))
    ):
        return None
    if sel.is_empty:
        raise TrackError("at least one track token is required")
    return sel


def _check_index(idx: int, track_count: int) -> None:
    if idx < 0 or idx >= track_count:
        raise TrackError(f"track index out of range: {idx} (0..{track_count - 1})")


def derived_dir(job_dir: Path) -> Path:
    d = Path(job_dir) / "derived"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_track_melody(job_dir: Path, source_index: int) -> Path:
    """Skyline melody MIDI for one source instrument (cached)."""
    from .melody import extract_main_melody

    job_dir = Path(job_dir)
    out = derived_dir(job_dir) / f"track_{source_index:02d}_melody.mid"
    if out.is_file():
        return out
    score = resolve_score_midi(job_dir)
    subset = derived_dir(job_dir) / f"track_{source_index:02d}_src.mid"
    if not subset.is_file():
        write_track_subset(score, subset, [source_index])
    extract_main_melody(subset, out)
    return out


def ensure_track_chords(job_dir: Path, source_index: int) -> Path:
    """Chord-pad MIDI estimated from one source instrument (cached)."""
    from .lead_sheet import LeadSheetError, build_lead_sheet

    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    job_dir = Path(job_dir)
    out = derived_dir(job_dir) / f"track_{source_index:02d}_chords.mid"
    if out.is_file():
        return out
    score = resolve_score_midi(job_dir)
    subset = derived_dir(job_dir) / f"track_{source_index:02d}_src.mid"
    if not subset.is_file():
        write_track_subset(score, subset, [source_index])
    lead = derived_dir(job_dir) / f"track_{source_index:02d}_lead_tmp.mid"
    chords_json = derived_dir(job_dir) / f"track_{source_index:02d}_chords.json"
    try:
        build_lead_sheet(
            subset,
            lead,
            chords_json=chords_json,
            exclude_melody_pcs=False,
        )
    except LeadSheetError as exc:
        raise TrackError(f"chord extract failed for track {source_index}: {exc}") from exc

    pm = pretty_midi.PrettyMIDI(str(lead))
    tempo = 120.0
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass
    out_pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    for inst in pm.instruments:
        if (inst.name or "").strip().lower() == "chords":
            clone = pretty_midi.Instrument(
                program=inst.program,
                is_drum=False,
                name=f"Track{source_index} Chords",
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
            out_pm.instruments.append(clone)
            break
    if not out_pm.instruments:
        raise TrackError(f"no chords produced for track {source_index}")
    out_pm.write(str(out))
    try:
        lead.unlink(missing_ok=True)
    except Exception:
        pass
    return out


def assemble_selection_midi(
    job_dir: Path,
    selection: TrackSelection,
    out_midi: Path,
) -> Path:
    """Merge selected source / melody / chord parts into one MIDI file."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise TrackError("pretty_midi is required") from exc

    job_dir = Path(job_dir)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    score = resolve_score_midi(job_dir)

    tempo = 120.0
    try:
        src = pretty_midi.PrettyMIDI(str(score))
        tempos = src.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        src = pretty_midi.PrettyMIDI(str(score))

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)

    def _append_from(path: Path, *, rename: str | None = None) -> None:
        pm = pretty_midi.PrettyMIDI(str(path))
        for inst in pm.instruments:
            name = rename or (inst.name or "").strip() or "Part"
            clone = pretty_midi.Instrument(
                program=inst.program,
                is_drum=inst.is_drum,
                name=name,
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
            out.instruments.append(clone)

    for idx in selection.sources:
        if idx >= len(src.instruments):
            raise TrackError(f"track index out of range: {idx}")
        inst = src.instruments[idx]
        clone = pretty_midi.Instrument(
            program=inst.program,
            is_drum=inst.is_drum,
            name=(inst.name or "").strip() or f"Track{idx}",
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
        out.instruments.append(clone)

    for idx in selection.melodies:
        mel = ensure_track_melody(job_dir, idx)
        base = ""
        if idx < len(src.instruments):
            base = (src.instruments[idx].name or "").strip()
        label = f"{base} Melody" if base else f"Track{idx} Melody"
        _append_from(mel, rename=label)

    for idx in selection.chords:
        ch = ensure_track_chords(job_dir, idx)
        base = ""
        if idx < len(src.instruments):
            base = (src.instruments[idx].name or "").strip()
        label = f"{base} Chords" if base else f"Track{idx} Chords"
        _append_from(ch, rename=label)

    if not out.instruments:
        raise TrackError("selection produced empty MIDI")
    out.write(str(out_midi))
    return out_midi
