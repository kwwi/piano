"""Merge Piano RH/LH MIDI into a single braced grand-staff MusicXML."""
from __future__ import annotations

from pathlib import Path


def piano_midi_to_musicxml(
    midi_path: Path,
    out_xml: Path,
    *,
    prefer_musescore: bool = True,
) -> Path:
    """Convert arranged piano MIDI → MusicXML with braced Piano grand staff.

    In-app Verovio preview and exported MusicXML then share the same layout
    model (one Piano, treble + bass), instead of two unrelated parts.
    """
    midi_path = Path(midi_path)
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)

    try:
        return _write_grand_staff(midi_path, out_xml)
    except Exception:
        from ..to_musicxml import midi_to_musicxml

        return midi_to_musicxml(
            midi_path, out_xml, prefer_musescore=prefer_musescore
        )


def _write_grand_staff(midi_path: Path, out_xml: Path) -> Path:
    try:
        import pretty_midi
        from music21 import (
            clef,
            instrument,
            layout,
            meter,
            note,
            stream,
            tempo,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pretty_midi + music21 required") from exc

    from ..to_musicxml import MusicXmlError

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    bpm = 120.0
    try:
        tempos = pm.get_tempo_changes()[1]
        if len(tempos):
            bpm = float(tempos[0])
    except Exception:
        pass

    rh_notes: list = []
    lh_notes: list = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        name = (inst.name or "").strip().lower()
        for n in inst.notes:
            if "lh" in name or "left" in name or "bass" in name:
                lh_notes.append(n)
            elif "rh" in name or "right" in name:
                rh_notes.append(n)
            elif int(n.pitch) >= 60:
                rh_notes.append(n)
            else:
                lh_notes.append(n)

    if not rh_notes and not lh_notes:
        raise MusicXmlError("no notes for piano grand staff")

    def _staff(notes: list, *, treble: bool) -> stream.PartStaff:
        part = stream.PartStaff()
        part.insert(0, instrument.Piano())
        part.insert(0, clef.TrebleClef() if treble else clef.BassClef())
        ql_per_sec = float(bpm) / 60.0
        for n in notes:
            start_ql = max(0.0, float(n.start) * ql_per_sec)
            dur_ql = max(0.05, (float(n.end) - float(n.start)) * ql_per_sec)
            el = note.Note(int(n.pitch))
            el.quarterLength = dur_ql
            try:
                el.volume.velocity = max(40, min(120, int(n.velocity)))
            except Exception:
                pass
            part.insert(start_ql, el)
        try:
            part.makeMeasures(inPlace=True)
        except Exception:
            pass
        return part

    rh = _staff(rh_notes, treble=True)
    lh = _staff(lh_notes, treble=False)
    rh.partName = "Piano"
    lh.partName = "Piano"
    rh.partAbbreviation = "Pno"
    lh.partAbbreviation = "Pno"

    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, rh)
    score.insert(0, lh)
    try:
        score.insert(
            0,
            layout.StaffGroup(
                [rh, lh],
                name="Piano",
                abbreviation="Pno",
                symbol="brace",
                barTogether=True,
            ),
        )
    except Exception:
        pass

    try:
        score = score.quantize((4, 3), inPlace=False)
    except Exception:
        pass

    score.write("musicxml", fp=str(out_xml))
    if not out_xml.is_file():
        raise MusicXmlError("grand-staff MusicXML write failed")
    return out_xml
