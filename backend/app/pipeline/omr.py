"""Jianpu image OMR (deskew + OCR → DSL).

Used by ``POST /omr``. Deskew uses a projection-profile angle search (Pillow).
Recognition prefers ``pytesseract`` when available (whitelist of Jianpu tokens);
otherwise returns the deskewed image with an empty draft so the client can
still offer the editable-preview UX.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageFilter, ImageStat


@dataclass
class OmrResponse:
    dsl: str
    confidence: float
    message: str
    deskewed_png: bytes


def run_omr(image_bytes: bytes) -> OmrResponse:
    try:
        im = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"cannot decode image: {exc}") from exc

    gray = ImageOps.grayscale(im)
    angle = _estimate_skew(gray)
    if abs(angle) >= 0.3:
        gray = gray.rotate(-angle, expand=True, fillcolor=255)

    buf = io.BytesIO()
    gray.save(buf, format="PNG")
    deskewed_png = buf.getvalue()

    text, conf = _ocr(gray)
    lines = _text_to_jianpu_lines(text)
    if not lines:
        dsl = _draft("(OCR 未识别到音符 — 请手补)")
        return OmrResponse(
            dsl=dsl,
            confidence=0.0,
            message="纠偏完成，但 OCR 未识别到简谱字符，请在预览中手补",
            deskewed_png=deskewed_png,
        )

    dsl = "key: 1=C\ntime: 4/4\ntempo: 100\ntitle: (从图片识别 — 请校对)\n---\n"
    dsl += "\n".join(lines) + "\n"
    return OmrResponse(
        dsl=dsl,
        confidence=conf,
        message="已完成纠偏与 OCR，请校对后应用",
        deskewed_png=deskewed_png,
    )


def _estimate_skew(gray: Image.Image) -> float:
    small = gray.copy()
    if small.width > 800:
        ratio = 800 / small.width
        small = small.resize((800, max(1, int(small.height * ratio))))

    best_a, best_s = 0.0, -1.0
    for a in [x * 0.5 for x in range(-30, 31)]:
        rot = small.rotate(a, expand=False, fillcolor=255)
        score = _proj_var(rot)
        if score > best_s:
            best_s, best_a = score, a
    for a in [best_a + x * 0.1 for x in range(-5, 6)]:
        rot = small.rotate(a, expand=False, fillcolor=255)
        score = _proj_var(rot)
        if score > best_s:
            best_s, best_a = score, a
    return best_a


def _proj_var(gray: Image.Image) -> float:
    bw = gray.point(lambda p: 0 if p < 128 else 255, mode="1")
    pix = bw.load()
    w, h = bw.size
    proj = []
    for y in range(h):
        s = sum(1 for x in range(w) if pix[x, y] == 0)
        proj.append(s)
    if not proj:
        return 0.0
    mean = sum(proj) / len(proj)
    return sum((v - mean) ** 2 for v in proj) / len(proj)


def _ocr(gray: Image.Image) -> tuple[str, float]:
    try:
        import pytesseract
    except Exception:
        return "", 0.0

    # Sharpen a bit for thin print.
    processed = gray.filter(ImageFilter.SHARPEN)
    config = r"--psm 6 -c tessedit_char_whitelist=01234567|#b'.,-=_ "
    try:
        data = pytesseract.image_to_data(processed, config=config, output_type=pytesseract.Output.DICT)
        texts = []
        confs = []
        for t, c in zip(data.get("text", []), data.get("conf", [])):
            if not t or not str(t).strip():
                continue
            texts.append(str(t))
            try:
                confs.append(float(c))
            except Exception:
                pass
        text = " ".join(texts)
        conf = (sum(confs) / len(confs) / 100.0) if confs else 0.3
        return text, max(0.0, min(1.0, conf))
    except Exception:
        try:
            text = pytesseract.image_to_string(processed, config=config)
            return text, 0.4 if text.strip() else 0.0
        except Exception:
            return "", 0.0


_TOKEN = re.compile(r"[#b=]?[0-7]['|,]*_*\.?|-|\|")


def _text_to_jianpu_lines(text: str) -> list[str]:
    if not text.strip():
        return []
    lines_out: list[str] = []
    for raw in text.splitlines() or [text]:
        tokens = _TOKEN.findall(raw.replace("，", ",").replace("｜", "|"))
        # Keep only plausible jianpu tokens.
        cleaned = []
        for t in tokens:
            if t in {"|", "-"} or re.match(r"^[#b=]?[0-7]", t):
                cleaned.append(t)
        if not cleaned:
            continue
        # Rebuild with spaces; ensure bar at end.
        line = " ".join(cleaned)
        line = re.sub(r"\s*\|\s*", " | ", line).strip()
        if not line.endswith("|"):
            line = f"{line} |"
        # Must contain at least one degree digit.
        if re.search(r"[0-7]", line):
            lines_out.append(line)
    return lines_out


def _draft(title: str) -> str:
    return (
        f"key: 1=C\ntime: 4/4\ntempo: 100\ntitle: {title}\n---\n"
        "1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -\n"
    )


# Silence unused import warning helpers for static checkers.
_ = ImageStat
