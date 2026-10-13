"""Tests for Jianpu image OMR (deskew always; OCR optional)."""
import io

import pytest
from PIL import Image, ImageDraw, ImageFont
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.omr import run_omr, _text_to_jianpu_lines


def _make_jianpu_png() -> bytes:
    im = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(im)
    # Slightly tilted-looking content is fine; we mainly need decode + deskew path.
    draw.text((40, 60), "1 1 5 5 | 6 6 5 -", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_text_to_jianpu_lines_extracts_degrees():
    lines = _text_to_jianpu_lines("1 1 5 5 | 6 6 5 -")
    assert lines
    assert "1" in lines[0]
    assert "|" in lines[0]


def test_run_omr_deskews_and_returns_dsl():
    result = run_omr(_make_jianpu_png())
    assert result.deskewed_png.startswith(b"\x89PNG")
    assert "key:" in result.dsl
    assert "---" in result.dsl
    assert isinstance(result.confidence, float)


def test_omr_api_endpoint():
    client = TestClient(app)
    png = _make_jianpu_png()
    r = client.post("/omr", files={"file": ("j.png", png, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert "dsl" in body
    assert "deskewed_png_base64" in body
    assert body["deskewed_png_base64"]
