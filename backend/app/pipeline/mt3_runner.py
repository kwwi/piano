"""Optional MT3 high-accuracy transcription engine.

MT3 (Magenta, Apache-2.0) is a transformer-based multi-instrument transcriber.
It needs a sizeable JAX/T5X runtime plus checkpoints that are provisioned in
the production worker image (see ``requirements-ml.txt`` and the Docker
``INSTALL_ML=1`` build arg).

This module is the pluggable hook that ``transcribe._transcribe_mt3`` imports.
When the runtime is not present the import fails and the API surfaces a clear
``TranscriptionError`` — callers should fall back to ``basic_pitch``.
"""
from __future__ import annotations

from pathlib import Path


class Mt3NotProvisioned(RuntimeError):
    pass


def run_mt3(audio_path: Path, out_midi: Path) -> Path:
    """Run MT3 on ``audio_path`` and write a Standard MIDI File to ``out_midi``.

    Expected provisioning (production image):
      - ``mt3`` Python package (or Magenta's ``t5x`` checkpoint runner)
      - checkpoint directory pointed to by ``MT3_CHECKPOINT`` env var
    """
    try:
        import mt3  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency
        raise Mt3NotProvisioned(
            "MT3 is not installed. Rebuild the worker image with INSTALL_ML=1 "
            "and provision an MT3 checkpoint, or use model=basic_pitch."
        ) from exc

    checkpoint = __import__("os").environ.get("MT3_CHECKPOINT")
    if not checkpoint:
        raise Mt3NotProvisioned("MT3_CHECKPOINT env var is not set")

    # Concrete runner is environment-specific; keep the hook explicit so the
    # production image can swap in the real call without changing the API.
    raise Mt3NotProvisioned(
        f"MT3 package is present but no runner is wired for checkpoint={checkpoint}"
    )
