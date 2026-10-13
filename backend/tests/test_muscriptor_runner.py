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


def test_transcribe_muscriptor_failure_does_not_fallback(tmp_path, monkeypatch):
    """MuScriptor errors must surface to the client — never silently use MT3."""
    from app.pipeline import transcribe

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    out = tmp_path / "o.mid"
    mt3_called = {"ok": False}
    bp_called = {"ok": False}

    def _boom(_audio, _midi):
        raise RuntimeError("weights gated")

    def _mt3(_audio, _midi):
        mt3_called["ok"] = True
        Path(_midi).write_bytes(b"MThd")
        return Path(_midi)

    def _bp(_audio, _midi):
        bp_called["ok"] = True
        Path(_midi).write_bytes(b"MThd")
        return Path(_midi)

    monkeypatch.setattr(transcribe, "_transcribe_muscriptor", _boom)
    monkeypatch.setattr(transcribe, "mt3_available", lambda: True)
    monkeypatch.setattr(transcribe, "basic_pitch_available", lambda: True)
    monkeypatch.setattr(transcribe, "_transcribe_mt3", _mt3)
    monkeypatch.setattr(transcribe, "_transcribe_basic_pitch", _bp)

    with pytest.raises(transcribe.TranscriptionError, match="MuScriptor 暂时不可用"):
        transcribe.transcribe_to_midi(wav, out, model="muscriptor")
    assert not mt3_called["ok"]
    assert not bp_called["ok"]
    assert not out.is_file()
