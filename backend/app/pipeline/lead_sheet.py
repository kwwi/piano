"""Build a lead-sheet MIDI: monophonic melody + beat-quantized chords.

Takes a polyphonic transcription (Basic Pitch / MT3) and writes two tracks:
  - ``Melody`` — skyline (highest sounding pitch)
  - ``Chords`` — compact chord voicings per beat, named via music21 when available
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class LeadSheetError(RuntimeError):
    pass


def build_lead_sheet(
    midi_path: str | Path,
    out_midi: str | Path,
    *,
    melody_midi: str | Path | None = None,
    beats_per_chord: float = 1.0,
    min_chord_pcs: int = 2,
    exclude_melody_pcs: bool = True,
    melody_min_dur: float = 0.06,
    melody_hop: float = 0.02,
    chords_json: str | Path | None = None,
) -> Path:
    """Write ``out_midi`` with Melody + Chords instruments.

    ``midi_path`` supplies harmonic / polyphonic material for chord guessing.
    When ``melody_midi`` is set (e.g. CREPE output), that file becomes the
    Melody track instead of skyline-from-``midi_path``.

    Also optionally writes ``chords_json``:
    ``[{"start": 0.0, "end": 0.5, "symbol": "Am", "pitches": [57, 60, 64]}]``.
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise LeadSheetError("pretty_midi is required") from exc

    from .melody import extract_main_melody, _estimate_tempo

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if not midi_path.is_file():
        raise LeadSheetError(f"MIDI not found: {midi_path}")

    src = pretty_midi.PrettyMIDI(str(midi_path))
    tempo = _estimate_tempo(src)
    beat_sec = (60.0 / max(tempo, 1e-6)) * float(beats_per_chord)

    # --- Melody: prefer external monophonic MIDI (CREPE), else skyline ---
    melody_notes = []
    if melody_midi is not None and Path(melody_midi).is_file():
        mel_pm = pretty_midi.PrettyMIDI(str(melody_midi))
        for inst in mel_pm.instruments:
            if not inst.is_drum:
                melody_notes.extend(inst.notes)
        if mel_pm.get_tempo_changes()[1].size:
            try:
                tempo = float(mel_pm.get_tempo_changes()[1][0]) or tempo
            except Exception:
                pass
    else:
        melody_tmp = out_midi.parent / f".{out_midi.stem}_melody_tmp.mid"
        extract_main_melody(
            midi_path,
            melody_tmp,
            hop=melody_hop,
            min_dur=melody_min_dur,
        )
        mel_pm = pretty_midi.PrettyMIDI(str(melody_tmp))
        for inst in mel_pm.instruments:
            if not inst.is_drum:
                melody_notes.extend(inst.notes)
        try:
            melody_tmp.unlink(missing_ok=True)
        except Exception:
            pass

    all_notes = []
    for inst in src.instruments:
        if inst.is_drum:
            continue
        all_notes.extend(inst.notes)
    # Include external melody pitches so chord windows still see the timeline.
    if melody_midi is not None:
        all_notes = list(all_notes) + list(melody_notes)
    if not all_notes and not melody_notes:
        raise LeadSheetError("no notes to build lead sheet from")

    t_end = 0.0
    if all_notes:
        t_end = max(t_end, max(n.end for n in all_notes))
    if melody_notes:
        t_end = max(t_end, max(n.end for n in melody_notes))

    chord_events = _extract_chord_events(
        all_notes,
        melody_notes,
        t_end=t_end,
        beat_sec=beat_sec,
        min_chord_pcs=min_chord_pcs,
        exclude_melody_pcs=exclude_melody_pcs,
    )

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    mel_inst = pretty_midi.Instrument(program=0, name="Melody")
    for n in melody_notes:
        mel_inst.notes.append(
            pretty_midi.Note(
                velocity=max(40, int(n.velocity)),
                pitch=int(n.pitch),
                start=float(n.start),
                end=float(n.end),
            )
        )
    out.instruments.append(mel_inst)

    ch_inst = pretty_midi.Instrument(program=0, name="Chords")
    for ev in chord_events:
        for p in ev["midi_pitches"]:
            ch_inst.notes.append(
                pretty_midi.Note(
                    velocity=70,
                    pitch=int(p),
                    start=float(ev["start"]),
                    end=float(ev["end"]),
                )
            )
    out.instruments.append(ch_inst)
    out.write(str(out_midi))

    if chords_json is not None:
        path = Path(chords_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        slim = [
            {
                "start": e["start"],
                "end": e["end"],
                "symbol": e["symbol"],
                "pitches": e["midi_pitches"],
            }
            for e in chord_events
        ]
        path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_midi


def write_lead_sheet_musicxml(
    lead_midi: str | Path,
    out_xml: str | Path,
    *,
    chords_json: str | Path | None = None,
) -> Path:
    """MusicXML from lead-sheet MIDI, injecting ChordSymbol harmonies when possible."""
    from .melody import _estimate_tempo
    from .to_musicxml import midi_to_musicxml

    lead_midi = Path(lead_midi)
    out_xml = Path(out_xml)
    midi_to_musicxml(lead_midi, out_xml, quantize=True, infer_key=True)

    events: list[dict] = []
    if chords_json is not None and Path(chords_json).is_file():
        events = json.loads(Path(chords_json).read_text(encoding="utf-8"))
    if not events:
        return out_xml

    try:
        import pretty_midi
        from music21 import converter, harmony
    except Exception:
        return out_xml

    try:
        tempo = _estimate_tempo(pretty_midi.PrettyMIDI(str(lead_midi)))
        ql_per_sec = float(tempo) / 60.0
        score = converter.parse(str(out_xml))
        part = score.parts[0] if score.parts else score
        for ev in events:
            sym = (ev.get("symbol") or "").strip()
            if not sym or sym in {"N.C.", "NC", "?"}:
                continue
            start = float(ev["start"])
            try:
                cs = harmony.ChordSymbol(sym)
            except Exception:
                continue
            part.insert(start * ql_per_sec, cs)
        score.write("musicxml", fp=str(out_xml))
    except Exception:
        pass
    return out_xml


def _extract_chord_events(
    all_notes: list,
    melody_notes: list,
    *,
    t_end: float,
    beat_sec: float,
    min_chord_pcs: int,
    exclude_melody_pcs: bool,
) -> list[dict]:
    if t_end <= 0 or beat_sec <= 0:
        return []

    events: list[dict] = []
    t = 0.0
    last_symbol = None
    while t < t_end - 1e-6:
        t1 = min(t_end, t + beat_sec)
        mid = 0.5 * (t + t1)
        sounding = [n for n in all_notes if n.start - 1e-4 <= mid < n.end]
        pcs = {int(n.pitch) % 12 for n in sounding}

        if exclude_melody_pcs:
            mel_pcs = {
                int(n.pitch) % 12
                for n in melody_notes
                if n.start - 1e-4 <= mid < n.end
            }
            harmony_pcs = pcs - mel_pcs
            if len(harmony_pcs) >= min_chord_pcs:
                pcs = harmony_pcs
            # else keep full pcs (melody-only windows still get a chord guess)

        if len(pcs) < min_chord_pcs:
            # Try union of all pitches that overlap the window at all.
            window_notes = [
                n for n in all_notes if n.end > t + 1e-4 and n.start < t1 - 1e-4
            ]
            pcs = {int(n.pitch) % 12 for n in window_notes}
            if exclude_melody_pcs:
                mel_pcs = {
                    int(n.pitch) % 12
                    for n in melody_notes
                    if n.end > t + 1e-4 and n.start < t1 - 1e-4
                }
                reduced = pcs - mel_pcs
                if len(reduced) >= min_chord_pcs:
                    pcs = reduced

        if len(pcs) < min_chord_pcs:
            t = t1
            continue

        # Prefer concrete MIDI pitches near C3–C4 for voicing.
        concrete = _pcs_to_voicing(pcs, sounding or all_notes)
        symbol = _name_chord(concrete)
        # Merge consecutive identical symbols.
        if events and symbol == last_symbol:
            events[-1]["end"] = t1
        else:
            events.append(
                {
                    "start": t,
                    "end": t1,
                    "symbol": symbol,
                    "midi_pitches": concrete,
                }
            )
            last_symbol = symbol
        t = t1
    return events


def _pcs_to_voicing(pcs: Iterable[int], ref_notes: list) -> list[int]:
    """Map pitch classes to a compact closed voicing around C3–B3."""
    pcs = sorted({int(p) % 12 for p in pcs})
    if not pcs:
        return []
    # Anchor around median pitch of reference notes, else C3.
    if ref_notes:
        med = sorted(int(n.pitch) for n in ref_notes)[len(ref_notes) // 2]
        base = max(48, min(60, (med // 12) * 12))
    else:
        base = 48  # C3
    out: list[int] = []
    for pc in pcs:
        pitch = base + ((pc - base) % 12)
        if out and pitch <= out[-1]:
            pitch += 12
        # Keep voicing within ~1.5 octaves starting near base.
        while pitch > base + 16:
            pitch -= 12
        while pitch < base - 2:
            pitch += 12
        out.append(pitch)
    return sorted(set(out))


def _name_chord(midi_pitches: list[int]) -> str:
    if not midi_pitches:
        return "N.C."
    try:
        from music21 import chord, pitch

        c = chord.Chord([pitch.Pitch(midi=p) for p in midi_pitches])
        # Prefer a compact pop-style label when possible.
        fig = (c.figure or "").strip()
        if fig:
            return fig.replace("-", "b")
        name = (c.pitchedCommonName or "").strip()
        if name:
            return name
    except Exception:
        pass
    # Fallback: root pitch-class letter.
    root = midi_pitches[0] % 12
    letters = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return letters[root]
