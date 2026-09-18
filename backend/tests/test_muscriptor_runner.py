"""Unit tests for MuScriptor runner (mocked — no weight download)."""
from pathlib import Path

import pretty_midi
import pytest


def test_muscriptor_available_reports_bool():
    from app.pipeline import muscriptor_runner

    assert isinstance(muscriptor_runner.muscriptor_available(), bool)


def test_run_muscriptor_writes_midi(tmp_path, monkeypatch):
    from app.pipeline import muscriptor_runner

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")  # content unused — model is mocked

    class _FakeModel:
        def transcribe_to_midi(self, audio):
            pm = pretty_midi.PrettyMIDI(initial_tempo=120)
            inst = pretty_midi.Instrument(program=0, name="piano")
            inst.notes.append(pretty_midi.Note(80, 60, 0.0, 0.5))
            pm.instruments.append(inst)
            import io

            buf = io.BytesIO()
            pm.write(buf)
            return buf.getvalue()

    monkeypatch.setattr(muscriptor_runner, "muscriptor_available", lambda: True)
    monkeypatch.setattr(muscriptor_runner, "_get_model", lambda: _FakeModel())
    muscriptor_runner._model_cache.clear()

    out = tmp_path / "out.mid"
    path = muscriptor_runner.run_muscriptor(wav, out)
    assert path.is_file()
    pm = pretty_midi.PrettyMIDI(str(path))
    assert pm.instruments
    assert pm.instruments[0].notes


def test_run_muscriptor_missing_raises(monkeypatch, tmp_path):
    from app.pipeline import muscriptor_runner

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")

    def _boom():
        raise muscriptor_runner.MuscriptorNotProvisioned("muscriptor is not installed")

    monkeypatch.setattr(muscriptor_runner, "_get_model", _boom)
    with pytest.raises(muscriptor_runner.MuscriptorNotProvisioned, match="not installed"):
        muscriptor_runner.run_muscriptor(wav, tmp_path / "out.mid")


def test_transcribe_routes_to_muscriptor(tmp_path, monkeypatch):
    from app.pipeline import transcribe

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    out = tmp_path / "o.mid"
    called = {}

    def _fake(audio, midi):
        Path(midi).write_bytes(b"MThd")
        called["ok"] = True
        return Path(midi)

    monkeypatch.setattr(transcribe, "_transcribe_muscriptor", _fake)
    transcribe.transcribe_to_midi(wav, out, model="muscriptor", split_audio=True)
    assert called.get("ok")
    assert out.is_file()
