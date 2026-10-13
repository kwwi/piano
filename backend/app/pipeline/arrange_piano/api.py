"""Public API: selection → lead → model → postprocess → piano MIDI."""
from __future__ import annotations

import logging
from pathlib import Path

from ..track_derive import TrackSelection, derived_dir
from ..tracks import TrackError

log = logging.getLogger("piano.arrange_piano")


class ArrangePianoError(TrackError):
    pass


def arrange_for_piano(
    job_dir: Path,
    selection: TrackSelection | None,
    out_midi: Path,
    *,
    backend: str | None = None,
    style: str | None = None,
    auto_chords: bool | None = None,
) -> Path:
    """Full pipeline: lead assembly → learning/rule arrange → RH/LH postprocess.

    Caches intermediate lead + arranged MIDI under ``job_dir/derived/``.
    """
    from ...config import (
        PIANO_ARRANGER_AUTO_CHORDS,
        PIANO_ARRANGER_BACKEND,
        PIANO_ARRANGER_ROOT,
        PIANO_ARRANGER_STYLE,
    )
    from .lead_input import LeadInputError, build_lead_midi
    from .model_runner import run_piano_arranger
    from .postprocess import postprocess_piano_midi

    job_dir = Path(job_dir)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)

    backend = (backend or PIANO_ARRANGER_BACKEND or "auto").strip().lower()
    style = (style or PIANO_ARRANGER_STYLE or "pop").strip().lower()
    if auto_chords is None:
        auto_chords = PIANO_ARRANGER_AUTO_CHORDS

    sel_key = selection.cache_key if selection is not None else "all"
    chord_tag = "cauto" if auto_chords else "coff"
    cache_stem = f"piano_{sel_key}_{backend}_{style}_{chord_tag}"

    derived = derived_dir(job_dir)
    lead_path = derived / f"{cache_stem}_lead.mid"
    raw_path = derived / f"{cache_stem}_raw.mid"
    final_path = out_midi

    if final_path.is_file() and final_path.stat().st_size > 0:
        return final_path

    try:
        if not lead_path.is_file():
            build_lead_midi(
                job_dir,
                selection,
                lead_path,
                auto_chords=bool(auto_chords),
            )
    except LeadInputError as exc:
        raise ArrangePianoError(str(exc)) from exc
    except TrackError as exc:
        raise ArrangePianoError(str(exc)) from exc

    try:
        if not raw_path.is_file():
            run_piano_arranger(
                lead_path,
                raw_path,
                backend=backend,
                style=style,
                structured_root=PIANO_ARRANGER_ROOT or None,
            )
        # Atomic final write so parallel /midi + /musicxml never read a partial file.
        if not final_path.is_file() or final_path.stat().st_size == 0:
            tmp_final = final_path.with_suffix(final_path.suffix + ".tmp")
            postprocess_piano_midi(raw_path, tmp_final)
            tmp_final.replace(final_path)
    except Exception as exc:
        raise ArrangePianoError(f"piano arrangement failed: {exc}") from exc

    if not final_path.is_file():
        raise ArrangePianoError("piano arrangement produced no MIDI")
    log.info(
        "arrange_for_piano → %s (backend=%s style=%s)",
        final_path.name,
        backend,
        style,
    )
    return final_path
