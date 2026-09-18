"""Jianpu image OMR — **main melody only**.

Primary path: OpenCV projection (deskew → system bands → melody strip → OCR).
Fallback: Pillow preprocess + Tesseract on the full page.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageStat

from ..logging_zh import get_logger
from .omr_cv import opencv_available, run_opencv_omr

log = get_logger("piano.omr")


@dataclass
class OmrResponse:
    dsl: str
    confidence: float
    message: str
    deskewed_png: bytes


# Must NOT contain `'` — pytesseract passes -c through a shell.
_TESS_WHITELIST = r"--oem 3 --psm 6 -c tessedit_char_whitelist=01234567|_.,-"
_TESS_SPARSE = r"--oem 3 --psm 11 -c tessedit_char_whitelist=01234567|_.,-"


def run_omr(image_bytes: bytes) -> OmrResponse:
    try:
        im = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"cannot decode image: {exc}") from exc

    gray = ImageOps.grayscale(im.convert("RGB"))
    log.info("图片尺寸 %dx%d，开始识别主旋律", gray.width, gray.height)
    header = _ocr_header(gray)
    key = header.get("key", "C")
    tempo = header.get("tempo", 100)
    title = header.get("title", "(从图片识别 — 请校对)")
    log.info("页眉解析：调号=1=%s 速度=%s 标题=%s", key, tempo, title)

    lines: list[str] = []
    conf = 0.0
    deskewed_png = b""
    engine = "pillow"
    candidates: list[tuple[str, list[str], float]] = []

    if opencv_available():
        log.info("OpenCV 路径：纠偏 → 分行 → 主旋律条带 OCR…")
        cv = run_opencv_omr(image_bytes)
        if cv is not None:
            deskewed_png = cv.deskewed_png or b""
            cv_lines = _text_to_jianpu_lines(cv.text, preserve_order=True)
            log.info(
                "OpenCV 结果：谱行带=%d，原始文本长度=%d，清洗后旋律行=%d，置信度=%.0f%%",
                cv.band_count,
                len(cv.text),
                len(cv_lines),
                cv.confidence * 100,
            )
            if cv_lines:
                candidates.append(("opencv", cv_lines, cv.confidence))
    else:
        log.warning("未安装 OpenCV，跳过 CV 路径")

    log.info("Pillow 全页 OCR 路径…")
    processed = _preprocess_for_digits(gray)
    text_p, conf_p = _ocr_melody_digits(processed)
    pillow_lines = _text_to_jianpu_lines(text_p)
    if len(pillow_lines) < 2:
        log.info("Pillow 首轮行数偏少，启用强化二值化重试…")
        alt = _preprocess_for_digits(gray, hard=True)
        text2, conf2 = _ocr_melody_digits(alt, sparse=True)
        lines2 = _text_to_jianpu_lines(text2)
        if len(lines2) > len(pillow_lines):
            pillow_lines, conf_p = lines2, max(conf_p, conf2)
    log.info("Pillow 结果：旋律行=%d，置信度=%.0f%%", len(pillow_lines), conf_p * 100)
    if pillow_lines:
        candidates.append(("pillow", pillow_lines, conf_p))

    def _score(ls: list[str], engine: str) -> float:
        degs = sum(len(re.findall(r"[0-7]", ln)) for ln in ls)
        bars = sum(ln.count("|") for ln in ls)
        # Structured CV lines with rhythm/octave marks are far more trustworthy
        # than full-page digit soup.
        marks = sum(ln.count("_") + ln.count("'") + ln.count(",") for ln in ls)
        score = degs * 1.0 + bars * 0.5 + len(ls) * 1.5 + marks * 3.0
        if engine == "opencv":
            score *= 1.35
        # Penalize absurdly long single-line soup.
        if len(ls) <= 2 and degs > 60:
            score *= 0.25
        return score

    if candidates:
        candidates.sort(key=lambda c: _score(c[1], c[0]), reverse=True)
        engine, lines, conf = candidates[0]
        log.info(
            "选用引擎=%s（候选 %s）",
            engine,
            " / ".join(f"{n}:{len(ls)}行" for n, ls, _ in candidates),
        )

    if not deskewed_png:
        angle = _estimate_skew(gray)
        log.info("Pillow 纠偏角估计：%.2f°", angle)
        if abs(angle) >= 0.3:
            gray = gray.rotate(-angle, expand=True, fillcolor=255)
        preview = gray.copy()
        if preview.width > 1200:
            ratio = 1200 / preview.width
            preview = preview.resize(
                (1200, max(1, int(preview.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        preview.save(buf, format="PNG")
        deskewed_png = buf.getvalue()

    if not lines:
        dsl = _draft(title, key=key, tempo=tempo)
        warn = "纠偏完成，但未能可靠识别主旋律数字。"
        if gray.width < 900:
            warn += " 原图偏小（建议长边 ≥ 1500px）。"
        warn += " 请对照图片手补主旋律。"
        log.warning("识别失败：%s", warn)
        return OmrResponse(
            dsl=dsl, confidence=0.0, message=warn, deskewed_png=deskewed_png
        )

    dsl = (
        f"key: 1={key}\n"
        f"time: 4/4\n"
        f"tempo: {tempo}\n"
        f"title: {title}\n"
        "---\n"
        + "\n".join(lines)
        + "\n"
    )
    conf = min(max(conf, 0.2), 0.8)
    msg = (
        f"已用 {engine} 识别主旋律（忽略和弦框/歌词/和声层）。"
        "请再校对节奏与八度。"
    )
    if gray.width < 900:
        msg += "（原图分辨率偏低。）"
    log.info("输出 DSL：%d 行旋律，置信度=%.0f%%", len(lines), conf * 100)
    return OmrResponse(
        dsl=dsl, confidence=conf, message=msg, deskewed_png=deskewed_png
    )


def _preprocess_for_digits(gray: Image.Image, hard: bool = False) -> Image.Image:
    w, h = gray.size
    scale = max(2.0, 2000 / max(w, 1))
    scale = min(scale, 4.0)
    big = gray.resize(
        (max(1, int(w * scale)), max(1, int(h * scale))),
        Image.Resampling.LANCZOS,
    )
    big = ImageOps.autocontrast(big)
    big = ImageEnhance.Contrast(big).enhance(2.0 if hard else 1.7)
    big = big.filter(ImageFilter.UnsharpMask(radius=1.5, percent=160, threshold=2))
    if hard:
        big = big.point(lambda p: 0 if p < 155 else 255)
    return big


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
    proj = [sum(1 for x in range(w) if pix[x, y] == 0) for y in range(h)]
    if not proj:
        return 0.0
    mean = sum(proj) / len(proj)
    return sum((v - mean) ** 2 for v in proj) / len(proj)


def _ocr_header(gray: Image.Image) -> dict:
    out: dict = {}
    try:
        import pytesseract
    except Exception:
        return out

    w, h = gray.size
    header = gray.crop((0, 0, w, max(40, int(h * 0.18))))
    header = header.resize((header.width * 2, header.height * 2), Image.Resampling.LANCZOS)
    try:
        text = pytesseract.image_to_string(header, lang="chi_sim+eng")
    except Exception:
        try:
            text = pytesseract.image_to_string(header)
        except Exception:
            return out

    m = re.search(r"1\s*=\s*([#b♭♯]?[A-Ga-g])", text)
    if m:
        k = m.group(1).replace("♭", "b").replace("♯", "#")
        if len(k) == 2 and k[0] == "b":
            out["key"] = k[1].upper() + "b"
        elif len(k) == 2 and k[0] == "#":
            out["key"] = k[1].upper() + "#"
        else:
            out["key"] = k[0].upper() + (k[1:] if len(k) > 1 else "")

    m = re.search(r"(\d{2,3})\s*\(\s*16", text, re.I)
    if not m:
        m = re.search(r"(?:♩\s*=\s*|=\s*)(\d{2,3})\b", text)
    if m:
        tempo = int(m.group(1))
        if 40 <= tempo <= 220:
            out["tempo"] = tempo

    for line in text.splitlines():
        s = line.strip()
        if 2 <= len(s) <= 20 and re.search(r"[\u4e00-\u9fff]", s):
            if any(x in s for x in ("调", "拍", "男", "女", "词", "曲", "编")):
                continue
            out["title"] = s
            break
    return out


def _ocr_melody_digits(processed: Image.Image, sparse: bool = False) -> tuple[str, float]:
    """OCR digits, preferring taller boxes (main melody over chord circles)."""
    try:
        import pytesseract
    except Exception:
        return "", 0.0

    config = _TESS_SPARSE if sparse else _TESS_WHITELIST
    try:
        data = pytesseract.image_to_data(
            processed, config=config, output_type=pytesseract.Output.DICT
        )
    except Exception:
        try:
            text = pytesseract.image_to_string(processed, config=config)
            return text, 0.3 if text.strip() else 0.0
        except Exception:
            return "", 0.0

    n = len(data.get("text", []))
    boxes: list[dict] = []
    confs: list[float] = []
    for i in range(n):
        t = str(data["text"][i] or "").strip()
        if not t:
            continue
        # Keep only melody-ish tokens.
        if not re.search(r"[0-7|\-_.]", t):
            continue
        try:
            h = int(data["height"][i])
            w = int(data["width"][i])
            top = int(data["top"][i])
            left = int(data["left"][i])
            c = float(data["conf"][i])
        except Exception:
            continue
        if h < 8 or w < 4:
            continue
        if c >= 0:
            confs.append(c)
        boxes.append(
            {
                "text": t,
                "h": h,
                "w": w,
                "top": top,
                "left": left,
                "line": int(data.get("line_num", [0])[i]),
                "block": int(data.get("block_num", [0])[i]),
            }
        )

    if not boxes:
        return "", 0.0

    # Main melody digits are larger than circled chord numerals.
    heights = sorted(b["h"] for b in boxes if re.search(r"[0-7]", b["text"]))
    if heights:
        median_h = heights[len(heights) // 2]
        min_h = max(10, int(median_h * 0.55))
        # Drop very short glyphs (chord circles / lyric debris).
        boxes = [b for b in boxes if b["h"] >= min_h or "|" in b["text"] or "-" in b["text"]]

    # Group into horizontal bands by top coordinate (melody systems).
    boxes.sort(key=lambda b: (b["top"], b["left"]))
    bands: list[list[dict]] = []
    for b in boxes:
        if not bands:
            bands.append([b])
            continue
        prev = bands[-1]
        avg_top = sum(x["top"] for x in prev) / len(prev)
        avg_h = sum(x["h"] for x in prev) / len(prev)
        if abs(b["top"] - avg_top) <= max(12, avg_h * 0.65):
            prev.append(b)
        else:
            bands.append([b])

    lines: list[str] = []
    for band in bands:
        band.sort(key=lambda b: b["left"])
        # Skip left-margin section labels that OCR as sparse short digits.
        texts = [b["text"] for b in band]
        joined = " ".join(texts)
        digit_count = sum(1 for ch in joined if ch in "01234567")
        if digit_count < 3:
            continue
        # Chord-only bands: few tokens, mostly isolated 7 / 4 / 6.
        if digit_count <= 4 and len(band) <= 4:
            continue
        lines.append(joined)

    text = "\n".join(lines)
    good = [c for c in confs if c > 0]
    conf = (sum(good) / len(good) / 100.0) if good else 0.25
    if lines and conf < 0.15:
        conf = 0.25
    return text, max(0.0, min(1.0, conf))


_TOKEN = re.compile(r"[0-7][',]*_*\.?|-|\|")


def _text_to_jianpu_lines(text: str, preserve_order: bool = False) -> list[str]:
    if not text.strip():
        return []

    lines_out: list[str] = []
    for raw in text.splitlines():
        raw = raw.replace("，", ",").replace("｜", "|").replace("—", "-")
        # Glyph CV already emits spaced tokens; only explode digit runs from Pillow soup.
        if not preserve_order:
            raw = re.sub(r"[0-7]{2,}", lambda m: " ".join(m.group(0)), raw)
        tokens = _TOKEN.findall(raw)
        cleaned = [t for t in tokens if t in {"|", "-"} or re.match(r"^[0-7]", t)]
        if not cleaned:
            continue

        degrees = [t for t in cleaned if re.match(r"^[0-7]", t)]
        if len(degrees) < 4:
            continue
        # Drop chord debris rows like "7 7 7" / "4 6 0".
        if _looks_like_chord_row(degrees):
            continue

        parts: list[str] = []
        for t in cleaned:
            if t == "-":
                if parts and re.match(r"^[0-7]", parts[-1].split()[0]):
                    parts[-1] = f"{parts[-1]} -"
                elif lines_out:
                    prev = lines_out[-1].rstrip(" |").rstrip()
                    if re.search(r"[0-7](?:\s+-\s*)*$", prev):
                        lines_out[-1] = prev + " - |"
            elif t == "|":
                if parts and parts[-1] != "|":
                    parts.append("|")
            else:
                parts.append(t)
        if not parts:
            continue
        while parts and parts[0] in {"-", "|"}:
            parts.pop(0)
        if not parts:
            continue

        line = " ".join(parts)
        line = re.sub(r"\s*\|\s*", " | ", line).strip()
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"^[\-\|\s]+", "", line)
        if not line:
            continue
        # CV already places bars / underlines; don't invent denser rhythm.
        if not preserve_order:
            line = _ensure_barlines(line)
        if not line.endswith("|"):
            line = f"{line} |"
        degrees = re.findall(r"[0-7]", line)
        if len(degrees) > 48 and line.count("|") < 2:
            continue
        if not preserve_order:
            line = _recover_dense_bar_rhythm(line)
        lines_out.append(line)

    deduped = _dedupe_similar_lines(lines_out)
    if preserve_order:
        return deduped
    return _rank_melody_lines(deduped)


def _looks_like_chord_row(degrees: list[str]) -> bool:
    """Circled chord OCR often yields short runs dominated by 4/5/6/7."""
    if len(degrees) > 8:
        return False
    core = [d[0] for d in degrees]
    if len(set(core)) <= 2 and len(core) <= 6:
        return True
    # Many identical digits in a short row (e.g. 7 7 7 from maj7).
    if len(core) <= 5 and core.count(max(set(core), key=core.count)) >= len(core) - 1:
        return True
    return False


def _ensure_barlines(line: str, beats: int = 4) -> str:
    """Insert ``|`` every N degrees when OCR lost barlines on a long run."""
    if line.count("|") >= 2:
        return line
    tokens = line.replace("|", " ").split()
    degrees = [t for t in tokens if re.match(r"^[0-7]", t)]
    if len(degrees) < beats * 2 or len(degrees) % beats != 0:
        return line
    out: list[str] = []
    count = 0
    for t in tokens:
        out.append(t)
        if re.match(r"^[0-7]", t):
            count += 1
            if count % beats == 0:
                out.append("|")
    return " ".join(out)


def _recover_dense_bar_rhythm(line: str, beats: int = 4) -> str:
    trailing_bar = line.rstrip().endswith("|")
    chunks = [c.strip() for c in re.split(r"\s*\|\s*", line.strip()) if c.strip()]
    fixed: list[str] = []
    for chunk in chunks:
        tokens = chunk.split()
        degrees = [t for t in tokens if re.match(r"^[0-7]", t)]
        has_dur = any(("_" in t) or ("." in t) or t.endswith("-") or t == "-" for t in tokens)
        if has_dur or not degrees:
            fixed.append(chunk)
            continue
        suffix = ""
        if len(degrees) == beats * 2:
            suffix = "_"
        elif len(degrees) == beats * 4:
            suffix = "__"
        if not suffix:
            fixed.append(chunk)
            continue
        rewritten = []
        for t in tokens:
            if re.match(r"^[0-7]", t) and "_" not in t and "." not in t:
                rewritten.append(f"{t}{suffix}")
            else:
                rewritten.append(t)
        fixed.append(" ".join(rewritten))
    out = " | ".join(fixed)
    if trailing_bar and not out.endswith("|"):
        out = f"{out} |"
    return out


def _rank_melody_lines(lines: list[str]) -> list[str]:
    scored: list[tuple[float, str]] = []
    for line in lines:
        degrees = re.findall(r"[0-7]", line)
        bars = max(1, line.count("|"))
        avg = len(degrees) / bars
        score = float(len(degrees))
        if 3 <= avg <= 12:
            score *= 2.2
        elif avg > 18:
            score *= 0.35
        if "|" in line:
            score *= 1.4
        # Penalize lines that are almost all one pitch (chord OCR echo).
        if degrees:
            top = max(degrees.count(d) for d in set(degrees))
            if top / len(degrees) > 0.7 and len(degrees) < 12:
                score *= 0.3
        scored.append((score, line))
    scored.sort(key=lambda x: -x[0])
    keep = [ln for s, ln in scored if s >= 5][:18]
    return keep if keep else [ln for _, ln in scored[:10]]


def _dedupe_similar_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        core = re.sub(r"\s+", "", line)
        if any(_similar(core, re.sub(r"\s+", "", prev)) for prev in out):
            continue
        out.append(line)
    return out


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    n = min(len(a), len(b), 24)
    same = sum(1 for i in range(n) if a[i] == b[i])
    return same / max(len(a), len(b)) > 0.85


def _draft(title: str, key: str = "C", tempo: int = 100) -> str:
    return (
        f"key: 1={key}\ntime: 4/4\ntempo: {tempo}\ntitle: {title}\n---\n"
        "# 请按图片填写主旋律，例如：\n"
        "# 3 5 5 5 | 2 2 1 | 2 3 3 - |\n"
    )


_ = ImageStat
