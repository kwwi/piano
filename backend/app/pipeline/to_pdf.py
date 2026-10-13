"""MusicXML -> PDF via Verovio SVG (optional rasterization).

Writes ``score.pdf`` when a SVG→raster tool is available (cairosvg, or
``rsvg-convert`` / ImageMagick ``convert`` on PATH). Otherwise raises
``PdfError`` so the pipeline can skip PDF without failing the job.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class PdfError(RuntimeError):
    pass


def musicxml_to_pdf(musicxml_path: str | Path, out_pdf: str | Path) -> Path:
    musicxml_path = Path(musicxml_path)
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    try:
        import verovio
    except Exception as exc:  # pragma: no cover
        raise PdfError("verovio is not installed") from exc

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise PdfError("Pillow is not installed") from exc

    tk = verovio.toolkit()
    tk.setOptions(
        {
            "pageWidth": 2100,
            "pageHeight": 2970,
            "scale": 40,
            "adjustPageHeight": True,
            "footer": "none",
            "header": "auto",
        }
    )
    if not tk.loadFile(str(musicxml_path)):
        raise PdfError(f"Verovio failed to load {musicxml_path}")

    page_count = max(1, int(tk.getPageCount()))
    images: list[Image.Image] = []
    with tempfile.TemporaryDirectory(prefix="piano_pdf_") as tmp:
        tmp_dir = Path(tmp)
        for page in range(1, page_count + 1):
            svg = tk.renderToSVG(page)
            png_path = tmp_dir / f"page_{page}.png"
            _svg_to_png(svg, png_path)
            images.append(Image.open(png_path).convert("RGB"))

    if not images:
        raise PdfError("no pages rendered")

    first, rest = images[0], images[1:]
    first.save(str(out_pdf), "PDF", save_all=bool(rest), append_images=rest)
    if not out_pdf.is_file():
        raise PdfError("PDF was not written")
    return out_pdf


def _svg_to_png(svg: str, out_png: Path) -> None:
    try:
        import cairosvg

        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(out_png),
            background_color="white",
            output_width=1600,
        )
        if out_png.is_file():
            return
    except Exception:
        pass

    with tempfile.NamedTemporaryFile(
        suffix=".svg", delete=False, mode="w", encoding="utf-8"
    ) as fh:
        fh.write(svg)
        svg_path = Path(fh.name)

    try:
        rsvg = shutil.which("rsvg-convert")
        if rsvg:
            subprocess.run(
                [rsvg, "-w", "1600", "-f", "png", "-o", str(out_png), str(svg_path)],
                check=True,
                capture_output=True,
            )
            if out_png.is_file():
                return

        convert = shutil.which("convert") or shutil.which("magick")
        if convert:
            cmd = [convert, str(svg_path), str(out_png)]
            if Path(convert).name == "magick":
                cmd = [convert, "convert", str(svg_path), str(out_png)]
            subprocess.run(cmd, check=True, capture_output=True)
            if out_png.is_file():
                return
    finally:
        svg_path.unlink(missing_ok=True)

    raise PdfError(
        "SVG→PNG unavailable (install cairosvg, or rsvg-convert / ImageMagick)"
    )
