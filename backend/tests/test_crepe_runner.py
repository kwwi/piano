"""Unit tests for torchcrepe → MIDI runner (mocked — no model download)."""
from pathlib import Path

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from app.pipeline import crepe_runner
from app.pipeline.lead_sheet import build_lead_sheet


def _tone_wav(path: Path, *, seconds: float = 1.0, freq: float = 440.0, sr: int = 16000) -> Path:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    audio = (0.25 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), audio, sr)
    return path


def test_crepe_available_reports_bool():
    assert isinstance(crepe_runner.crepe_available(), bool)


def test_run_crepe_writes_melody_midi(tmp_path, monkeypatch):
    wav = _tone_wav(tmp_path / "a.wav", seconds=0.5, freq=440.0)

    class _FakeTensor:
        def __init__(self, arr):
            self._arr = np.asarray(arr, dtype=np.float32)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

        def reshape(self, *args):
            return self._arr.reshape(*args)

    def _fake_predict(audio, sr, hop_length=160, return_periodicity=False, **kwargs):
        # ~0.5s @ hop 160 → ~50 frames of A4 with high periodicity.
        n = max(8, int(0.5 * sr / hop_length))
        pitch = np.full(n, 440.0, dtype=np.float32)
        peri = np.full(n, 0.9, dtype=np.float32)
        if return_periodicity:
            return _FakeTensor(pitch), _FakeTensor(peri)
        return _FakeTensor(pitch)

    import types
    import sys

    fake_mod = types.ModuleType("torchcrepe")
    fake_mod.predict = _fake_predict
    monkeypatch.setitem(sys.modules, "torchcrepe", fake_mod)
    monkeypatch.setattr(crepe_runner, "crepe_available", lambda: True)
    monkeypatch.setattr(
        crepe_runner,
        "_resolve_device",
        lambda requested: "cpu",
    )

    # torch.from_numpy path still needs real torch if imported inside run_crepe.
    out = tmp_path / "out.mid"
    path = crepe_runner.run_crepe(wav, out)
    assert path.is_file()
    pm = pretty_midi.PrettyMIDI(str(path))
    assert len(pm.instruments) == 1
    assert pm.instruments[0].name == "Melody"
    assert pm.instruments[0].notes
    # A4 ≈ MIDI 69
    assert abs(pm.instruments[0].notes[0].pitch - 69) <= 1


def test_lead_sheet_accepts_external_melody(tmp_path: Path):
    # Harmony pad MIDI
    harm = pretty_midi.PrettyMIDI(initial_tempo=120)
    pad = pretty_midi.Instrument(program=48, name="pad")
    for i, chord in enumerate(([60, 64, 67], [62, 65, 69])):
        for p in chord:
            pad.notes.append(pretty_midi.Note(70, p, i * 0.5, i * 0.5 + 0.45))
    harm.instruments.append(pad)
    harm_path = tmp_path / "harm.mid"
    harm.write(str(harm_path))

    # External CREPE-like melody
    mel = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Melody")
    inst.notes.append(pretty_midi.Note(90, 72, 0.0, 0.45))
    inst.notes.append(pretty_midi.Note(90, 74, 0.5, 0.95))
    mel.instruments.append(inst)
    mel_path = tmp_path / "crepe.mid"
    mel.write(str(mel_path))

    out = build_lead_sheet(
        harm_path,
        tmp_path / "lead.mid",
        melody_midi=mel_path,
        chords_json=tmp_path / "chords.json",
    )
    pm = pretty_midi.PrettyMIDI(str(out))
    names = [i.name for i in pm.instruments]
    assert names == ["Melody", "Chords"]
    assert [n.pitch for n in pm.instruments[0].notes] == [72, 74]
