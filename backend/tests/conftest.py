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
