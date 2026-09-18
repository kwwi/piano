"""Tests for MIDI → MusicXML (music21 + optional MuseScore CLI)."""
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
    out = to_musicxml.midi_to_musicxml(midi, tmp_path / "scale.musicxml")
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert "<pitch>" in text
    assert text.count("<note") >= 8
    assert "<step>C</step>" in text


def test_key_inference_runs(tmp_path):
    midi = _c_major_scale_midi(tmp_path / "scale2.mid")
    out = to_musicxml.midi_to_musicxml(
        midi, tmp_path / "scale2.musicxml", infer_key=True, prefer_musescore=False
    )
    text = out.read_text(encoding="utf-8")
    assert "<key>" in text


def test_musescore_cli_preferred(tmp_path, monkeypatch):
    midi = _c_major_scale_midi(tmp_path / "scale.mid")
    fake_bin = tmp_path / "mscore"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def _fake_cli(midi_path, out_xml, bin_path):
        assert bin_path == fake_bin
        out_xml.write_text(
            '<?xml version="1.0"?><score-partwise version="3.1">'
            "<part-list><score-part id=\"P1\">"
            "<part-name>Piano</part-name></score-part></part-list>"
            '<part id="P1"><measure number="1">'
            "<note><pitch><step>C</step><octave>4</octave></pitch>"
            "<duration>1</duration><type>quarter</type></note>"
            "</measure></part></score-partwise>",
            encoding="utf-8",
        )
        return out_xml

    monkeypatch.setattr(to_musicxml, "find_musescore_bin", lambda: fake_bin)
    monkeypatch.setattr(to_musicxml, "_midi_to_musicxml_musescore", _fake_cli)
    out = to_musicxml.midi_to_musicxml(midi, tmp_path / "via_ms.musicxml")
    assert "<score-partwise" in out.read_text(encoding="utf-8")
    assert "Piano" in out.read_text(encoding="utf-8")


def test_musescore_failure_falls_back_to_music21(tmp_path, monkeypatch):
    midi = _c_major_scale_midi(tmp_path / "scale.mid")
    fake_bin = tmp_path / "mscore"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def _boom(*_a, **_k):
        raise to_musicxml.MusicXmlError("mscore exploded")

    monkeypatch.setattr(to_musicxml, "find_musescore_bin", lambda: fake_bin)
    monkeypatch.setattr(to_musicxml, "_midi_to_musicxml_musescore", _boom)
    out = to_musicxml.midi_to_musicxml(midi, tmp_path / "fallback.musicxml")
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert text.count("<note") >= 8


def test_find_musescore_respects_env(tmp_path, monkeypatch):
    fake = tmp_path / "custom-mscore"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("MUSESCORE_PATH", str(fake))
    assert to_musicxml.find_musescore_bin() == fake


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

    out = to_musicxml.midi_to_musicxml(
        mid, tmp_path / "kit.musicxml", prefer_musescore=False
    )
    text = out.read_text(encoding="utf-8")
    assert "<score-partwise" in text
    assert text.count("<note") >= 8
