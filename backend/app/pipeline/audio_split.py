"""Split a long WAV into fixed-length chunks for segment-wise transcription."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class AudioSplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    start_sec: float
    duration_sec: float
    index: int


def audio_duration_sec(wav_path: str | Path) -> float:
    """Return duration in seconds (soundfile, fallback wave)."""
    wav_path = Path(wav_path)
    try:
        import soundfile as sf

        info = sf.info(str(wav_path))
        if info.frames and info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    try:
        import wave

        with wave.open(str(wav_path), "rb") as wf:
            return float(wf.getnframes()) / float(wf.getframerate())
    except Exception as exc:
        raise AudioSplitError(f"cannot read duration: {exc}") from exc


def split_wav(
    wav_path: str | Path,
    out_dir: str | Path,
    *,
    chunk_sec: float = 30.0,
    overlap_sec: float = 1.0,
    min_chunk_sec: float = 2.0,
) -> list[AudioChunk]:
    """Split ``wav_path`` into overlapping WAV chunks under ``out_dir``.

    If the file is shorter than ``chunk_sec``, returns a single chunk that is a
    copy/link of the original (no re-encode).
    """
    import shutil

    import numpy as np

    try:
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise AudioSplitError("soundfile is required for audio splitting") from exc

    wav_path = Path(wav_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not wav_path.is_file():
        raise AudioSplitError(f"audio not found: {wav_path}")

    chunk_sec = float(chunk_sec)
    overlap_sec = max(0.0, float(overlap_sec))
    if chunk_sec <= 0:
        raise AudioSplitError("chunk_sec must be > 0")
    if overlap_sec >= chunk_sec:
        raise AudioSplitError("overlap_sec must be < chunk_sec")

    duration = audio_duration_sec(wav_path)
    if duration <= chunk_sec + 1e-3:
        dest = out_dir / "chunk_000.wav"
        if dest.resolve() != wav_path.resolve():
            shutil.copyfile(wav_path, dest)
        return [
            AudioChunk(
                path=dest,
                start_sec=0.0,
                duration_sec=duration,
                index=0,
            )
        ]

    audio, sr = sf.read(str(wav_path), always_2d=True)
    audio = np.asarray(audio, dtype=np.float32)
    n = int(audio.shape[0])
    hop = max(1, int(round((chunk_sec - overlap_sec) * sr)))
    win = max(1, int(round(chunk_sec * sr)))
    min_samples = max(1, int(round(min_chunk_sec * sr)))

    chunks: list[AudioChunk] = []
    start = 0
    index = 0
    while start < n:
        end = min(n, start + win)
        # Drop a trailing stub that is too short (covered by previous overlap).
        if end - start < min_samples and chunks:
            break
        piece = audio[start:end]
        dest = out_dir / f"chunk_{index:03d}.wav"
        sf.write(str(dest), piece, sr)
        chunks.append(
            AudioChunk(
                path=dest,
                start_sec=start / float(sr),
                duration_sec=(end - start) / float(sr),
                index=index,
            )
        )
        index += 1
        if end >= n:
            break
        start += hop

    if not chunks:
        raise AudioSplitError("audio split produced no chunks")
    return chunks
