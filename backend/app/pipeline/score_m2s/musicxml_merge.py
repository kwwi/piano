"""Merge several single-/multi-part MusicXML files into one score-partwise file.

Works on the XML tree directly (no music21 round-trip) so M2S engraving details
survive untouched. Part ids are renumbered ``P1, P2, …``; instrument ids and
part-group numbers are rewritten to stay unique; shorter parts are padded with
whole-measure rests so every part has the same measure count.
"""
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Sequence

_DOCTYPE = (
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
    '"http://www.musicxml.org/dtds/partwise.dtd">'
)
_HEADER_TAGS = ("work", "movement-number", "movement-title", "identification", "defaults", "credit")


class MergeError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = _local(el.tag)


def _load(path: Path) -> ET.Element:
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise MergeError(f"invalid MusicXML {path.name}: {exc}") from exc
    _strip_ns(root)
    if root.tag != "score-partwise":
        raise MergeError(f"{path.name}: only score-partwise is supported (got {root.tag})")
    return root


def _measure_duration(divisions: int, beats: int, beat_type: int) -> int:
    return max(1, round(divisions * beats * 4 / max(beat_type, 1)))


def _last_attributes(part: ET.Element) -> tuple[int, int, int, int]:
    """(divisions, beats, beat_type, staves) in effect at the end of ``part``."""
    divisions, beats, beat_type, staves = 1, 4, 4, 1
    for measure in _children(part, "measure"):
        for attrs in _children(measure, "attributes"):
            d = _child(attrs, "divisions")
            if d is not None and (d.text or "").strip().isdigit():
                divisions = int(d.text.strip())
            s = _child(attrs, "staves")
            if s is not None and (s.text or "").strip().isdigit():
                staves = int(s.text.strip())
            t = _child(attrs, "time")
            if t is not None:
                b = _child(t, "beats")
                bt = _child(t, "beat-type")
                try:
                    if b is not None and bt is not None:
                        beats = int((b.text or "4").split("+")[0])
                        beat_type = int(bt.text or "4")
                except ValueError:
                    pass
    return divisions, beats, beat_type, staves


def _rest_measure(number: str, duration: int, staves: int) -> ET.Element:
    m = ET.Element("measure", {"number": number})
    for staff in range(1, staves + 1):
        if staff > 1:
            backup = ET.SubElement(m, "backup")
            ET.SubElement(backup, "duration").text = str(duration)
        n = ET.SubElement(m, "note")
        ET.SubElement(n, "rest", {"measure": "yes"})
        ET.SubElement(n, "duration").text = str(duration)
        ET.SubElement(n, "voice").text = str(1 if staff == 1 else 5)
        if staves > 1:
            ET.SubElement(n, "staff").text = str(staff)
    return m


def pad_part(part: ET.Element, target_measures: int) -> None:
    measures = _children(part, "measure")
    missing = target_measures - len(measures)
    if missing <= 0:
        return
    divisions, beats, beat_type, staves = _last_attributes(part)
    duration = _measure_duration(divisions, beats, beat_type)
    last_no = 0
    for m in measures:
        try:
            last_no = max(last_no, int(str(m.get("number", "0")).strip()))
        except ValueError:
            continue
    if not measures:
        # A part with no measures needs attributes to be renderable.
        first = _rest_measure("1", duration, staves)
        attrs = ET.Element("attributes")
        ET.SubElement(attrs, "divisions").text = str(divisions)
        time = ET.SubElement(attrs, "time")
        ET.SubElement(time, "beats").text = str(beats)
        ET.SubElement(time, "beat-type").text = str(beat_type)
        clef = ET.SubElement(attrs, "clef")
        ET.SubElement(clef, "sign").text = "G"
        ET.SubElement(clef, "line").text = "2"
        first.insert(0, attrs)
        part.append(first)
        last_no, missing = 1, missing - 1
    for i in range(missing):
        part.append(_rest_measure(str(last_no + i + 1), duration, staves))


def empty_part_score(name: str, out_xml: str | Path, *, measures: int = 1) -> Path:
    """Minimal one-part score with whole-measure rests (placeholder for empty tracks)."""
    root = ET.Element("score-partwise", {"version": "4.0"})
    pl = ET.SubElement(root, "part-list")
    sp = ET.SubElement(pl, "score-part", {"id": "P1"})
    ET.SubElement(sp, "part-name").text = name or "Part"
    part = ET.SubElement(root, "part", {"id": "P1"})
    pad_part(part, max(1, measures))
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    _write(root, out_xml)
    return out_xml


def _rename_ids(elements: Iterable[ET.Element], mapping: dict[str, str]) -> None:
    for el in elements:
        for sub in el.iter():
            old = sub.get("id")
            if old is not None and old in mapping:
                sub.set("id", mapping[old])


def _write(root: ET.Element, out_xml: Path) -> None:
    body = ET.tostring(root, encoding="unicode")
    tmp = out_xml.with_name(out_xml.name + ".part")
    tmp.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + _DOCTYPE + "\n" + body + "\n",
        encoding="utf-8",
    )
    tmp.replace(out_xml)


def merge_musicxml(
    sources: Sequence[str | Path],
    out_xml: str | Path,
    *,
    part_names: Sequence[str | None] | None = None,
) -> Path:
    """Concatenate the parts of ``sources`` (in order) into ``out_xml``.

    ``part_names[i]`` (when given) overrides the ``part-name`` of every part that
    came from ``sources[i]``.
    """
    paths = [Path(p) for p in sources]
    if not paths:
        raise MergeError("nothing to merge")
    out_xml = Path(out_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)

    docs = [_load(p) for p in paths]
    base = docs[0]
    merged = ET.Element("score-partwise", {"version": base.get("version", "4.0")})
    for tag in _HEADER_TAGS:
        for el in _children(base, tag):
            merged.append(copy.deepcopy(el))
    part_list = ET.SubElement(merged, "part-list")
    parts_out: list[ET.Element] = []

    next_part = 1
    group_offset = 0
    for src_idx, doc in enumerate(docs):
        pl = _child(doc, "part-list")
        if pl is None:
            raise MergeError(f"{paths[src_idx].name}: missing part-list")
        mapping: dict[str, str] = {}
        for sp in _children(pl, "score-part"):
            old = sp.get("id", "")
            new = f"P{next_part}"
            next_part += 1
            mapping[old] = new
            for k, inst in enumerate(sp.iter("score-instrument"), start=1):
                if inst.get("id"):
                    mapping[inst.get("id")] = f"{new}-I{k}"
        max_group = 0
        name_override = None
        if part_names is not None and src_idx < len(part_names):
            name_override = part_names[src_idx]
        for entry in list(pl):
            entry = copy.deepcopy(entry)
            tag = _local(entry.tag)
            if tag == "part-group":
                try:
                    num = int(entry.get("number", "1"))
                except ValueError:
                    num = 1
                max_group = max(max_group, num)
                entry.set("number", str(group_offset + num))
            elif tag == "score-part":
                if name_override:
                    pn = _child(entry, "part-name")
                    if pn is None:
                        pn = ET.Element("part-name")
                        entry.insert(0, pn)
                    pn.text = name_override
            part_list.append(entry)
        group_offset += max_group
        _rename_ids(list(part_list)[-len(list(pl)) :] if len(pl) else [], mapping)

        for part in _children(doc, "part"):
            part = copy.deepcopy(part)
            old = part.get("id", "")
            if old not in mapping:
                raise MergeError(f"{paths[src_idx].name}: part {old!r} not in part-list")
            _rename_ids([part], mapping)
            part.set("id", mapping[old])
            parts_out.append(part)

    target = max((len(_children(p, "measure")) for p in parts_out), default=0)
    for part in parts_out:
        pad_part(part, target)
        merged.append(part)

    _write(merged, out_xml)
    return out_xml
