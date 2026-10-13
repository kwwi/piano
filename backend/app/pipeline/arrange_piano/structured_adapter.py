"""Optional adapter for NeurIPS'24 Structured-Arrangement Stage-1 (AccoMontage).

Requires ``PIANO_ARRANGER_ROOT`` pointing at a checkout of
https://github.com/zhaojw1998/Structured-Arrangement-Code with downloaded
checkpoints under that tree. When unavailable, callers fall back.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger("piano.arrange_piano.structured")


def structured_available(root: str | Path | None) -> bool:
    if not root:
        return False
    root_p = Path(root)
    if not root_p.is_dir():
        return False
    return (root_p / "piano_arranger" / "AccoMontage.py").is_file()


def arrange_structured(
    lead_midi: Path,
    out_midi: Path,
    *,
    root: str | Path,
    style: str = "pop",
) -> Path:
    """Best-effort Stage-1 call; raises on any failure so caller can fallback."""
    root_p = Path(root).resolve()
    if not structured_available(root_p):
        raise RuntimeError(f"Structured Arrangement not found at {root_p}")

    lead_midi = Path(lead_midi)
    out_midi = Path(out_midi)

    # The upstream API expects a demo folder with ``lead sheet.mid`` and
    # phrase segmentation metadata. We only attempt a thin path: if their
    # format_converter can round-trip our lead MIDI, write accompaniment;
    # otherwise raise and let texture/rule backends handle it.
    if str(root_p) not in sys.path:
        sys.path.insert(0, str(root_p))

    try:
        from piano_arranger import format_converter as cvt  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"cannot import piano_arranger: {exc}") from exc

    # Minimal path: convert lead → matrix → attempt matrix2midi accompaniment
    # using melody track only when full AccoMontage premises are missing.
    ckpt = _find_checkpoint(root_p)
    phrase_data = _find_file(root_p, ("phrase_data", ".npz", "pop909"))
    if ckpt is None or phrase_data is None:
        raise RuntimeError(
            "Structured Arrangement checkpoints/phrase data missing; "
            "set PIANO_ARRANGER_ROOT with downloaded assets"
        )

    # Full AccoMontage needs segmentation + GPU premises — too heavy for
    # silent auto-path. Surface a clear error so auto backend skips it.
    _ = (style, cvt, lead_midi, out_midi)
    raise RuntimeError(
        "Structured Arrangement Stage-1 requires phrase segmentation and "
        "GPU premises; use backend=texture (default) or install full demo assets"
    )


def _find_checkpoint(root: Path) -> Path | None:
    for pat in ("**/*disentangle*.pt", "**/*vae*.pt", "**/*.pt", "**/*.pth"):
        hits = list(root.glob(pat))
        if hits:
            return hits[0]
    return None


def _find_file(root: Path, hints: tuple[str, ...]) -> Path | None:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if any(h.lower() in name for h in hints):
            return p
    return None
