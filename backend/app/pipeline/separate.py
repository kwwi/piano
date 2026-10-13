"""Source separation helpers for melody-focused transcription.

Default for this app is **vocals = main melody**. HT-Demucs two-stem mode
yields ``vocals`` and ``no_vocals``; we pick the stem the user asked for.
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


def separate_for_melody(
    input_wav: str | Path,
    out_wav: str | Path,
    *,
    prefer_vocals: bool = True,
    model: str = "htdemucs",
    allow_passthrough: bool = False,
) -> Path:
    """Write the stem most likely to contain the main melody.

    * ``prefer_vocals=True`` (default) → Demucs ``vocals`` stem (sung melody).
    * ``prefer_vocals=False`` → ``no_vocals`` instrumental (for karaoke / covers
      where the lead is an instrument).
    """
    input_wav = Path(input_wav)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    if not demucs_available():
        if allow_passthrough:
            shutil.copyfile(input_wav, out_wav)
            return out_wav
        raise SeparationError("demucs is not installed")

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
    stem_name = "vocals.wav" if prefer_vocals else "no_vocals.wav"
    stem = next(out_root.glob(f"{model}/*/{stem_name}"), None)
    if stem is None:
        # Fallback to the other stem if demucs naming differs.
        alt = "no_vocals.wav" if prefer_vocals else "vocals.wav"
        stem = next(out_root.glob(f"{model}/*/{alt}"), None)
    if stem is None:
        raise SeparationError(f"demucs did not produce {stem_name}")
    shutil.move(str(stem), str(out_wav))
    return out_wav


def remove_vocals(
    input_wav: str | Path,
    out_wav: str | Path,
    model: str = "htdemucs",
    allow_passthrough: bool = False,
) -> Path:
    """Back-compat: instrumental only (no vocals)."""
    return separate_for_melody(
        input_wav,
        out_wav,
        prefer_vocals=False,
        model=model,
        allow_passthrough=allow_passthrough,
    )
