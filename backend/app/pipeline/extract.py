"""Audio extraction / normalisation via ffmpeg.

Works for both plain audio files and video containers (the audio track is
demuxed and decoded). Output is a standard PCM WAV that downstream models
(Demucs, Basic Pitch, MT3) can consume directly.

ffmpeg is used under its LGPL build for commercial-friendly licensing.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ExtractionError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_audio(
    input_path: str | Path,
    out_wav: str | Path,
    sample_rate: int = 44100,
    mono: bool = False,
) -> Path:
    """Decode the audio track of ``input_path`` into a WAV at ``out_wav``.

    Returns the output path. Raises :class:`ExtractionError` on failure.
    """
    if not ffmpeg_available():
        raise ExtractionError("ffmpeg not found on PATH")

    input_path = Path(input_path)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",  # drop any video stream
        "-ac",
        "1" if mono else "2",
        "-ar",
        str(sample_rate),
        "-acodec",
        "pcm_s16le",
        str(out_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ExtractionError(f"ffmpeg failed: {proc.stderr[-500:]}")
    if not out_wav.exists() or out_wav.stat().st_size == 0:
        raise ExtractionError("ffmpeg produced no output")
    return out_wav
