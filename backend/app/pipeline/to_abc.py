"""MIDI / MusicXML → standard ABC notation (monophonic melody).

music21 can *read* ABC but does not reliably *write* it, so we emit ABC
ourselves from a flattened note stream. Tuned for the audio/video pipeline's
skyline + beat-quantized MIDI.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path


class AbcError(RuntimeError):
    pass


def midi_to_abc(
    midi_path: str | Path,
    out_abc: str | Path,
    *,
    title: str = "Transcription",
    unit_quarter: float = 1.0,
) -> Path:
    """Write a single-voice ABC file from ``midi_path``."""
    midi_path = Path(midi_path)
    out_abc = Path(out_abc)
    out_abc.parent.mkdir(parents=True, exist_ok=True)

    try:
        from music21 import converter, key, meter, note, tempo
    except Exception as exc:  # pragma: no cover
        raise AbcError("music21 is not installed") from exc

    score = converter.parse(str(midi_path))
    try:
        score = score.quantize((4, 3), inPlace=False)
    except Exception:
        pass

    # Metadata
    ts = score.recurse().getElementsByClass(meter.TimeSignature).first()
    meter_str = ts.ratioString if ts is not None else "4/4"
    beats = ts.numerator if ts is not None else 4
    beat_type = ts.denominator if ts is not None else 4
    measure_ql = float(beats) * (4.0 / float(beat_type))

    key_str = "C"
    kobj = score.recurse().getElementsByClass(key.Key).first()
    if kobj is None:
        kobj = score.recurse().getElementsByClass(key.KeySignature).first()
    if kobj is not None and hasattr(kobj, "tonic"):
        key_str = _key_to_abc(kobj)
    else:
        try:
            analyzed = score.analyze("key")
            key_str = _key_to_abc(analyzed)
        except Exception:
            pass

    qpm = 100
    mm = score.recurse().getElementsByClass(tempo.MetronomeMark).first()
    if mm is not None and getattr(mm, "number", None):
        try:
            qpm = int(round(float(mm.number)))
        except Exception:
            pass

    # Collect sounding events in order (notes + rests), monophonic.
    # Re-spell pitches into the chosen key so Ab→_A not ^G.
    try:
        if key_str.endswith("m") and len(key_str) > 1:
            k_ctx = key.Key(key_str[:-1], "minor")
        else:
            k_ctx = key.Key(key_str)
    except Exception:
        k_ctx = key.Key("C")
    key_alters = _key_step_alters(k_ctx)

    flat = score.flatten().notesAndRests.stream()
    tokens: list[str] = []
    beat_acc = 0.0
    for el in flat:
        if isinstance(el, note.Note):
            p = _spell_pitch_in_key(el.pitch, k_ctx)
            tok = _pitch_to_abc(p, key_alter_by_step=key_alters) + _len_suffix(
                float(el.quarterLength), unit_quarter
            )
        elif isinstance(el, note.Rest):
            tok = "z" + _len_suffix(float(el.quarterLength), unit_quarter)
        else:
            continue
        tokens.append(tok)
        beat_acc += float(el.quarterLength)
        # Insert barlines on measure boundaries (tolerance for float noise).
        if beat_acc + 1e-6 >= measure_ql:
            tokens.append("|")
            while beat_acc + 1e-6 >= measure_ql:
                beat_acc -= measure_ql

    if tokens and tokens[-1] != "|":
        tokens.append("|")

    # Soft-wrap body for readability (~16 tokens / line).
    body_lines = _wrap_abc_body(tokens)

    # L:1/4 means unit_quarter == 1.0
    l_field = _unit_to_l_field(unit_quarter)
    lines = [
        "X:1",
        f"T:{_abc_escape(title)}",
        f"M:{meter_str}",
        f"L:{l_field}",
        f"Q:1/4={qpm}",
        f"K:{key_str}",
        *body_lines,
    ]
    text = "\n".join(lines) + "\n"
    out_abc.write_text(text, encoding="utf-8")
    if not out_abc.exists():
        raise AbcError("failed to write ABC file")
    return out_abc


def musicxml_to_abc(
    xml_path: str | Path,
    out_abc: str | Path,
    *,
    title: str = "Transcription",
) -> Path:
    """Convenience: parse MusicXML then emit ABC (same writer path)."""
    xml_path = Path(xml_path)
    # Reuse MIDI path by parsing XML with music21 — write temp via converter.
    try:
        from music21 import converter
    except Exception as exc:  # pragma: no cover
        raise AbcError("music21 is not installed") from exc

    score = converter.parse(str(xml_path))
    # Write a temporary MIDI then convert — keeps one code path.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        mid = Path(td) / "tmp.mid"
        score.write("midi", fp=str(mid))
        return midi_to_abc(mid, out_abc, title=title)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abc_escape(s: str) -> str:
    return s.replace("\n", " ").strip() or "Untitled"


def _key_to_abc(k) -> str:
    """music21 Key / KeySignature → ABC K: field (e.g. C, Am, Ab, F#m)."""
    try:
        tonic = k.tonic.name.replace("-", "b")  # A- → Ab
        mode = getattr(k, "mode", "major") or "major"
        if str(mode).lower().startswith("min"):
            return f"{tonic}m"
        return tonic
    except Exception:
        return "C"


def _spell_pitch_in_key(src_pitch, k_ctx):
    """Prefer the enharmonic spelling that matches ``k_ctx`` (e.g. Ab not G#)."""
    try:
        from music21.pitch import Pitch
    except Exception:
        return src_pitch
    pc = int(src_pitch.pitchClass)
    octv = int(src_pitch.octave) if src_pitch.octave is not None else 4
    # Map pitch-class → preferred step/accidental from the key's diatonic set.
    preferred = {}
    try:
        for kp in k_ctx.pitches:
            preferred[int(kp.pitchClass)] = kp
    except Exception:
        return src_pitch
    if pc in preferred:
        model = preferred[pc]
        spelled = Pitch(model.name)
        spelled.octave = octv
        return spelled
    # Chromatic out-of-key: pick closest enharmonic with fewest accidentals.
    p = Pitch(midi=int(src_pitch.midi))
    candidates = [p] + list(p.getAllCommonEnharmonics())
    candidates.sort(
        key=lambda c: (
            abs(float(c.accidental.alter) if c.accidental else 0.0),
            len(c.name),
        )
    )
    best = candidates[0]
    best.octave = octv
    return best


def _pitch_to_abc(pitch, *, key_alter_by_step: dict[str, float] | None = None) -> str:
    """music21 Pitch → ABC pitch token (accidental + letter + octave marks).

    When ``key_alter_by_step`` is provided (from the key signature), accidentals
    that already belong to the key are omitted (standard ABC practice).
    """
    step = pitch.step  # C D E F G A B
    alter = 0.0
    if pitch.accidental is not None:
        alter = float(pitch.accidental.alter)

    acc = ""
    key_alter = 0.0
    if key_alter_by_step is not None:
        key_alter = float(key_alter_by_step.get(step, 0.0))
    written = alter
    # Only emit an accidental when it differs from the key signature.
    if abs(written - key_alter) > 0.25:
        delta = written  # absolute accidental relative to natural letter
        if abs(delta - key_alter) > 0.25:
            if written >= 1.5:
                acc = "^^"
            elif written >= 0.5:
                acc = "^"
            elif written <= -1.5:
                acc = "__"
            elif written <= -0.5:
                acc = "_"
            else:
                acc = "="  # natural against a sharpened/flattened key degree
    elif pitch.accidental is not None and pitch.accidental.name == "natural" and abs(key_alter) > 0.25:
        acc = "="

    octv = int(pitch.octave) if pitch.octave is not None else 4
    # ABC: C = C4, c = C5, C, = C3, c' = C6
    if octv >= 5:
        body = step.lower() + ("'" * (octv - 5))
    else:
        body = step.upper() + ("," * (4 - octv))
    return f"{acc}{body}"


def _key_step_alters(k_ctx) -> dict[str, float]:
    """step letter → accidental alter implied by the key (0 if natural)."""
    out: dict[str, float] = {s: 0.0 for s in "CDEFGAB"}
    try:
        for p in k_ctx.pitches:
            alter = float(p.accidental.alter) if p.accidental else 0.0
            out[p.step] = alter
    except Exception:
        pass
    return out


def _len_suffix(ql: float, unit_ql: float) -> str:
    """ABC length relative to L: unit (default quarter = 1)."""
    if ql <= 0:
        return ""
    try:
        f = Fraction(ql / unit_ql).limit_denominator(64)
    except (ZeroDivisionError, ValueError):
        return ""
    if f == 1:
        return ""
    if f.denominator == 1:
        return str(f.numerator)
    if f.numerator == 1:
        return f"/{f.denominator}"
    return f"{f.numerator}/{f.denominator}"


def _unit_to_l_field(unit_quarter: float) -> str:
    """Map unit quarterLength → ABC ``L:`` (fraction of a whole note)."""
    if abs(unit_quarter - 1.0) < 1e-9:
        return "1/4"
    if abs(unit_quarter - 0.5) < 1e-9:
        return "1/8"
    # unit_quarter is length in quarters; whole note = 4 quarters → L = unit/4.
    as_whole = Fraction(unit_quarter).limit_denominator(64) / 4
    if as_whole.numerator == 1:
        return f"1/{as_whole.denominator}"
    return f"{as_whole.numerator}/{as_whole.denominator}"


def _wrap_abc_body(tokens: list[str], max_per_line: int = 20) -> list[str]:
    if not tokens:
        return ["|"]
    lines: list[str] = []
    buf: list[str] = []
    for t in tokens:
        buf.append(t)
        if t == "|" or len(buf) >= max_per_line:
            lines.append(" ".join(buf))
            buf = []
    if buf:
        lines.append(" ".join(buf))
    return lines
