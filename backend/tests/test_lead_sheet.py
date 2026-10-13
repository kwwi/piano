"""Tests for lead-sheet (melody + chords) arrangement."""
from pathlib import Path

import pretty_midi

from app.pipeline.lead_sheet import build_lead_sheet, write_lead_sheet_musicxml


def _poly_midi(path: Path) -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    # Melody-ish high line
    mel = pretty_midi.Instrument(program=0, name="lead")
    for i, pitch in enumerate([72, 74, 76, 77]):
        mel.notes.append(
            pretty_midi.Note(90, pitch, i * 0.5, i * 0.5 + 0.45)
        )
    # Harmony pads
    pad = pretty_midi.Instrument(program=48, name="pad")
    for i, chord in enumerate(
        ([60, 64, 67], [62, 65, 69], [64, 67, 71], [65, 69, 72])
    ):
        for p in chord:
            pad.notes.append(
                pretty_midi.Note(70, p, i * 0.5, i * 0.5 + 0.48)
            )
    pm.instruments.extend([mel, pad])
    pm.write(str(path))
    return path


def test_build_lead_sheet_two_tracks(tmp_path: Path):
    raw = _poly_midi(tmp_path / "raw.mid")
    out = build_lead_sheet(
        raw,
        tmp_path / "lead.mid",
        chords_json=tmp_path / "chords.json",
    )
    pm = pretty_midi.PrettyMIDI(str(out))
    names = [i.name for i in pm.instruments]
    assert names == ["Melody", "Chords"]
    assert pm.instruments[0].notes
    assert pm.instruments[1].notes
    text = (tmp_path / "chords.json").read_text(encoding="utf-8")
    assert "symbol" in text


def test_lead_sheet_musicxml(tmp_path: Path):
    raw = _poly_midi(tmp_path / "raw.mid")
    lead = build_lead_sheet(
        raw,
        tmp_path / "lead.mid",
        chords_json=tmp_path / "chords.json",
    )
    xml = write_lead_sheet_musicxml(
        lead,
        tmp_path / "lead.musicxml",
        chords_json=tmp_path / "chords.json",
    )
    body = xml.read_text(encoding="utf-8")
    assert "<score-partwise" in body
