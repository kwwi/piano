"""MIDI -> MusicXML using music21 (BSD).

music21 quantises note offsets/durations to a beat grid, infers key and time
signatures, and writes clean MusicXML that Verovio engraves on the client.
"""
from __future__ import annotations

from pathlib import Path


class MusicXmlError(RuntimeError):
    pass


def midi_to_musicxml(
    midi_path: str | Path,
    out_xml: str | Path,
    quantize: bool = True,
    infer_key: bool = True,
) -> Path:
    midi_path = Path(midi_path)
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)

    try:
        from music21 import converter, meter
    except Exception as exc:  # pragma: no cover
        raise MusicXmlError("music21 is not installed") from exc

    score = converter.parse(str(midi_path))

    if quantize:
        # Snap to sixteenth / triplet-eighth grids to clean up raw MIDI timing.
        score = score.quantize((4, 3), inPlace=False)

    if infer_key:
        try:
            key = score.analyze("key")
            for part in score.parts:
                first = part.getElementsByClass("Measure").first()
                if first is not None:
                    first.insert(0, key)
        except Exception:
            pass  # key inference is best-effort

    # Ensure at least a default time signature exists for readable output.
    if not score.recurse().getElementsByClass(meter.TimeSignature):
        score.parts[0].insert(0, meter.TimeSignature("4/4"))

    score.write("musicxml", fp=str(out_xml))
    if not out_xml.exists():
        raise MusicXmlError("music21 did not write MusicXML")
    return out_xml
