"""Vocal removal (source separation) with HT-Demucs.

Primary path uses the ``demucs`` package (MIT). HT-Demucs v4 splits a mix into
drums/bass/other/vocals; we drop the ``vocals`` stem and sum the rest to obtain
the instrumental backing that the transcriber then analyses.

The heavy model weights are downloaded on first use. When Demucs is not
installed (e.g. a slim test environment) the caller can request a graceful
pass-through via ``allow_passthrough`` so the rest of the pipeline still runs.
"""
from __future__ import annotations

import shutil
from pathlib import Path


class SeparationError(RuntimeError):
    pass


def demucs_available() -> bool:
    try:
        import demucs.separate  # noqa: F401

        return True
    except Exception:
        return False


def remove_vocals(
    input_wav: str | Path,
    out_wav: str | Path,
    model: str = "htdemucs",
    allow_passthrough: bool = False,
) -> Path:
    """Produce an instrumental (no-vocals) WAV at ``out_wav``.

    Uses ``demucs`` two-stem separation (``--two-stems vocals``) and returns the
    ``no_vocals`` stem. If Demucs is unavailable and ``allow_passthrough`` is
    True, the input is copied unchanged.
    """
    input_wav = Path(input_wav)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    if not demucs_available():
        if allow_passthrough:
            shutil.copyfile(input_wav, out_wav)
            return out_wav
        raise SeparationError("demucs is not installed")

    import torch  # noqa: F401  (demucs pulls torch)
    from demucs.separate import main as demucs_main

    out_root = out_wav.parent / "_demucs"
    demucs_main(
        [
            "-n",
            model,
            "--two-stems",
            "vocals",
            "-o",
            str(out_root),
            str(input_wav),
        ]
    )
    # demucs writes <out_root>/<model>/<track>/no_vocals.wav
    stem = next(out_root.glob(f"{model}/*/no_vocals.wav"), None)
    if stem is None:
        raise SeparationError("demucs did not produce a no_vocals stem")
    shutil.move(str(stem), str(out_wav))
    return out_wav
