"""Unit tests for mt3-infer runner (mocked — no checkpoint download)."""
from pathlib import Path

import numpy as np
import pytest

from app.pipeline import mt3_runner


class _FakeMidi:
    def __init__(self):
        self.saved = None

    def save(self, path: str) -> None:
        Path(path).write_bytes(b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x60" + b"\x00" * 8)
        self.saved = path


class _FakeModel:
    def transcribe(self, audio, sr=16000):
        assert isinstance(audio, np.ndarray)
        assert sr == 16000
        return _FakeMidi()


def test_mt3_infer_available_reports_bool():
    assert isinstance(mt3_runner.mt3_infer_available(), bool)


def test_run_mt3_writes_midi(tmp_path, monkeypatch):
    wav = tmp_path / "tone.wav"
    # 0.25s silence @ 44100 — runner resamples to 16k
    import soundfile as sf

    sf.write(str(wav), np.zeros(11025, dtype=np.float32), 44100)

    monkeypatch.setattr(mt3_runner, "_get_model", lambda: _FakeModel())
    mt3_runner._model_cache.clear()

    out = tmp_path / "out.mid"
    path = mt3_runner.run_mt3(wav, out)
    assert path == out
    assert out.is_file()
    assert out.read_bytes().startswith(b"MThd")


def test_run_mt3_model_failure(monkeypatch, tmp_path):
    import soundfile as sf

    wav = tmp_path / "tone.wav"
    sf.write(str(wav), np.zeros(1600, dtype=np.float32), 16000)

    def _boom():
        raise mt3_runner.Mt3NotProvisioned("mt3-infer is not installed")

    monkeypatch.setattr(mt3_runner, "_get_model", _boom)
    with pytest.raises(mt3_runner.Mt3NotProvisioned, match="not installed"):
        mt3_runner.run_mt3(wav, tmp_path / "out.mid")
