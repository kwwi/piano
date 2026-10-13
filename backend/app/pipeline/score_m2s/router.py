"""Route MIDI tracks to MIDI2ScoreTransformer or music21 rules, then merge.

Score modes (``SCORE_MODES`` in config):

* ``per_track``  — each non-drum track → its own M2S grand-staff part; drums → rules.
* ``piano_only`` — GM piano tracks (program 0–7) → M2S; everything else → rules.
* ``reduce_all`` — all non-drum tracks merged → one M2S piano score; drums dropped.

``arranged_piano`` (``arrange=piano`` output) is always engraved by M2S as one part.

In ``per_track`` / ``piano_only`` the output has exactly one part per MIDI
instrument, in order, so part-index filtering of the full score stays valid.
Per-track results are cached by MIDI content under ``<cache_dir>``.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...config import SCORE_MODES
from ...logging_zh import get_logger
from ..to_musicxml import midi_to_musicxml_rule
from . import client as m2s_client
from .musicxml_merge import empty_part_score, merge_musicxml

log = get_logger("piano.score")

_PIANO_PROGRAMS = range(0, 8)


class ScoreRouteError(RuntimeError):
    pass


def normalize_score_mode(mode: Optional[str]) -> str:
    from ...config import SCORE_MODE_DEFAULT

    val = (mode or "").strip().lower().replace("-", "_")
    if not val:
        return SCORE_MODE_DEFAULT
    aliases = {
        "track": "per_track",
        "tracks": "per_track",
        "piano": "piano_only",
        "reduce": "reduce_all",
        "reduction": "reduce_all",
    }
    val = aliases.get(val, val)
    if val not in SCORE_MODES:
        raise ScoreRouteError(
            f"invalid score_mode={mode!r} (use {' | '.join(SCORE_MODES)})"
        )
    return val


def mode_supports_part_filter(mode: str) -> bool:
    """True when the full score has one part per source track (in order)."""
    return mode in ("per_track", "piano_only")


@dataclass
class _Track:
    index: int
    name: str
    program: int
    is_drum: bool
    note_count: int


def _tempo(pm) -> float:
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            return float(tempos[0])
    except Exception:
        pass
    return 120.0


def _write_single(pm, insts, out_mid: Path, *, name: str, program: int = 0, is_drum: bool = False) -> Path:
    import pretty_midi

    out = pretty_midi.PrettyMIDI(initial_tempo=_tempo(pm))
    merged = pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)
    for inst in insts:
        for n in inst.notes:
            merged.notes.append(
                pretty_midi.Note(velocity=n.velocity, pitch=n.pitch, start=n.start, end=n.end)
            )
    merged.notes.sort(key=lambda n: (n.start, n.pitch))
    out.instruments.append(merged)
    out_mid.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(out_mid))
    return out_mid


def reshape_midi_for_score_mode(
    midi_path: str | Path,
    out_midi: str | Path,
    *,
    score_mode: Optional[str] = None,
) -> Path:
    """Rewrite MIDI so audition / export matches the chosen score mode.

    * ``per_track`` — copy unchanged (multi-track).
    * ``piano_only`` — keep GM piano tracks (program 0–7) only; drop drums / others.
    * ``reduce_all`` — merge all non-drum tracks into one Piano part; drop drums.
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise ScoreRouteError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    mode = normalize_score_mode(score_mode)
    if not midi_path.is_file():
        raise ScoreRouteError(f"MIDI not found: {midi_path}")

    if mode == "per_track":
        out_midi.parent.mkdir(parents=True, exist_ok=True)
        if midi_path.resolve() != out_midi.resolve():
            shutil.copyfile(midi_path, out_midi)
        return out_midi

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    if mode == "piano_only":
        keep = [
            inst
            for inst in pm.instruments
            if not inst.is_drum and int(inst.program) in _PIANO_PROGRAMS and inst.notes
        ]
        if not keep:
            raise ScoreRouteError("仅钢琴：选中内容里没有钢琴类音轨可试听")
        out = pretty_midi.PrettyMIDI(initial_tempo=_tempo(pm))
        for inst in keep:
            clone = pretty_midi.Instrument(
                program=inst.program,
                is_drum=False,
                name=(inst.name or "").strip() or "Piano",
            )
            for n in inst.notes:
                clone.notes.append(
                    pretty_midi.Note(n.velocity, n.pitch, n.start, n.end)
                )
            out.instruments.append(clone)
        out_midi.parent.mkdir(parents=True, exist_ok=True)
        out.write(str(out_midi))
        return out_midi

    # reduce_all
    pitched = [inst for inst in pm.instruments if not inst.is_drum and inst.notes]
    if not pitched:
        raise ScoreRouteError("合并缩谱：选中内容里没有可合并的非鼓音轨")
    return _write_single(pm, pitched, out_midi, name="Piano", program=0, is_drum=False)


def _digest(path: Path, tag: str) -> str:
    h = hashlib.sha1(tag.encode("utf-8"))
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _cached(cache_dir: Path, midi: Path, engine: str, name: str, build) -> Path:
    """Run ``build(midi, out)`` once per (engine, name, MIDI bytes)."""
    out = cache_dir / f"{engine}_{_digest(midi, engine + '|' + name)}.musicxml"
    if out.is_file() and out.stat().st_size > 0:
        return out
    build(midi, out)
    return out


def _via_m2s(cache_dir: Path, midi: Path, name: str) -> Path:
    return _cached(
        cache_dir,
        midi,
        "m2s",
        name,
        lambda m, o: m2s_client.midi_to_musicxml_m2s(m, o, name=name),
    )


def _via_rule(cache_dir: Path, midi: Path, name: str) -> Path:
    return _cached(
        cache_dir,
        midi,
        "rule",
        name,
        lambda m, o: midi_to_musicxml_rule(m, o),
    )


def build_score_xml_from_midi(
    midi_path: str | Path,
    out_xml: str | Path,
    *,
    score_mode: Optional[str] = None,
    arranged_piano: bool = False,
    cache_dir: str | Path | None = None,
) -> Path:
    """Engrave ``midi_path`` into ``out_xml`` according to ``score_mode``."""
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise ScoreRouteError("pretty_midi is required") from exc

    midi_path = Path(midi_path)
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    mode = normalize_score_mode(score_mode)
    cache = Path(cache_dir) if cache_dir else out_xml.parent / "score_parts"
    cache.mkdir(parents=True, exist_ok=True)
    work = cache / "midi"
    work.mkdir(parents=True, exist_ok=True)

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    tracks = [
        _Track(
            index=i,
            name=(inst.name or "").strip() or f"Track{i}",
            program=int(inst.program),
            is_drum=bool(inst.is_drum),
            note_count=len(inst.notes),
        )
        for i, inst in enumerate(pm.instruments)
    ]
    pitched = [t for t in tracks if not t.is_drum and t.note_count > 0]

    if arranged_piano:
        if not pitched:
            raise ScoreRouteError("arranged piano MIDI has no notes")
        single = _write_single(
            pm, [pm.instruments[t.index] for t in pitched], work / "arranged_piano.mid", name="Piano"
        )
        log.info("谱面生成：钢琴编配 → M2S")
        return _publish(_via_m2s(cache, single, "Piano"), out_xml)

    if mode == "reduce_all":
        if not pitched:
            raise ScoreRouteError("reduce_all: no pitched tracks to engrave")
        single = _write_single(
            pm, [pm.instruments[t.index] for t in pitched], work / "reduce_all.mid", name="Piano"
        )
        log.info("谱面生成：合并缩谱（%d 轨 → 1 钢琴谱）", len(pitched))
        return _publish(_via_m2s(cache, single, "Piano"), out_xml)

    if not tracks:
        raise ScoreRouteError("MIDI has no tracks")

    part_files: list[Path] = []
    names: list[str] = []
    for t in tracks:
        inst = pm.instruments[t.index]
        names.append(t.name)
        if t.note_count == 0:
            part_files.append(empty_part_score(t.name, cache / f"empty_{t.index:02d}.musicxml"))
            continue
        tmp = work / f"t{t.index:02d}.mid"
        _write_single(pm, [inst], tmp, name=t.name, program=t.program, is_drum=t.is_drum)
        use_m2s = not t.is_drum and (mode == "per_track" or t.program in _PIANO_PROGRAMS)
        if use_m2s:
            part_files.append(_via_m2s(cache, tmp, t.name))
        else:
            part_files.append(_via_rule(cache, tmp, t.name))
        log.info(
            "谱面生成（%s）：轨 %d %s → %s",
            mode,
            t.index,
            t.name,
            "M2S" if use_m2s else "规则",
        )

    if len(part_files) == 1:
        return _publish(part_files[0], out_xml)
    return merge_musicxml(part_files, out_xml, part_names=names)


def _publish(src: Path, out_xml: Path) -> Path:
    tmp = out_xml.with_name(out_xml.name + ".part")
    shutil.copyfile(src, tmp)
    tmp.replace(out_xml)
    return out_xml


def build_score_xml(
    job_dir: str | Path,
    selection,
    arrange: Optional[str],
    score_mode: Optional[str],
    out_xml: str | Path,
    *,
    piano_style: Optional[str] = None,
    piano_auto_chords: Optional[bool] = None,
) -> Path:
    """Build MusicXML for a job selection (``selection=None`` → all source tracks)."""
    from ..track_derive import assemble_selection_midi
    from ..tracks import resolve_score_midi

    job_dir = Path(job_dir)
    exports = job_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    cache_dir = job_dir / "score_parts"

    if arrange == "piano":
        from ..arrange_piano import arrange_for_piano

        sel_key = selection.cache_key if selection is not None else "all"
        piano_mid = exports / f"score_piano_{sel_key}.mid"
        if not piano_mid.is_file():
            arrange_for_piano(
                job_dir,
                selection,
                piano_mid,
                style=piano_style,
                auto_chords=piano_auto_chords,
            )
        return build_score_xml_from_midi(
            piano_mid, out_xml, score_mode=score_mode, arranged_piano=True, cache_dir=cache_dir
        )

    if selection is None:
        midi = resolve_score_midi(job_dir)
    else:
        midi = exports / f"sel_{selection.cache_key}.mid"
        if not midi.is_file():
            assemble_selection_midi(job_dir, selection, midi)
    return build_score_xml_from_midi(
        midi, out_xml, score_mode=score_mode, cache_dir=cache_dir
    )
