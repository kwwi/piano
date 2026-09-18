"""MIDI -> MusicXML for Verovio engraving.

Prefer **MuseScore CLI** when installed (better quantization, voicing, spelling).
Fall back to **music21** (quantize + key/time inference) when MuseScore is absent
or the CLI fails.

Override the binary with ``MUSESCORE_PATH`` / ``MUSESCORE_BIN``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..logging_zh import get_logger

log = get_logger("piano.musicxml")

# Common MuseScore / mscore locations (macOS app bundle + PATH names).
_MUSESCORE_CANDIDATES = (
    "mscore",
    "mscore4",
    "musescore",
    "musescore4",
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
    "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
    "/usr/bin/mscore",
    "/usr/bin/musescore",
    "/usr/local/bin/mscore",
    "/usr/local/bin/musescore",
)


class MusicXmlError(RuntimeError):
    pass


def find_musescore_bin() -> Path | None:
    """Return a MuseScore CLI binary path, or None if not found."""
    for key in ("MUSESCORE_PATH", "MUSESCORE_BIN", "MUSCRIPTOR_MUSESCORE"):
        raw = (os.getenv(key) or "").strip().strip('"').strip("'")
        if not raw:
            continue
        p = Path(raw)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        which = shutil.which(raw)
        if which:
            return Path(which)

    for name in _MUSESCORE_CANDIDATES:
        p = Path(name)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        which = shutil.which(name)
        if which:
            return Path(which)
    return None


def musescore_available() -> bool:
    return find_musescore_bin() is not None


def midi_to_musicxml(
    midi_path: str | Path,
    out_xml: str | Path,
    quantize: bool = True,
    infer_key: bool = True,
    *,
    prefer_musescore: bool = True,
) -> Path:
    """Convert MIDI to MusicXML (MuseScore CLI → music21 fallback)."""
    midi_path = Path(midi_path)
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    if not midi_path.is_file():
        raise MusicXmlError(f"MIDI not found: {midi_path}")

    if prefer_musescore:
        bin_path = find_musescore_bin()
        if bin_path is not None:
            try:
                path = _midi_to_musicxml_musescore(midi_path, out_xml, bin_path)
                _annotate_part_names(midi_path, out_xml)
                log.info(
                    "MusicXML via MuseScore：%s → %s",
                    midi_path.name,
                    out_xml.name,
                )
                return path
            except Exception as exc:
                log.warning(
                    "MuseScore CLI 失败，回退 music21：%s",
                    exc,
                )

    return _midi_to_musicxml_music21(
        midi_path,
        out_xml,
        quantize=quantize,
        infer_key=infer_key,
    )


def _midi_to_musicxml_musescore(
    midi_path: Path,
    out_xml: Path,
    bin_path: Path,
) -> Path:
    """Shell out to ``mscore -o out.musicxml in.mid``."""
    # MuseScore sometimes refuses odd extensions; stage under a temp dir.
    with tempfile.TemporaryDirectory(prefix="piano_mscore_") as tmp:
        tmp_dir = Path(tmp)
        staged_mid = tmp_dir / "in.mid"
        staged_mid.write_bytes(midi_path.read_bytes())
        staged_xml = tmp_dir / "out.musicxml"
        cmd = [str(bin_path), "-o", str(staged_xml), str(staged_mid)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=float(os.getenv("MUSESCORE_TIMEOUT", "180")),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MusicXmlError(f"MuseScore timed out: {bin_path}") from exc
        except FileNotFoundError as exc:
            raise MusicXmlError(f"MuseScore not executable: {bin_path}") from exc

        # Some builds write .musicxml / .xml with a slightly different stem.
        produced = staged_xml if staged_xml.is_file() else None
        if produced is None:
            for cand in tmp_dir.glob("out.*"):
                if cand.suffix.lower() in {".musicxml", ".xml", ".mxl"}:
                    produced = cand
                    break
        if produced is None or not produced.is_file():
            err = (proc.stderr or proc.stdout or "").strip()
            raise MusicXmlError(
                f"MuseScore did not write MusicXML (exit {proc.returncode}): {err[:400]}"
            )
        if proc.returncode != 0 and produced.stat().st_size == 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise MusicXmlError(
                f"MuseScore failed (exit {proc.returncode}): {err[:400]}"
            )

        data = produced.read_bytes()
        if produced.suffix.lower() == ".mxl":
            # Compressed MusicXML — expand to plain XML for Verovio / filtering.
            data = _mxl_to_musicxml_bytes(data)
        out_xml.write_bytes(data)

    if not out_xml.is_file() or out_xml.stat().st_size == 0:
        raise MusicXmlError("MuseScore produced empty MusicXML")
    text = out_xml.read_text(encoding="utf-8", errors="ignore")
    if "<score-partwise" not in text and "<score-timewise" not in text:
        raise MusicXmlError("MuseScore output is not MusicXML")
    return out_xml


def _mxl_to_musicxml_bytes(data: bytes) -> bytes:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Container points at the root score file; fall back to first .xml.
        names = zf.namelist()
        root = None
        if "META-INF/container.xml" in names:
            meta = zf.read("META-INF/container.xml").decode("utf-8", errors="ignore")
            import re

            m = re.search(r'full-path="([^"]+)"', meta)
            if m:
                root = m.group(1)
        if root is None:
            for n in names:
                if n.lower().endswith((".xml", ".musicxml")) and not n.startswith(
                    "META-INF/"
                ):
                    root = n
                    break
        if root is None:
            raise MusicXmlError("could not find score inside .mxl")
        return zf.read(root)


def _annotate_part_names(midi_path: Path, musicxml_path: Path) -> None:
    """Best-effort: copy pretty_midi instrument names onto MusicXML part-names."""
    try:
        import pretty_midi
        import xml.etree.ElementTree as ET
    except Exception:
        return
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        labels = [
            (inst.name or "").strip()
            for inst in pm.instruments
            if (inst.name or "").strip()
        ]
        if not labels:
            return
        tree = ET.parse(str(musicxml_path))
        root = tree.getroot()
        # MusicXML may use a default namespace.
        def local(tag: str) -> str:
            return tag.rsplit("}", 1)[-1] if "}" in tag else tag

        part_list = next(
            (c for c in root if local(c.tag) == "part-list"),
            None,
        )
        if part_list is None:
            return
        score_parts = [c for c in part_list if local(c.tag) == "score-part"]
        for sp, label in zip(score_parts, labels):
            # Ensure / update part-name
            pn = next((c for c in sp if local(c.tag) == "part-name"), None)
            if pn is None:
                # Preserve namespace of score-part if any.
                ns = ""
                if "}" in sp.tag:
                    ns = sp.tag.split("}")[0] + "}"
                pn = ET.SubElement(sp, f"{ns}part-name")
            pn.text = label
        tree.write(str(musicxml_path), encoding="utf-8", xml_declaration=True)
    except Exception:
        return


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
