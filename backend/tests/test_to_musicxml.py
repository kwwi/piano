"""Tests for rule-based MIDI → MusicXML (music21)."""
from pathlib import Path

import pretty_midi

from app.pipeline import to_musicxml


def _c_major_scale_midi(path: Path) -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    start = 0.0
    for pitch in [60, 62, 64, 65, 67, 69, 71, 72]:
        inst.notes.append(
            pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=start + 0.5)
        )
        start += 0.5
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


def test_midi_to_musicxml_produces_notes(tmp_path):
    midi = _c_major_scale_midi(tmp_path / "scale.mid")
    out = to_musicxml.midi_to_musicxml_rule(midi, tmp_path / "scale.musicxml")
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert "<pitch>" in text
    assert text.count("<note") >= 8
    assert "<step>C</step>" in text


def test_key_inference_runs(tmp_path):
    midi = _c_major_scale_midi(tmp_path / "scale2.mid")
    out = to_musicxml.midi_to_musicxml_rule(
        midi, tmp_path / "scale2.musicxml", infer_key=True
    )
    text = out.read_text(encoding="utf-8")
    assert "<key>" in text


def test_drum_kit_midi_exports_musicxml(tmp_path):
    """MuScriptor-style drum kits must not crash music21 MusicXML export."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="drums")
    # Varied GM percussion (kick/snare/hats/toms/crash) like MuScriptor output.
    for i, pitch in enumerate([36, 42, 38, 42, 43, 46, 49, 38] * 4):
        drums.notes.append(
            pretty_midi.Note(90, pitch, i * 0.25, i * 0.25 + 0.12)
        )
    guitar = pretty_midi.Instrument(program=25, name="guitar")
    guitar.notes.append(pretty_midi.Note(80, 60, 0.0, 1.0))
    pm.instruments.extend([drums, guitar])
    mid = tmp_path / "kit.mid"
    pm.write(str(mid))

    out = to_musicxml.midi_to_musicxml_rule(mid, tmp_path / "kit.musicxml")
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert text.count("<note") >= 8
