"""Render MusicXML files to SVG (and PNG if a converter is available) with Verovio.

Usage: python tool/render_musicxml.py <out_dir> <file1.musicxml> [file2 ...]
"""
import sys
from pathlib import Path

import verovio


def render(path: Path, out_dir: Path) -> Path:
    tk = verovio.toolkit()
    tk.setOptions(
        {
            "pageWidth": 2100,
            "pageHeight": 900,
            "scale": 45,
            "adjustPageHeight": True,
            "footer": "none",
            "header": "auto",
        }
    )
    if not tk.loadFile(str(path)):
        raise SystemExit(f"Verovio failed to load {path}")
    svg = tk.renderToSVG(1)
    out_svg = out_dir / (path.stem + ".svg")
    out_svg.write_text(svg, encoding="utf-8")
    print(f"wrote {out_svg}")

    # Optional SVG -> PNG.
    try:
        import cairosvg

        out_png = out_dir / (path.stem + ".png")
        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(out_png),
            background_color="white",
            output_width=1600,
        )
        print(f"wrote {out_png}")
    except Exception as exc:  # pragma: no cover
        print(f"(png conversion skipped: {exc})")
    return out_svg


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sys.argv[2:]:
        render(Path(f), out_dir)


if __name__ == "__main__":
    main()
