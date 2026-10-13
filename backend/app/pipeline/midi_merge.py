"""Merge per-chunk MIDI transcriptions into one timeline."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


class MidiMergeError(RuntimeError):
    pass


def merge_midis(
    segments: Sequence[tuple[Path | str, float]],
    out_midi: str | Path,
    *,
    overlap_sec: float = 0.0,
) -> Path:
    """Merge ``(midi_path, start_offset_sec)`` segments into ``out_midi``.

    Instruments are merged by ``(is_drum, program, name)``. For segments after
    the first, notes whose onset falls inside the leading ``overlap_sec`` window
    (relative to the chunk) are skipped to avoid double-counting overlapped
    audio.
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise MidiMergeError("pretty_midi is required") from exc

    if not segments:
        raise MidiMergeError("no MIDI segments to merge")

    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    overlap_sec = max(0.0, float(overlap_sec))

    tempo = 120.0
    first_path = Path(segments[0][0])
    try:
        first = pretty_midi.PrettyMIDI(str(first_path))
        tempos = first.get_tempo_changes()[1]
        if len(tempos):
            tempo = float(tempos[0])
    except Exception:
        pass

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    # key -> Instrument
    buckets: dict[tuple[bool, int, str], object] = {}

    def _bucket(inst) -> tuple[bool, int, str]:
        name = (inst.name or "").strip()
        return (bool(inst.is_drum), int(inst.program), name)

    for seg_i, (midi_path, offset_sec) in enumerate(segments):
        midi_path = Path(midi_path)
        if not midi_path.is_file():
            raise MidiMergeError(f"MIDI not found: {midi_path}")
        try:
            pm = pretty_midi.PrettyMIDI(str(midi_path))
        except Exception as exc:
            raise MidiMergeError(f"failed to read {midi_path.name}: {exc}") from exc

        offset = float(offset_sec)
        skip_before = overlap_sec if seg_i > 0 else 0.0

        for inst in pm.instruments:
            key = _bucket(inst)
            dest = buckets.get(key)
            if dest is None:
                dest = pretty_midi.Instrument(
                    program=inst.program,
                    is_drum=inst.is_drum,
                    name=(inst.name or "").strip() or f"Track{len(buckets)}",
                )
                buckets[key] = dest
                out.instruments.append(dest)

            for n in inst.notes:
                if n.start < skip_before:
                    continue
                dest.notes.append(
                    pretty_midi.Note(
                        velocity=n.velocity,
                        pitch=n.pitch,
                        start=n.start + offset,
                        end=n.end + offset,
                    )
                )
            for pb in inst.pitch_bends:
                if pb.time < skip_before:
                    continue
                dest.pitch_bends.append(
                    pretty_midi.PitchBend(pitch=pb.pitch, time=pb.time + offset)
                )
            for cc in inst.control_changes:
                if cc.time < skip_before:
                    continue
                dest.control_changes.append(
                    pretty_midi.ControlChange(
                        number=cc.number,
                        value=cc.value,
                        time=cc.time + offset,
                    )
                )

    # Drop empty instruments.
    out.instruments = [i for i in out.instruments if i.notes]
    if not out.instruments:
        raise MidiMergeError("merged MIDI has no notes")

    out.write(str(out_midi))
    return out_midi


def merge_chunk_midis(
    chunk_midis: Iterable[tuple[Path | str, float]],
    out_midi: str | Path,
    *,
    overlap_sec: float = 0.0,
) -> Path:
    return merge_midis(list(chunk_midis), out_midi, overlap_sec=overlap_sec)
