"""Dispatch piano arrangement backends: structured → texture → rule."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("piano.arrange_piano.model")


def run_piano_arranger(
    lead_midi: Path,
    out_midi: Path,
    *,
    backend: str = "auto",
    style: str = "pop",
    structured_root: str | Path | None = None,
) -> tuple[Path, str]:
    """Arrange lead MIDI → raw piano MIDI.

    Returns ``(path, backend_used)``.
    """
    from .fallback_rule import arrange_rule
    from .structured_adapter import arrange_structured, structured_available
    from .texture_model import arrange_texture

    lead_midi = Path(lead_midi)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    backend = (backend or "auto").strip().lower()
    style = (style or "pop").strip().lower()

    order: list[str]
    if backend == "rule":
        order = ["rule"]
    elif backend == "texture":
        order = ["texture", "rule"]
    elif backend == "structured":
        order = ["structured", "texture", "rule"]
    else:  # auto
        order = ["structured", "texture", "rule"]

    errors: list[str] = []
    for name in order:
        try:
            if name == "structured":
                if not structured_available(structured_root):
                    errors.append("structured: not configured")
                    continue
                arrange_structured(
                    lead_midi, out_midi, root=structured_root or "", style=style
                )
            elif name == "texture":
                arrange_texture(lead_midi, out_midi, style=style)
            else:
                arrange_rule(lead_midi, out_midi)
            if out_midi.is_file() and out_midi.stat().st_size > 0:
                log.info("piano arranger backend=%s style=%s", name, style)
                return out_midi, name
            errors.append(f"{name}: empty output")
        except Exception as exc:
            log.warning("piano arranger %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")

    raise RuntimeError("all piano arrangers failed: " + "; ".join(errors))
