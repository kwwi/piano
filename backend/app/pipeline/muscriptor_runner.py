"""Multi-instrument transcription via MuScriptor (Kyutai × Mirelo).

MuScriptor is designed for **full mixes**: it detects instruments and writes
one MIDI track per part. Prefer the raw mix (skip Demucs) for best results.

Weights are CC BY-NC 4.0 — accept the Hugging Face license and set ``HF_TOKEN``
(or ``huggingface-cli login``) before first use.
"""
from __future__ import annotations

from pathlib import Path

from ..config import (
    MUSCRIPTOR_DEVICE,
    MUSCRIPTOR_QUANTIZE,
    MUSCRIPTOR_SIZE,
)
from ..logging_zh import get_logger

log = get_logger("piano.muscriptor")

_model_cache: dict[tuple[str, str], object] = {}


class MuscriptorNotProvisioned(RuntimeError):
    pass


def muscriptor_available() -> bool:
    try:
        import muscriptor  # noqa: F401

        return True
    except Exception:
        return False


def _resolve_device(requested: str) -> str | None:
    """Return a torch device string, or None to let MuScriptor auto-pick."""
    req = (requested or "auto").strip().lower()
    if req in {"", "auto"}:
        return None
    if req in {"cpu", "cuda", "mps"}:
        return req
    return None


def _get_model():
    if not muscriptor_available():
        raise MuscriptorNotProvisioned(
            "muscriptor is not installed. pip install muscriptor "
            "(see requirements-ml.txt)"
        )

    from muscriptor import TranscriptionModel

    size = (MUSCRIPTOR_SIZE or "medium").strip().lower()
    if size not in {"small", "medium", "large"}:
        size = "medium"
    device = _resolve_device(MUSCRIPTOR_DEVICE)
    key = (size, device or "auto")
    cached = _model_cache.get(key)
    if cached is not None:
        return cached

    log.info(
        "加载 MuScriptor：size=%s device=%s（首次会从 Hugging Face 下载权重）…",
        size,
        device or "auto",
    )
    try:
        kwargs: dict = {"weights_path": size}
        if device is not None:
            kwargs["device"] = device
        model = TranscriptionModel.load_model(**kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        hint = ""
        if any(
            s in msg
            for s in (
                "401",
                "403",
                "gated",
                "authorized",
                "authentication",
                "token",
                "license",
            )
        ):
            hint = (
                " Accept the CC BY-NC license on "
                f"https://huggingface.co/MuScriptor/muscriptor-{size} "
                "and set HF_TOKEN in backend/.env (see .env.example), "
                "or run: huggingface-cli login."
            )
        raise MuscriptorNotProvisioned(
            f"failed to load MuScriptor ({size}): {exc}.{hint}"
        ) from exc

    _model_cache[key] = model
    log.info("MuScriptor 已就绪：%s", size)
    return model


def _quantize_midi_bytes(midi_bytes: bytes) -> bytes:
    """Snap note onsets/durations to a readable grid (music21).

    Used when MuScriptor 0.3.x has no native ``quantize=`` flag, so sheet-music
    conversion (MuseScore / music21) sees cleaner timing.
    """
    import tempfile

    try:
        from music21 import converter
    except Exception:
        return midi_bytes

    with tempfile.TemporaryDirectory(prefix="piano_msq_") as tmp:
        mid = Path(tmp) / "in.mid"
        mid.write_bytes(midi_bytes)
        try:
            score = converter.parse(str(mid))
            score = score.quantize((4, 3), inPlace=False)
            out_path = Path(tmp) / "out.mid"
            score.write("midi", fp=str(out_path))
            return out_path.read_bytes()
        except Exception as exc:
            log.warning("MuScriptor MIDI 网格量化失败，使用原始 timing：%s", exc)
            return midi_bytes


def _infer_midi_bytes(model, audio_path: Path, *, quantize: bool) -> bytes:
    """Call the installed MuScriptor API (0.3.x vs newer main).

    PyPI 0.3.0 exposes ``transcribe_to_midi`` → ``bytes`` (no quantize kwarg).
    Newer git main has ``transcribe_and_postprocess(..., quantize=)``.
    When quantize is requested on 0.3.x we post-snap with music21.
    """
    audio = str(audio_path)

    if hasattr(model, "transcribe_and_postprocess"):
        try:
            result = model.transcribe_and_postprocess(audio, quantize=quantize)
            midi_bytes = result[0] if isinstance(result, tuple) else result
            if midi_bytes:
                return midi_bytes
        except TypeError:
            # Older signature without quantize=
            result = model.transcribe_and_postprocess(audio)
            midi_bytes = result[0] if isinstance(result, tuple) else result
            if midi_bytes and quantize:
                return _quantize_midi_bytes(midi_bytes)
            if midi_bytes:
                return midi_bytes

    if hasattr(model, "transcribe_to_midi"):
        midi_bytes = model.transcribe_to_midi(audio)
        if midi_bytes and quantize:
            log.info("MuScriptor 0.3.x：后处理网格量化（MUSCRIPTOR_QUANTIZE=1）")
            return _quantize_midi_bytes(midi_bytes)
        return midi_bytes

    raise MuscriptorNotProvisioned(
        "MuScriptor TranscriptionModel has neither transcribe_to_midi "
        "nor transcribe_and_postprocess"
    )


def run_muscriptor(audio_path: Path, out_midi: Path) -> Path:
    """Transcribe a full mix to multi-track MIDI via MuScriptor."""
    audio_path = Path(audio_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if not audio_path.is_file():
        raise MuscriptorNotProvisioned(f"audio not found: {audio_path}")

    model = _get_model()
    quantize = bool(MUSCRIPTOR_QUANTIZE)
    log.info(
        "MuScriptor 推理：%s → %s（quantize=%s）…",
        audio_path.name,
        out_midi.name,
        quantize,
    )
    try:
        midi_bytes = _infer_midi_bytes(model, audio_path, quantize=quantize)
    except MuscriptorNotProvisioned:
        raise
    except Exception as exc:
        raise MuscriptorNotProvisioned(f"MuScriptor inference failed: {exc}") from exc

    if not midi_bytes:
        raise MuscriptorNotProvisioned("MuScriptor produced empty MIDI")

    out_midi.write_bytes(midi_bytes)
    log.info(
        "MuScriptor 完成：%s（%.1f KB）",
        out_midi.name,
        out_midi.stat().st_size / 1024,
    )
    return out_midi
