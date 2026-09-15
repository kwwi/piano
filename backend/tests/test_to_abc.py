"""Unit tests for MIDI → ABC conversion (no ML deps)."""
from pathlib import Path

from music21 import key, meter, note, stream, tempo

from app.pipeline.to_abc import (
    _len_suffix,
    _pitch_to_abc,
    midi_to_abc,
)


def _write_toy_midi(path: Path) -> None:
    s = stream.Score()
    p = stream.Part()
    p.append(tempo.MetronomeMark(number=96))
    p.append(meter.TimeSignature("4/4"))
    p.append(key.Key("C"))
    # C4 quarter, D4 eighth, E4 eighth, F4 half | G4 dotted-quarter, A4 eighth, rest quarter
    for n, ql in [
        ("C4", 1.0),
        ("D4", 0.5),
        ("E4", 0.5),
        ("F4", 2.0),
        ("G4", 1.5),
        ("A4", 0.5),
    ]:
        p.append(note.Note(n, quarterLength=ql))
    p.append(note.Rest(quarterLength=1.0))
    # high / low octave checks
    p.append(note.Note("C5", quarterLength=1.0))
    p.append(note.Note("C3", quarterLength=1.0))
    p.append(note.Note("C6", quarterLength=1.0))
    p.append(note.Rest(quarterLength=1.0))
    s.insert(0, p)
    s.write("midi", fp=str(path))


def test_pitch_and_length_helpers():
    from music21 import pitch

    assert _pitch_to_abc(pitch.Pitch("C4")) == "C"
    assert _pitch_to_abc(pitch.Pitch("C5")) == "c"
    assert _pitch_to_abc(pitch.Pitch("C3")) == "C,"
    assert _pitch_to_abc(pitch.Pitch("C6")) == "c'"
    assert _pitch_to_abc(pitch.Pitch("F#4")) == "^F"
    assert _pitch_to_abc(pitch.Pitch("Bb4")) == "_B"

    assert _len_suffix(1.0, 1.0) == ""
    assert _len_suffix(0.5, 1.0) == "/2"
    assert _len_suffix(0.25, 1.0) == "/4"
    assert _len_suffix(2.0, 1.0) == "2"
    assert _len_suffix(1.5, 1.0) == "3/2"


def test_midi_to_abc_roundtrip(tmp_path: Path):
    mid = tmp_path / "toy.mid"
    abc_path = tmp_path / "toy.abc"
    _write_toy_midi(mid)
    midi_to_abc(mid, abc_path, title="Toy")
    text = abc_path.read_text(encoding="utf-8")
    assert text.startswith("X:1")
    assert "T:Toy" in text
    assert "M:4/4" in text
    assert "L:1/4" in text
    assert "K:C" in text
    assert "C" in text
    assert "c" in text  # C5
    assert "C," in text  # C3
    assert "c'" in text  # C6
    assert "|" in text
