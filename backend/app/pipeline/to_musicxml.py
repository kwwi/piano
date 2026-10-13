"""Rule-based MIDI -> MusicXML via music21 (quantize + key/time inference).

Pitched parts are engraved by MIDI2ScoreTransformer (see ``score_m2s``); this
path handles drum kits and lightweight helpers such as the lead-sheet writer.
"""
from __future__ import annotations

from pathlib import Path

from ..logging_zh import get_logger

log = get_logger("piano.musicxml")


class MusicXmlError(RuntimeError):
    pass


def midi_to_musicxml_rule(
    midi_path: str | Path,
    out_xml: str | Path,
    quantize: bool = True,
    infer_key: bool = True,
) -> Path:
    """Convert MIDI to MusicXML with music21 rules."""
    midi_path = Path(midi_path)
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    if not midi_path.is_file():
        raise MusicXmlError(f"MIDI not found: {midi_path}")
    return _midi_to_musicxml_music21(
        midi_path,
        out_xml,
        quantize=quantize,
        infer_key=infer_key,
    )


def _sanitize_unpitched_instruments(score) -> None:
    """Fix drum/percussion parts so music21 can export MusicXML.

    MuScriptor (and some MIDI parsers) attach a *distinct* percussion instrument
    object to each unpitched note (Hi-Hat, Snare, …) while the part's
    ``instrumentStream`` only lists a generic ``UnpitchedPercussion``. music21's
    MusicXML writer then raises::

        Instrument instance Hi-Hat Cymbal … not found in instrumentStream

    Re-point every unpitched note at the part's percussion instrument.
    """
    try:
        from music21 import instrument, note
    except Exception:
        return

    for part in getattr(score, "parts", []) or []:
        unpitched_notes: list = []
        for el in part.recurse().notes:
            if isinstance(el, note.Unpitched):
                unpitched_notes.append(el)
            else:
                # Chord members may also be Unpitched.
                for n in getattr(el, "notes", []) or []:
                    if isinstance(n, note.Unpitched):
                        unpitched_notes.append(n)
        if not unpitched_notes:
            continue

        perc = None
        for el in part.recurse().getElementsByClass(instrument.UnpitchedPercussion):
            perc = el
            break
        if perc is None:
            perc = instrument.UnpitchedPercussion()
            name = (getattr(part, "partName", None) or "Percussion").strip()
            perc.instrumentName = name or "Percussion"
            try:
                part.insert(0, perc)
            except Exception:
                part.insert(0.0, perc)

        for n in unpitched_notes:
            try:
                n.storedInstrument = perc
            except Exception:
                pass


def _midi_to_musicxml_music21(
    midi_path: Path,
    out_xml: Path,
    *,
    quantize: bool,
    infer_key: bool,
) -> Path:
    try:
        from music21 import converter, meter
    except Exception as exc:  # pragma: no cover
        raise MusicXmlError("music21 is not installed") from exc

    score = converter.parse(str(midi_path))

    try:
        import pretty_midi

        pm = pretty_midi.PrettyMIDI(str(midi_path))
        for part, inst in zip(score.parts, pm.instruments):
            label = (inst.name or "").strip()
            if not label:
                continue
            part.partName = label
            if len(label) <= 6:
                part.partAbbreviation = label
    except Exception:
        pass

    if quantize:
        score = score.quantize((4, 3), inPlace=False)

    if infer_key:
        try:
            # Skip pure-percussion scores — key analysis is meaningless / noisy.
            has_pitched = False
            from music21 import note as _note

            for part in score.parts:
                for n in part.recurse().notes:
                    if isinstance(n, _note.Note):
                        has_pitched = True
                        break
                if has_pitched:
                    break
            if has_pitched:
                key = score.analyze("key")
                for part in score.parts:
                    first = part.getElementsByClass("Measure").first()
                    if first is not None:
                        first.insert(0, key)
        except Exception:
            pass

    if not score.recurse().getElementsByClass(meter.TimeSignature):
        if score.parts:
            score.parts[0].insert(0, meter.TimeSignature("4/4"))

    # Quantize / MIDI import can leave per-note percussion instruments that
    # break MusicXML export — always sanitize before write.
    _sanitize_unpitched_instruments(score)

    try:
        score.write("musicxml", fp=str(out_xml))
    except Exception as exc:
        # One more attempt after re-sanitize (quantize copies can reintroduce).
        msg = str(exc)
        if "instrumentStream" in msg or "Unpitched" in msg:
            log.warning("鼓轨 MusicXML 导出重试：%s", exc)
            _sanitize_unpitched_instruments(score)
            try:
                score.write("musicxml", fp=str(out_xml))
            except Exception as exc2:
                raise MusicXmlError(f"music21 MusicXML export failed: {exc2}") from exc2
        else:
            raise MusicXmlError(f"music21 MusicXML export failed: {exc}") from exc

    if not out_xml.exists():
        raise MusicXmlError("music21 did not write MusicXML")
    log.info("MusicXML via music21：%s → %s", midi_path.name, out_xml.name)
    return out_xml
