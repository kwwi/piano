"""Audio -> MIDI transcription.

Engines:
  - **muscriptor** — multi-instrument full-mix via MuScriptor (default)
  - **mt3** — multi-instrument via ``mt3-infer``
  - **basic_pitch** — Spotify Basic Pitch (light / polyphonic)
  - **crepe** — torchcrepe monophonic F0 (best on Demucs vocals)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..config import DEFAULT_MODEL
from ..logging_zh import get_logger

log = get_logger("piano.transcribe")

ChunkProgressCB = Callable[[int, int], None]

# Engines that already segment internally (or must see the whole stem once).
_NO_EXTERNAL_SPLIT = frozenset({"crepe", "muscriptor"})


class TranscriptionError(RuntimeError):
    pass


def basic_pitch_available() -> bool:
    try:
        import basic_pitch  # noqa: F401

        return True
    except Exception:
        return False


def mt3_available() -> bool:
    try:
        from .mt3_runner import mt3_infer_available

        return mt3_infer_available()
    except Exception:
        return False


def crepe_available() -> bool:
    try:
        from .crepe_runner import crepe_available as _ok

        return _ok()
    except Exception:
        return False


def muscriptor_available() -> bool:
    try:
        from .muscriptor_runner import muscriptor_available as _ok

        return _ok()
    except Exception:
        return False


def transcribe_to_midi(
    audio_path: str | Path,
    out_midi: str | Path,
    model: str | None = None,
    *,
    split_audio: bool = False,
    split_seconds: float = 30.0,
    split_overlap: float = 1.0,
    chunks_dir: str | Path | None = None,
    on_chunk_progress: ChunkProgressCB | None = None,
) -> Path:
    audio_path = Path(audio_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    model = (model or DEFAULT_MODEL).strip().lower()

    # CREPE / MuScriptor: do not externally chunk (MuScriptor already uses 5s
    # windows; CREPE is whole-stem F0).
    if model in _NO_EXTERNAL_SPLIT:
        return _transcribe_one(audio_path, out_midi, model)

    if split_audio:
        return _transcribe_split(
            audio_path,
            out_midi,
            model=model,
            split_seconds=split_seconds,
            split_overlap=split_overlap,
            chunks_dir=chunks_dir,
            on_chunk_progress=on_chunk_progress,
        )

    return _transcribe_one(audio_path, out_midi, model)


def _transcribe_one(audio_path: Path, out_midi: Path, model: str) -> Path:
    if model == "muscriptor":
        try:
            return _transcribe_muscriptor(audio_path, out_midi)
        except Exception as exc:
            # Prefer MT3 as multi-instrument fallback, then Basic Pitch.
            if mt3_available():
                log.warning("MuScriptor 不可用，回退 MT3：%s", exc)
                try:
                    return _transcribe_mt3(audio_path, out_midi)
                except Exception as exc2:
                    log.warning("MT3 回退也失败：%s", exc2)
            if basic_pitch_available():
                log.warning("回退 Basic Pitch：%s", exc)
                return _transcribe_basic_pitch(audio_path, out_midi)
            raise

    if model == "crepe":
        try:
            return _transcribe_crepe(audio_path, out_midi)
        except Exception as exc:
            if basic_pitch_available():
                log.warning("CREPE 不可用，回退 Basic Pitch：%s", exc)
                return _transcribe_basic_pitch(audio_path, out_midi)
            raise

    if model == "mt3":
        try:
            return _transcribe_mt3(audio_path, out_midi)
        except Exception as exc:
            if not basic_pitch_available():
                raise
            log.warning("MT3 不可用，回退 Basic Pitch：%s", exc)
            return _transcribe_basic_pitch(audio_path, out_midi)

    if model == "basic_pitch":
        return _transcribe_basic_pitch(audio_path, out_midi)

    log.warning("未知转录模型 %r，使用 Basic Pitch", model)
    return _transcribe_basic_pitch(audio_path, out_midi)


def _transcribe_split(
    audio_path: Path,
    out_midi: Path,
    *,
    model: str,
    split_seconds: float,
    split_overlap: float,
    chunks_dir: str | Path | None,
    on_chunk_progress,
) -> Path:
    from .audio_split import AudioSplitError, audio_duration_sec, split_wav
    from .midi_merge import MidiMergeError, merge_chunk_midis

    duration = audio_duration_sec(audio_path)
    if duration <= float(split_seconds) + 0.05:
        log.info("音频 %.1fs ≤ 分段 %.1fs，跳过分割直接转录", duration, split_seconds)
        return _transcribe_one(audio_path, out_midi, model)

    work = Path(chunks_dir) if chunks_dir else out_midi.parent / "chunks"
    work.mkdir(parents=True, exist_ok=True)
    try:
        chunks = split_wav(
            audio_path,
            work / "wav",
            chunk_sec=split_seconds,
            overlap_sec=split_overlap,
        )
    except AudioSplitError as exc:
        raise TranscriptionError(str(exc)) from exc

    log.info(
        "音频分段：时长 %.1fs → %d 段（每段 %.1fs，重叠 %.1fs）",
        duration,
        len(chunks),
        split_seconds,
        split_overlap,
    )

    midi_dir = work / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)
    merged_inputs: list[tuple[Path, float]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        mid = midi_dir / f"chunk_{chunk.index:03d}.mid"
        log.info(
            "转录分段 %d/%d（起 %.1fs，长 %.1fs）…",
            i + 1,
            total,
            chunk.start_sec,
            chunk.duration_sec,
        )
        _transcribe_one(chunk.path, mid, model)
        merged_inputs.append((mid, chunk.start_sec))
        if on_chunk_progress is not None:
            on_chunk_progress(i + 1, total)

    try:
        merge_chunk_midis(
            merged_inputs,
            out_midi,
            overlap_sec=split_overlap,
        )
    except MidiMergeError as exc:
        raise TranscriptionError(str(exc)) from exc
    return out_midi


def _transcribe_basic_pitch(audio_path: Path, out_midi: Path) -> Path:
    if not basic_pitch_available():
        raise TranscriptionError("basic-pitch is not installed")

    from basic_pitch.inference import predict

    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH

        model_or_path = ICASSP_2022_MODEL_PATH
    except Exception:  # pragma: no cover - depends on backend availability
        model_or_path = None

    if model_or_path is not None:
        _model_output, midi_data, _note_events = predict(str(audio_path), model_or_path)
    else:
        _model_output, midi_data, _note_events = predict(str(audio_path))

    midi_data.write(str(out_midi))
    return out_midi


def _transcribe_mt3(audio_path: Path, out_midi: Path) -> Path:
    """Multi-instrument transcription via mt3-infer (PyTorch MT3 ports)."""
    from .mt3_runner import run_mt3

    return run_mt3(audio_path, out_midi)


def _transcribe_crepe(audio_path: Path, out_midi: Path) -> Path:
    """Monophonic vocal/melody transcription via torchcrepe."""
    from .crepe_runner import run_crepe

    return run_crepe(audio_path, out_midi)


def _transcribe_muscriptor(audio_path: Path, out_midi: Path) -> Path:
    """Multi-instrument full-mix transcription via MuScriptor."""
    from .muscriptor_runner import run_muscriptor

    return run_muscriptor(audio_path, out_midi)
