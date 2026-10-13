"""MT3 transcription via ``mt3-infer`` (PyTorch MT3 family).

Uses community PyTorch ports (MT3-PyTorch / MR-MT3 / YourMT3) instead of the
heavy Magenta JAX/T5X Colab stack. Checkpoints auto-download on first use
unless ``MT3_CHECKPOINT`` points at a local path.
"""
from __future__ import annotations

from pathlib import Path

from ..config import (
    MT3_CHECKPOINT,
    MT3_DEVICE,
    MT3_INFER_MODEL,
    MT3_SAMPLE_RATE,
)
from ..logging_zh import get_logger

log = get_logger("piano.mt3")

_model_cache: dict[tuple[str, str, str | None], object] = {}
_compat_patched = False


class Mt3NotProvisioned(RuntimeError):
    pass


def mt3_infer_available() -> bool:
    try:
        import mt3_infer  # noqa: F401

        return True
    except Exception:
        return False


def _ensure_transformers_compat() -> None:
    """Bridge mt3-infer's vendored T5 stacks to current ``transformers`` APIs.

    mt3-infer calls ``T5Block(..., past_key_values=...)`` (plural) and may rely on
    ``PreTrainedModel.get_extended_attention_mask``. Transformers 4.x uses
    ``past_key_value`` (singular); 5.x removed the mask helpers entirely.
    """
    global _compat_patched
    if _compat_patched:
        return

    import inspect

    try:
        import transformers
        from transformers.models.t5.modeling_t5 import T5Block
    except Exception as exc:  # pragma: no cover
        raise Mt3NotProvisioned(
            "transformers is required for mt3-infer "
            "(pin transformers>=4.35,<4.44 per requirements-ml.txt)"
        ) from exc

    ver = getattr(transformers, "__version__", "?")
    # Soft-check: warn loudly if on v5 where mask helpers disappeared.
    try:
        from transformers import PreTrainedModel

        if not hasattr(PreTrainedModel, "get_extended_attention_mask"):
            raise Mt3NotProvisioned(
                f"transformers {ver} is incompatible with mt3-infer "
                "(missing PreTrainedModel.get_extended_attention_mask). "
                "Install transformers>=4.35,<4.44 then restart the backend."
            )
    except Mt3NotProvisioned:
        raise
    except Exception:
        pass

    if getattr(T5Block.forward, "_piano_mt3_patched", False):
        _compat_patched = True
        return

    orig = T5Block.forward
    params = inspect.signature(orig).parameters

    def _forward(self, *args, **kwargs):
        # mt3-infer passes plural; HF T5Block expects singular.
        if "past_key_values" in kwargs and "past_key_value" not in kwargs:
            kwargs["past_key_value"] = kwargs.pop("past_key_values")
        elif "past_key_values" in kwargs and "past_key_value" in kwargs:
            kwargs.pop("past_key_values")
        # With use_cache=True, T5Block returns (hidden, present_kv, position_bias, …)
        # but mt3-infer unpacks as if index 1 were position_bias (4.44+ layout).
        # Disable cache so the tuple is (hidden, position_bias, …).
        if "use_cache" in params:
            kwargs["use_cache"] = False
        filtered = {k: v for k, v in kwargs.items() if k in params}
        return orig(self, *args, **filtered)

    _forward._piano_mt3_patched = True  # type: ignore[attr-defined]
    T5Block.forward = _forward  # type: ignore[method-assign]
    _compat_patched = True
    log.info("已应用 mt3-infer / transformers(%s) T5Block 兼容补丁", ver)


def _load_audio_mono_16k(audio_path: Path) -> tuple:
    import numpy as np

    try:
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise Mt3NotProvisioned("soundfile is required for MT3 audio I/O") from exc

    audio, sr = sf.read(str(audio_path), always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1).astype(np.float32)

    target = int(MT3_SAMPLE_RATE)
    if int(sr) != target:
        try:
            import librosa
        except Exception as exc:  # pragma: no cover
            raise Mt3NotProvisioned(
                "librosa is required to resample audio for MT3 (16 kHz)"
            ) from exc
        audio = librosa.resample(audio, orig_sr=int(sr), target_sr=target)
        audio = np.asarray(audio, dtype=np.float32)
        sr = target
    return audio, int(sr)


def _get_model():
    try:
        from mt3_infer import load_model
    except Exception as exc:
        raise Mt3NotProvisioned(
            "mt3-infer is not installed. "
            "pip install -r requirements-ml.txt (includes mt3-infer), "
            "or use model=basic_pitch."
        ) from exc

    _ensure_transformers_compat()

    model_name = (MT3_INFER_MODEL or "mt3_pytorch").strip()
    device = (MT3_DEVICE or "auto").strip()
    checkpoint = (MT3_CHECKPOINT or "").strip() or None
    key = (model_name, device, checkpoint)
    if key not in _model_cache:
        log.info(
            "加载 MT3 模型：variant=%s device=%s checkpoint=%s",
            model_name,
            device,
            checkpoint or "(auto-download)",
        )
        _model_cache[key] = load_model(
            model_name,
            checkpoint_path=checkpoint,
            device=device,
            cache=True,
            auto_download=True,
        )
    return _model_cache[key]


def run_mt3(audio_path: Path, out_midi: Path) -> Path:
    """Transcribe ``audio_path`` with mt3-infer and write a Standard MIDI File."""
    audio_path = Path(audio_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)

    if not audio_path.is_file():
        raise Mt3NotProvisioned(f"audio not found: {audio_path}")

    audio, sr = _load_audio_mono_16k(audio_path)
    model = _get_model()
    try:
        midi = model.transcribe(audio, sr=sr)
    except Exception as exc:
        raise Mt3NotProvisioned(f"mt3-infer transcription failed: {exc}") from exc

    # mt3-infer returns mido.MidiFile
    save = getattr(midi, "save", None)
    if callable(save):
        save(str(out_midi))
    else:  # pragma: no cover - unexpected return type
        raise Mt3NotProvisioned(
            f"unexpected MT3 return type: {type(midi)!r} (expected mido.MidiFile)"
        )

    if not out_midi.is_file() or out_midi.stat().st_size == 0:
        raise Mt3NotProvisioned("MT3 did not write a MIDI file")
    log.info(
        "MT3 完成：%s → %s（%.1f KB）",
        audio_path.name,
        out_midi.name,
        out_midi.stat().st_size / 1024,
    )
    return out_midi
