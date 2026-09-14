"""Tests the MIDI -> MusicXML stage (music21). Runs for real (music21 is light)."""
from pathlib import Path

import pretty_midi

from app.pipeline.to_musicxml import midi_to_musicxml


def _c_major_scale_midi(path: Path) -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    start = 0.0
    for pitch in [60, 62, 64, 65, 67, 69, 71, 72]:  # C4..C5
        inst.notes.append(
            pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=start + 0.5)
        )
        start += 0.5
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


def test_midi_to_musicxml_produces_notes(tmp_path):
    midi = _c_major_scale_midi(tmp_path / "scale.mid")
    out = midi_to_musicxml(midi, tmp_path / "scale.musicxml")
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert "<pitch>" in text
    assert text.count("<note") >= 8
    assert "<step>C</step>" in text


def test_key_inference_runs(tmp_path):
    midi = _c_major_scale_midi(tmp_path / "scale2.mid")
    out = midi_to_musicxml(midi, tmp_path / "scale2.musicxml", infer_key=True)
    text = out.read_text(encoding="utf-8")
    assert "<key>" in text
