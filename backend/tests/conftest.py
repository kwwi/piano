import math
import struct
import wave
from pathlib import Path

import pytest


def write_sine_wav(path: Path, freq: float = 440.0, seconds: float = 2.0,
                   sample_rate: int = 44100, amplitude: float = 0.4) -> Path:
    """Write a mono 16-bit PCM sine tone (stdlib only)."""
    n = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            sample = amplitude * math.sin(2 * math.pi * freq * i / sample_rate)
            frames += struct.pack("<h", int(sample * 32767))
        w.writeframes(bytes(frames))
    return path


@pytest.fixture
def sine_wav(tmp_path) -> Path:
    return write_sine_wav(tmp_path / "tone.wav")


FAKE_M2S_WORKER = Path(__file__).with_name("fake_m2s_worker.py")


def make_fake_m2s_client(tmp_path: Path, mode: str = "ok", **kwargs):
    import sys

    from app.pipeline.score_m2s.client import M2SClient

    log = tmp_path / "fake_m2s_requests.jsonl"
    client = M2SClient(
        [sys.executable, str(FAKE_M2S_WORKER)],
        env={
            "FAKE_M2S_MODE": mode,
            "FAKE_M2S_LOG": str(log),
            "FAKE_M2S_MARKER": str(tmp_path / "fake_m2s_crashed"),
        },
        timeout=kwargs.pop("timeout", 30),
        startup_timeout=kwargs.pop("startup_timeout", 30),
    )
    client.request_log = log
    return client


@pytest.fixture
def fake_m2s(tmp_path):
    """Install a fake MIDI2ScoreTransformer worker as the shared client."""
    from app.pipeline.score_m2s import client as m2s_client

    client = make_fake_m2s_client(tmp_path)
    m2s_client.set_client(client)
    yield client
    m2s_client.set_client(None)
