"""Tests for audio chunking and MIDI timeline merge."""
from pathlib import Path

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from app.pipeline.audio_split import audio_duration_sec, split_wav
from app.pipeline.midi_merge import merge_chunk_midis


def _write_tone(path: Path, *, seconds: float, sr: int = 16000) -> Path:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(str(path), audio, sr)
    return path


def test_split_short_audio_single_chunk(tmp_path: Path):
    wav = _write_tone(tmp_path / "short.wav", seconds=5)
    chunks = split_wav(wav, tmp_path / "out", chunk_sec=30, overlap_sec=1)
    assert len(chunks) == 1
    assert chunks[0].start_sec == 0.0
    assert audio_duration_sec(chunks[0].path) == pytest.approx(5.0, abs=0.05)


def test_split_long_audio_multiple_chunks(tmp_path: Path):
    wav = _write_tone(tmp_path / "long.wav", seconds=65)
    chunks = split_wav(wav, tmp_path / "out", chunk_sec=30, overlap_sec=1)
    assert len(chunks) >= 3
    assert chunks[0].start_sec == pytest.approx(0.0, abs=0.02)
    assert chunks[1].start_sec == pytest.approx(29.0, abs=0.05)
    # Last chunk reaches near the end.
    last = chunks[-1]
    assert last.start_sec + last.duration_sec == pytest.approx(65.0, abs=0.1)


def test_merge_midis_shifts_and_dedupes_overlap(tmp_path: Path):
    def _seg(name: str, start: float, pitch: int) -> Path:
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0, name="Pno0")
        inst.notes.append(pretty_midi.Note(90, pitch, start, start + 0.4))
        # Note inside overlap window for second segment (should be skipped).
        if name == "b":
            inst.notes.append(pretty_midi.Note(90, 50, 0.2, 0.5))
        pm.instruments.append(inst)
        path = tmp_path / f"{name}.mid"
        pm.write(str(path))
        return path

    a = _seg("a", 0.0, 60)
    b = _seg("b", 1.0, 64)  # relative; absolute = 30 + 1
    out = merge_chunk_midis(
        [(a, 0.0), (b, 30.0)],
        tmp_path / "merged.mid",
        overlap_sec=1.0,
    )
    pm = pretty_midi.PrettyMIDI(str(out))
    assert len(pm.instruments) == 1
    starts = sorted(n.start for n in pm.instruments[0].notes)
    pitches = sorted(n.pitch for n in pm.instruments[0].notes)
    # Overlap note at relative 0.2 on segment b is dropped.
    assert pitches == [60, 64]
    assert starts[0] == pytest.approx(0.0, abs=0.01)
    assert starts[1] == pytest.approx(31.0, abs=0.01)
