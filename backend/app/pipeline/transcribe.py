"""Audio -> MIDI transcription.

Default engine: Spotify **Basic Pitch** (Apache-2.0) — lightweight, instrument
agnostic, polyphonic, outputs a MIDI with pitch bends. Optional high-accuracy
engine: **MT3** (Magenta, Apache-2.0) via a pluggable hook.
"""
from __future__ import annotations

from pathlib import Path


class TranscriptionError(RuntimeError):
    pass


def basic_pitch_available() -> bool:
    try:
        import basic_pitch  # noqa: F401

        return True
    except Exception:
        return False


def transcribe_to_midi(
    audio_path: str | Path,
    out_midi: str | Path,
    model: str = "basic_pitch",
) -> Path:
    audio_path = Path(audio_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)

    if model == "mt3":
        return _transcribe_mt3(audio_path, out_midi)
    return _transcribe_basic_pitch(audio_path, out_midi)


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
    """High-accuracy MT3 transcription.

    MT3 requires a sizeable JAX/T5X runtime and checkpoints; it is wired here as
    an optional engine and expected to be provisioned in the production image.
    """
    try:
        from .mt3_runner import run_mt3  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise TranscriptionError(
            "MT3 engine not provisioned in this environment"
        ) from exc
    return run_mt3(audio_path, out_midi)
