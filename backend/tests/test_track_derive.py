"""Tests for per-track melody/chord derivation and selection tokens."""
from pathlib import Path

import pretty_midi
import pytest

from app.pipeline.track_derive import (
    assemble_selection_midi,
    ensure_track_chords,
    ensure_track_melody,
    parse_track_selection,
)
from app.pipeline.tracks import TrackError


def _poly_job(tmp_path: Path) -> Path:
    job = tmp_path / "job"
    job.mkdir()
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    lead = pretty_midi.Instrument(program=0, name="lead")
    for i, pitch in enumerate([72, 74, 76, 77]):
        lead.notes.append(pretty_midi.Note(90, pitch, i * 0.5, i * 0.5 + 0.45))
    pad = pretty_midi.Instrument(program=48, name="pad")
    for i, chord in enumerate(([60, 64, 67], [62, 65, 69], [64, 67, 71], [65, 69, 72])):
        for p in chord:
            pad.notes.append(pretty_midi.Note(70, p, i * 0.5, i * 0.5 + 0.48))
    pm.instruments.extend([lead, pad])
    mid = job / "transcription.mid"
    pm.write(str(mid))
    (job / "transcription_raw.mid").write_bytes(mid.read_bytes())
    return job


def test_parse_track_selection_mixed():
    sel = parse_track_selection("0,m0,c1,1", track_count=2)
    assert sel is not None
    assert sel.sources == [0, 1]
    assert sel.melodies == [0]
    assert sel.chords == [1]
    assert sel.tokens == ["0", "m0", "c1", "1"]
    assert sel.has_derived


def test_parse_full_sources_is_none():
    assert parse_track_selection("0,1", track_count=2) is None


def test_parse_invalid_token():
    with pytest.raises(TrackError, match="invalid"):
        parse_track_selection("melody", track_count=2)


def test_ensure_melody_and_chords(tmp_path: Path):
    job = _poly_job(tmp_path)
    mel = ensure_track_melody(job, 0)
    assert mel.is_file()
    pm = pretty_midi.PrettyMIDI(str(mel))
    assert pm.instruments
    assert pm.instruments[0].notes

    ch = ensure_track_chords(job, 1)
    assert ch.is_file()
    cpm = pretty_midi.PrettyMIDI(str(ch))
    assert cpm.instruments
    assert cpm.instruments[0].notes


def test_assemble_selection(tmp_path: Path):
    job = _poly_job(tmp_path)
    sel = parse_track_selection("m0,c1", track_count=2)
    assert sel is not None
    out = assemble_selection_midi(job, sel, job / "exports" / "out.mid")
    pm = pretty_midi.PrettyMIDI(str(out))
    assert len(pm.instruments) == 2
    names = [i.name for i in pm.instruments]
    assert any("Melody" in n for n in names)
    assert any("Chords" in n for n in names)
