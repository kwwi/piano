"""OpenCV Jianpu OMR — glyph-level main-melody recognition.

Pipeline (digit-first, then octave, then rhythm):

  1. Deskew (safe border) + dark-ink binarize (suppress watermark)
  2. Horizontal projection → musical systems
  3. Strip underlines for **segmentation only** (underlines glue adjacent digits)
  4. Locate melody row; connected components → individual digit boxes
  5. Classify each digit with cached MLP on underline-free masks
     (+ hole / aspect overrides)
  6. On full ink: octave dots ``'``/``,``, underlines ``_``, aug dots ``.``, dashes ``-``
  7. Emit Jianpu tokens per system
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from ..logging_zh import get_logger

log = get_logger("piano.omr.cv")

_WIN = (16, 24)  # w, h for digit features


@dataclass
class CvOmrResult:
    text: str
    confidence: float
    deskewed_png: bytes
    band_count: int


def opencv_available() -> bool:
    return cv2 is not None


def run_opencv_omr(image_bytes: bytes) -> CvOmrResult | None:
    if cv2 is None:
        return None
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        log.warning("OpenCV 无法解码图片")
        return None

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h0, w0 = gray.shape[:2]
    scale = max(1.0, 2200 / max(w0, 1))
    scale = min(scale, 4.0)
    if scale > 1.05:
        log.info("放大图片 ×%.2f（原 %dx%d）", scale, w0, h0)
        gray = cv2.resize(
            gray,
            (int(w0 * scale), int(h0 * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    angle = _estimate_skew_cv(gray)
    log.info("倾斜估计：%.2f°", angle)
    if abs(angle) >= 0.25:
        gray = _rotate(gray, -angle, border=255)
        log.info("已按 %.2f° 纠偏", -angle)
    else:
        log.info("倾斜可忽略，不旋转")

    deskewed_png = _encode_png(gray)
    ink = _dark_ink(gray)
    systems = _find_systems(ink)
    log.info("检测到谱系统（行带）%d 个", len(systems))
    if not systems:
        return CvOmrResult("", 0.0, deskewed_png, 0)

    clf = _digit_classifier()
    lines: list[str] = []
    confs: list[float] = []
    for idx, (y0, y1) in enumerate(systems, start=1):
        # Extend toward next system so melody + underlines fit.
        y1e = systems[idx][0] - 2 if idx < len(systems) else min(ink.shape[0], y1 + 80)
        y1e = max(y1e, y1)
        tokens, conf = _recognize_system(gray, ink, y0, y1e, clf)
        if not tokens:
            continue
        line = " ".join(tokens)
        if not line.rstrip().endswith("|"):
            line = f"{line} |"
        lines.append(line)
        confs.append(conf)
        log.info("  第%d带 主旋律：%s", idx, line[:120])

    joined = "\n".join(lines)
    conf = float(sum(confs) / len(confs)) if confs else 0.0
    log.info("OpenCV 字形识别合计 %d 行，平均置信度 %.0f%%", len(lines), conf * 100)
    return CvOmrResult(joined, conf, deskewed_png, len(systems))


# ---------------------------------------------------------------------------
# Preprocess / geometry
# ---------------------------------------------------------------------------

def _dark_ink(gray: np.ndarray) -> np.ndarray:
    adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    dark = (gray < 145).astype(np.uint8) * 255
    ink = cv2.bitwise_and(adapt, dark)
    ink = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    )
    return ink


def _strip_underlines(ink: np.ndarray) -> np.ndarray:
    """Remove long horizontal strokes so adjacent digits disconnect."""
    kw = max(20, ink.shape[1] // 50)
    horiz = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1))
    )
    return cv2.subtract(ink, horiz)


def _encode_png(gray: np.ndarray) -> bytes:
    h, w = gray.shape[:2]
    if w > 1200:
        ratio = 1200 / w
        gray = cv2.resize(gray, (1200, max(1, int(h * ratio))))
    ok, buf = cv2.imencode(".png", gray)
    return bytes(buf) if ok else b""


def _rotate(gray: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=int(border)
    )


def _estimate_skew_cv(gray: np.ndarray) -> float:
    small = gray
    h, w = gray.shape[:2]
    if w > 900:
        ratio = 900 / w
        small = cv2.resize(gray, (900, max(1, int(h * ratio))))
    dark = (small < 120).astype(np.uint8) * 255
    if dark.mean() < 1.0:
        dark = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    best_a, best_s = 0.0, -1.0
    scores: dict[float, float] = {}
    for a in [x * 0.5 for x in range(-20, 21)]:
        rot = _rotate(dark, a, border=0)
        score = float(rot.sum(axis=1).astype(np.float64).var())
        scores[a] = score
        if score > best_s:
            best_s, best_a = score, a

    zero = scores.get(0.0, 0.0)
    if best_a != 0.0 and zero >= best_s * 0.85:
        return 0.0
    if abs(best_a) >= 3.0:
        local = max(scores.get(a, 0.0) for a in (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0))
        if best_s < local * 1.15:
            best_a = max(
                (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0),
                key=lambda a: scores.get(a, 0.0),
            )
    return best_a


def _find_systems(ink: np.ndarray) -> list[tuple[int, int]]:
    h, w = ink.shape[:2]
    x0, x1 = int(w * 0.10), int(w * 0.98)
    proj = (ink[:, x0:x1] > 0).sum(axis=1).astype(np.float64)
    if proj.max() < 1:
        return []
    k = max(7, h // 100)
    smooth = np.convolve(proj, np.ones(k) / k, mode="same")
    thr = max(smooth.mean() * 0.45, smooth.max() * 0.10)
    mask = smooth > thr

    spans: list[tuple[int, int]] = []
    i = 0
    while i < h:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < h and mask[j]:
            j += 1
        if j - i >= max(16, int(h * 0.01)):
            spans.append((i, j))
        i = j

    merged: list[tuple[int, int]] = []
    for y0, y1 in spans:
        if not merged:
            merged.append((y0, y1))
            continue
        py0, py1 = merged[-1]
        gap = y0 - py1
        if gap < max(6, int(h * 0.004)) and (y1 - py0) < int(h * 0.09):
            merged[-1] = (py0, y1)
        else:
            merged.append((y0, y1))

    out = []
    for y0, y1 in merged:
        mid = (y0 + y1) / 2
        if mid < h * 0.07 or mid > h * 0.97:
            continue
        if y1 - y0 < 18:
            continue
        out.append((y0, y1))
    return out


# ---------------------------------------------------------------------------
# Digit classifier (cached MLP)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _digit_classifier():
    try:
        import joblib
    except Exception:
        return None
    path = Path(__file__).resolve().parent / "data" / "jianpu_digit_mlp.joblib"
    if not path.exists():
        log.warning("缺少数字分类模型 %s，回退 Tesseract", path)
        return None
    try:
        blob = joblib.load(path)
        return blob["clf"]
    except Exception as exc:  # noqa: BLE001
        log.warning("加载数字分类模型失败：%s", exc)
        return None


def _digit_features(img_bw: np.ndarray) -> np.ndarray:
    """Black digit on white → feature vector."""
    img = cv2.resize(img_bw, _WIN, interpolation=cv2.INTER_AREA)
    ink = ((img < 128) * 255).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(255 - ink, 4)
    holes = 0
    h, w = ink.shape
    for i in range(1, n):
        x, y, ww, hh, a = stats[i]
        if a >= 1 and x > 0 and y > 0 and x + ww < w - 1 and y + hh < h - 1:
            holes += 1
    ys, xs = np.where(ink > 0)
    if len(ys) == 0:
        return np.zeros(_WIN[0] * _WIN[1] + 6, np.float32)
    ar = (ys.max() - ys.min() + 1) / max(xs.max() - xs.min() + 1, 1)
    fill = float(ink.mean() / 255.0)
    rp = (ink > 0).sum(axis=1) / max(w, 1)
    top = float(rp[: h // 3].mean())
    mid = float(rp[h // 3 : 2 * h // 3].mean())
    bot = float(rp[2 * h // 3 :].mean())
    pix = (ink.astype(np.float32) / 255.0).ravel()
    return np.concatenate([pix, np.array([holes, ar, fill, top, mid, bot], np.float32)])


def _count_holes(img_bw: np.ndarray) -> tuple[int, float, float]:
    ink = ((img_bw < 128) * 255).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(255 - ink, 4)
    holes = 0
    h, w = ink.shape
    for i in range(1, n):
        x, y, ww, hh, a = stats[i]
        if a >= 1 and x > 0 and y > 0 and x + ww < w - 1 and y + hh < h - 1:
            holes += 1
    ys, _ = np.where(ink > 0)
    if len(ys) == 0:
        return holes, 0.0, 0.0
    cy = int((int(ys.min()) + int(ys.max())) / 2)
    cy = min(max(cy, 1), h - 1)
    top_roi = ink[:cy]
    bot_roi = ink[cy:]
    top = float((top_roi > 0).mean()) if top_roi.size else 0.0
    bot = float((bot_roi > 0).mean()) if bot_roi.size else 0.0
    return holes, top, bot


def _classify_digit(
    img_bw: np.ndarray, g: dict, med_h: float, clf
) -> tuple[str | None, float]:
    ar = g["h"] / max(g["w"], 1)
    if ar >= 2.25 and g["w"] <= med_h * 0.5:
        return "1", 0.92

    holes, top, bot = _count_holes(img_bw)
    # Only force obvious 0 (centered hole, round). Let MLP decide 4 vs 6.
    if holes >= 1 and ar < 2.0 and abs(top - bot) < 0.10 and ar <= 1.35:
        return "0", 0.88

    pred, conf = None, 0.0
    if clf is not None:
        try:
            proba = clf.predict_proba(_digit_features(img_bw).reshape(1, -1))[0]
            pred = str(clf.classes_[int(np.argmax(proba))])
            conf = float(np.max(proba))
        except Exception:
            pred, conf = None, 0.0

    if holes >= 1 and ar < 2.0 and pred not in ("0", "4", "6"):
        if bot > top * 1.15:
            pred = "6"
        elif ar <= 1.4:
            pred = "0"
        else:
            pred = "4"
        conf = max(conf, 0.7)
    # Broken low-res 6 sometimes classified as 2; hole proves otherwise.
    if holes >= 1 and pred == "2" and ar < 1.8:
        pred = "6"
        conf = max(conf, 0.75)
    # Open 6 (hole not closed at low res) is bottom-heavy; real 2 is balanced.
    if pred == "2" and bot > top * 1.45 and bot > 0.52:
        if _tesseract_digit(img_bw) == "6":
            pred = "6"
            conf = max(conf, 0.8)

    # Prefer MLP when confident on 4 vs 6 (hole heuristics misfire on italic 4).
    if pred is not None and conf >= 0.55:
        return pred, conf

    tess = _tesseract_digit(img_bw)
    if tess:
        return tess, max(conf, 0.45)
    return pred, conf


def _tesseract_digit(img_bw: np.ndarray) -> str | None:
    try:
        import pytesseract
    except Exception:
        return None
    h, w = img_bw.shape[:2]
    side = max(h, w) + 8
    canvas = np.full((side, side), 255, np.uint8)
    canvas[(side - h) // 2 : (side - h) // 2 + h, (side - w) // 2 : (side - w) // 2 + w] = (
        img_bw
    )
    up = cv2.resize(canvas, (64, 96), interpolation=cv2.INTER_CUBIC)
    try:
        raw = pytesseract.image_to_string(
            up, config=r"--oem 3 --psm 10 -c tessedit_char_whitelist=01234567"
        ).strip()
    except Exception:
        return None
    return raw[0] if raw and raw[0] in "01234567" else None


# ---------------------------------------------------------------------------
# Per-system glyph recognition
# ---------------------------------------------------------------------------

def _recognize_system(
    gray: np.ndarray,
    ink: np.ndarray,
    y0: int,
    y1: int,
    clf,
) -> tuple[list[str], float]:
    h, w = ink.shape[:2]
    x0 = int(w * 0.08)
    region = ink[y0:y1, x0:]
    region_g = gray[y0:y1, x0:]
    if region.size == 0:
        return [], 0.0

    seg = _strip_underlines(region)
    comps = _components(seg)
    cands = [
        c
        for c in comps
        if 12 <= c["h"] <= 40
        and 0.35 <= c["h"] / max(c["w"], 1) <= 3.5
        and c["w"] <= 50
    ]
    if len(cands) < 3:
        return [], 0.0

    ys = np.array([c["cy"] for c in cands])
    hist, edges = np.histogram(ys, bins=max(20, len(cands) // 2))
    peak_bin = int(np.argmax(hist))
    melody_cy = float((edges[peak_bin] + edges[peak_bin + 1]) / 2)
    near_h = [c["h"] for c in cands if abs(c["cy"] - melody_cy) < 24]
    if not near_h:
        return [], 0.0
    med_h = float(np.median(near_h))

    # Digit boxes on melody row (exclude thin barlines here; handle later).
    row = [
        c
        for c in comps
        if abs(c["cy"] - melody_cy) <= med_h * 0.55
        and c["h"] >= med_h * 0.4
        and c["h"] <= med_h * 1.6
        and 4 <= c["w"] <= med_h * 2.8
    ]
    row.sort(key=lambda c: c["x"])
    # Dedup overlapping.
    kept: list[dict] = []
    for c in row:
        if any(
            _overlap_x(c, k) > 0.5 and abs(c["cy"] - k["cy"]) < med_h * 0.4
            for k in kept
        ):
            continue
        kept.append(c)

    # Split residual wide blobs.
    glyphs: list[dict] = []
    for g in kept:
        glyphs.extend(_split_wide(seg, g, med_h))
    glyphs.sort(key=lambda c: c["x"])

    tokens: list[str] = []
    confs: list[float] = []
    for g in glyphs:
        # Barline
        if g["w"] <= max(3, med_h * 0.22) and g["h"] >= med_h * 0.7:
            if tokens and tokens[-1] != "|":
                tokens.append("|")
            continue
        # Extender dash
        if g["w"] >= med_h * 0.55 and g["h"] <= med_h * 0.35:
            if tokens and re.match(r"^[0-7]", tokens[-1]):
                tokens.append("-")
            continue

        img = _digit_mask(seg, g)
        if img is None:
            continue
        digit, conf = _classify_digit(img, g, med_h, clf)
        if digit is None:
            continue

        # Octave / rhythm from full ink (underlines + dots still present).
        oct_marks = _octave_marks(region, g, med_h)
        unders = _underline_count(region, g, med_h)
        dotted = _has_augmentation_dot(region, g, med_h)

        token = f"{digit}{oct_marks}{'_' * unders}"
        if dotted:
            token += "."
        tokens.append(token)
        confs.append(conf)

    cleaned: list[str] = []
    for t in tokens:
        if t == "|":
            if cleaned and cleaned[-1] != "|":
                cleaned.append("|")
        else:
            cleaned.append(t)
    avg = float(sum(confs) / len(confs)) if confs else 0.0
    degs = sum(1 for t in cleaned if re.match(r"^[0-7]", t))
    if degs < 3:
        return [], avg
    return cleaned, avg


def _digit_mask(seg: np.ndarray, g: dict) -> np.ndarray | None:
    roi = seg[g["y"] : g["y"] + g["h"], g["x"] : g["x"] + g["w"]]
    if roi.size == 0 or (roi > 0).sum() < 8:
        return None
    img = np.full_like(roi, 255)
    img[roi > 0] = 0
    ys, xs = np.where(roi > 0)
    return img[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _overlap_x(a: dict, b: dict) -> float:
    x1 = max(a["x"], b["x"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    return max(0, x2 - x1) / max(min(a["w"], b["w"]), 1)


def _split_wide(seg: np.ndarray, g: dict, med_h: float) -> list[dict]:
    if g["w"] < med_h * 1.05:
        return [g]
    roi = seg[g["y"] : g["y"] + g["h"], g["x"] : g["x"] + g["w"]]
    col = (roi > 0).sum(axis=0).astype(float)
    k = max(1, int(med_h * 0.06))
    sm = np.convolve(col, np.ones(k) / k, mode="same")
    expect = max(8, int(med_h * 0.52))
    thr = max(sm.max() * 0.22, 1)
    cuts: list[int] = []
    i = expect // 2
    while i < len(sm) - expect // 2:
        if sm[i] <= thr and sm[i] == sm[max(0, i - 2) : i + 3].min():
            if not cuts or i - cuts[-1] >= expect * 0.55:
                cuts.append(i)
                i += expect
                continue
        i += 1
    if not cuts:
        n = max(1, int(round(g["w"] / max(expect, 1))))
        if n <= 1:
            return [g]
        cuts = [int((k + 1) * g["w"] / n) for k in range(n - 1)]
    xs = [0] + cuts + [g["w"]]
    out: list[dict] = []
    for a, b in zip(xs, xs[1:]):
        if b - a < 4:
            continue
        sub = roi[:, a:b]
        ys, xs_ = np.where(sub > 0)
        if len(ys) == 0:
            continue
        yy0, yy1 = int(ys.min()), int(ys.max()) + 1
        xx0, xx1 = int(xs_.min()), int(xs_.max()) + 1
        out.append(
            {
                "x": g["x"] + a + xx0,
                "y": g["y"] + yy0,
                "w": xx1 - xx0,
                "h": yy1 - yy0,
                "area": int((sub > 0).sum()),
                "cx": g["x"] + a + (xx0 + xx1) / 2.0,
                "cy": g["y"] + (yy0 + yy1) / 2.0,
            }
        )
    return out or [g]


def _components(binary: np.ndarray) -> list[dict]:
    n, _labels, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 8 or w < 1 or h < 1:
            continue
        out.append(
            {
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "area": int(area),
                "cx": float(cents[i][0]),
                "cy": float(cents[i][1]),
            }
        )
    return out


def _octave_marks(band_ink: np.ndarray, g: dict, med_h: float) -> str:
    above = _count_dots(
        band_ink,
        x0=int(g["x"] - 2),
        x1=int(g["x"] + g["w"] + 2),
        y0=max(0, int(g["y"] - med_h * 0.75)),
        y1=max(0, int(g["y"] - 1)),
        med_h=med_h,
    )
    # Low-octave dots sit *below* rhythm underlines. Skip the underline band
    # (~0.35·med_h under the digit) so underline fragments are not counted as dots.
    under_skip = int(med_h * 0.38)
    below = _count_dots(
        band_ink,
        x0=int(g["x"] - 2),
        x1=int(g["x"] + g["w"] + 2),
        y0=min(band_ink.shape[0], int(g["y"] + g["h"] + under_skip)),
        y1=min(band_ink.shape[0], int(g["y"] + g["h"] + med_h * 0.95)),
        med_h=med_h,
    )
    # If both fire, prefer the stronger side; rarely both are real.
    if above and below:
        if above >= below:
            below = 0
        else:
            above = 0
    return ("'" * min(above, 2)) + ("," * min(below, 2))


def _count_dots(
    ink: np.ndarray, x0: int, x1: int, y0: int, y1: int, med_h: float
) -> int:
    if y1 <= y0 or x1 <= x0:
        return 0
    roi = ink[y0:y1, x0:x1]
    if roi.size == 0 or (roi > 0).sum() < 3:
        return 0
    comps = _components(roi)
    max_d = max(3, int(med_h * 0.28))
    dots = 0
    for c in comps:
        if c["h"] <= max_d and c["w"] <= max_d and c["area"] >= 3:
            if abs(c["h"] - c["w"]) <= max(2, max_d * 0.5):
                dots += 1
    return dots


def _underline_count(band_ink: np.ndarray, g: dict, med_h: float) -> int:
    y0 = min(band_ink.shape[0], int(g["y"] + g["h"] + 1))
    y1 = min(band_ink.shape[0], int(g["y"] + g["h"] + med_h * 0.6))
    x0 = max(0, int(g["x"] - 1))
    x1 = min(band_ink.shape[1], int(g["x"] + g["w"] + 1))
    if y1 <= y0 or x1 <= x0:
        return 0
    roi = band_ink[y0:y1, x0:x1]
    if roi.size == 0:
        return 0
    row = (roi > 0).sum(axis=1).astype(np.float64)
    if row.max() < roi.shape[1] * 0.35:
        return 0
    thr = row.max() * 0.45
    count = 0
    on = False
    for v in row:
        if v >= thr and not on:
            count += 1
            on = True
        elif v < thr:
            on = False
    return min(count, 3)


def _has_augmentation_dot(band_ink: np.ndarray, g: dict, med_h: float) -> bool:
    x0 = min(band_ink.shape[1], int(g["x"] + g["w"] + 1))
    x1 = min(band_ink.shape[1], int(g["x"] + g["w"] + med_h * 0.45))
    y0 = max(0, int(g["cy"] - med_h * 0.25))
    y1 = min(band_ink.shape[0], int(g["cy"] + med_h * 0.25))
    if x1 <= x0 or y1 <= y0:
        return False
    roi = band_ink[y0:y1, x0:x1]
    comps = _components(roi)
    max_d = max(3, int(med_h * 0.25))
    for c in comps:
        if c["h"] <= max_d and c["w"] <= max_d and c["area"] >= 3:
            return True
    return False
