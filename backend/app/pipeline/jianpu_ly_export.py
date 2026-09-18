"""Optional GPL jianpu-ly → LilyPond export for numbered-notation engraving.

The primary staff path remains MusicXML + Verovio. This module adds a mature
LilyPond toolchain when the operator wants jianpu-ly output.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def jianpu_ly_available() -> bool:
    try:
        import jianpu_ly  # noqa: F401

        return True
    except Exception:
        try:
            subprocess.run(
                ["jianpu-ly", "--help"],
                capture_output=True,
                check=False,
            )
            return True
        except Exception:
            return False


def dsl_to_jianpu_ly_input(dsl: str) -> str:
    """Convert our app DSL body into a whitespace jianpu-ly note stream."""
    lines = []
    body = False
    for raw in dsl.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "---":
            body = True
            continue
        if not body:
            # Map headers loosely.
            m = re.match(r"key:\s*1=(\S+)", line, re.I)
            if m:
                lines.append(f"1={m.group(1)}")
            m = re.match(r"time:\s*(\d+)/(\d+)", line, re.I)
            if m:
                lines.append(f"{m.group(1)}/{m.group(2)}")
            m = re.match(r"tempo:\s*(\d+)", line, re.I)
            if m:
                lines.append(f"q={m.group(1)}")
            continue
        # jianpu-ly uses spaces; keep barlines as |
        cleaned = line.replace("_", "")  # underlines approximated away
        lines.append(cleaned)
    return "\n".join(lines) + "\n"


def export_lilypond(dsl: str, out_ly: str | Path) -> Path:
    """Run jianpu-ly on ``dsl`` and write LilyPond source to ``out_ly``."""
    out_ly = Path(out_ly)
    out_ly.parent.mkdir(parents=True, exist_ok=True)
    text = dsl_to_jianpu_ly_input(dsl)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ["jianpu-ly", tmp_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            # Library API fallback.
            ly = _via_module(text)
        else:
            ly = proc.stdout
        out_ly.write_text(ly, encoding="utf-8")
        return out_ly
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _via_module(text: str) -> str:
    try:
        import jianpu_ly
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("jianpu-ly is not installed") from exc
    # Older / newer APIs differ; try common entry points.
    if hasattr(jianpu_ly, "process"):
        return str(jianpu_ly.process(text))
    raise RuntimeError(
        "jianpu-ly produced no output; ensure the `jianpu-ly` script is on PATH"
    )
