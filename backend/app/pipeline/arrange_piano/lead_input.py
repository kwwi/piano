"""Assemble Melody + Chords lead MIDI from a track selection."""
from __future__ import annotations

from pathlib import Path

from ..track_derive import (
    TrackSelection,
    ensure_track_chords,
    ensure_track_melody,
)
from ..tracks import TrackError, resolve_score_midi


class LeadInputError(TrackError):
    pass


def build_lead_midi(
    job_dir: Path,
    selection: TrackSelection | None,
    out_midi: Path,
    *,
    auto_chords: bool = True,
) -> Path:
    """Write a 2-track lead sheet (Melody + Chords) for piano arrangement.

    Melody sources (priority):
      1. Explicit ``mN`` tokens
      2. Skyline from selected source tracks
      3. Skyline from the full score (when selection is empty / full)

    Chords:
      - Explicit ``cN`` tokens, else
      - Auto-estimate from the same source as melody when ``auto_chords``.
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise LeadInputError("pretty_midi is required") from exc

    from ..lead_sheet import LeadSheetError, build_lead_sheet
    from ..melody import extract_main_melody

    job_dir = Path(job_dir)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    score = resolve_score_midi(job_dir)
    src = pretty_midi.PrettyMIDI(str(score))

    tempo = 120.0
    try:
        tempos = src.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass

    melody_notes: list = []
    harmony_paths: list[Path] = []

    if selection is not None and selection.melodies:
        for idx in selection.melodies:
            mel = ensure_track_melody(job_dir, idx)
            pm = pretty_midi.PrettyMIDI(str(mel))
            for inst in pm.instruments:
                if not inst.is_drum:
                    melody_notes.extend(inst.notes)
            harmony_paths.append(
                _source_subset(job_dir, score, src, idx)
            )
    elif selection is not None and selection.sources:
        for idx in selection.sources:
            if idx >= len(src.instruments):
                continue
            if src.instruments[idx].is_drum:
                continue
            mel = ensure_track_melody(job_dir, idx)
            pm = pretty_midi.PrettyMIDI(str(mel))
            for inst in pm.instruments:
                if not inst.is_drum:
                    melody_notes.extend(inst.notes)
            harmony_paths.append(
                _source_subset(job_dir, score, src, idx)
            )
    else:
        tmp = out_midi.parent / f".{out_midi.stem}_skyline.mid"
        extract_main_melody(score, tmp)
        pm = pretty_midi.PrettyMIDI(str(tmp))
        for inst in pm.instruments:
            if not inst.is_drum:
                melody_notes.extend(inst.notes)
        harmony_paths.append(score)

    if not melody_notes:
        raise LeadInputError("no melody notes available for piano arrangement")

    # Merge overlapping same-pitch runs; keep skyline on polyphony clashes.
    melody_notes = _skyline_merge(melody_notes)

    chord_notes: list = []
    if selection is not None and selection.chords:
        for idx in selection.chords:
            ch = ensure_track_chords(job_dir, idx)
            pm = pretty_midi.PrettyMIDI(str(ch))
            for inst in pm.instruments:
                if not inst.is_drum:
                    chord_notes.extend(inst.notes)
    elif auto_chords:
        harm = harmony_paths[0] if harmony_paths else score
        lead_tmp = out_midi.parent / f".{out_midi.stem}_lead_tmp.mid"
        try:
            build_lead_sheet(
                harm,
                lead_tmp,
                exclude_melody_pcs=False,
            )
            pm = pretty_midi.PrettyMIDI(str(lead_tmp))
            for inst in pm.instruments:
                if (inst.name or "").strip().lower() == "chords":
                    chord_notes.extend(inst.notes)
                    break
        except LeadSheetError:
            chord_notes = []
        finally:
            try:
                lead_tmp.unlink(missing_ok=True)
            except Exception:
                pass

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    mel_inst = pretty_midi.Instrument(program=0, name="Melody")
    for n in melody_notes:
        mel_inst.notes.append(
            pretty_midi.Note(
                velocity=max(40, int(n.velocity)),
                pitch=int(n.pitch),
                start=float(n.start),
                end=float(n.end),
            )
        )
    out.instruments.append(mel_inst)

    ch_inst = pretty_midi.Instrument(program=0, name="Chords")
    for n in chord_notes:
        ch_inst.notes.append(
            pretty_midi.Note(
                velocity=max(40, int(n.velocity)),
                pitch=int(n.pitch),
                start=float(n.start),
                end=float(n.end),
            )
        )
    out.instruments.append(ch_inst)
    out.write(str(out_midi))
    return out_midi


def _source_subset(job_dir: Path, score: Path, src, idx: int) -> Path:
    from ..tracks import write_track_subset

    derived = Path(job_dir) / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    subset = derived / f"track_{idx:02d}_src.mid"
    if not subset.is_file():
        write_track_subset(score, subset, [idx])
    return subset


def _skyline_merge(notes: list) -> list:
    """Collapse simultaneous notes to the highest pitch."""
    if not notes:
        return []
    try:
        import pretty_midi
    except Exception:
        return list(notes)

    events: list[tuple[float, float, int, int]] = []
    for n in notes:
        events.append((float(n.start), float(n.end), int(n.pitch), int(n.velocity)))
    events.sort(key=lambda e: (e[0], -e[2]))

    # Greedy: keep non-overlapping skyline by onset order.
    kept: list = []
    for start, end, pitch, vel in events:
        if end <= start:
            continue
        clash = False
        for kn in kept:
            if start < kn.end and end > kn.start:
                if pitch > kn.pitch:
                    kn.end = start  # truncate lower note
                    if kn.end <= kn.start + 1e-3:
                        kn.end = kn.start
                else:
                    clash = True
                    break
        if clash:
            continue
        kept.append(
            pretty_midi.Note(velocity=vel, pitch=pitch, start=start, end=end)
        )
    return [n for n in kept if n.end > n.start + 1e-3]
