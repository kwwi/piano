"""Unit tests for MIDI track listing / subset export."""
from pathlib import Path

import pretty_midi
import pytest

from app.pipeline.tracks import (
    TrackError,
    list_midi_tracks,
    parse_track_indices,
    write_per_track_midis,
    write_track_subset,
    write_tracks_manifest,
)
from app.pipeline.to_abc import midi_to_abc
from app.pipeline.to_musicxml import midi_to_musicxml


def _multi_track_midi(path: Path) -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(program=0, name="Piano")
    piano.notes.append(pretty_midi.Note(90, 60, 0.0, 0.5))
    piano.notes.append(pretty_midi.Note(90, 64, 0.5, 1.0))
    violin = pretty_midi.Instrument(program=40, name="Violin")
    violin.notes.append(pretty_midi.Note(80, 67, 0.0, 1.0))
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Kit")
    drums.notes.append(pretty_midi.Note(100, 36, 0.0, 0.2))
    pm.instruments.extend([piano, violin, drums])
    pm.write(str(path))
    return path


def test_list_and_manifest(tmp_path: Path):
    mid = _multi_track_midi(tmp_path / "raw.mid")
    tracks = list_midi_tracks(mid)
    assert len(tracks) == 3
    assert tracks[0]["name"] == "Piano"
    assert tracks[0]["note_count"] == 2
    assert tracks[0]["abbreviation"] == "Pno"
    assert tracks[1]["program"] == 40
    assert tracks[1]["abbreviation"] == "Str"
    assert tracks[2]["is_drum"] is True

    manifest = write_tracks_manifest(mid, tmp_path / "tracks.json")
    text = manifest.read_text(encoding="utf-8")
    assert "Piano" in text
    assert "transcription_raw.mid" in text


def test_unnamed_instruments_get_pno_labels(tmp_path: Path):
    import pretty_midi

    mid = tmp_path / "anon.mid"
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    for pitch in (60, 64, 67):
        inst = pretty_midi.Instrument(program=0, name="")
        inst.notes.append(pretty_midi.Note(90, pitch, 0.0, 0.5))
        pm.instruments.append(inst)
    pm.write(str(mid))

    tracks = list_midi_tracks(mid)
    assert [t["name"] for t in tracks] == ["Pno0", "Pno1", "Pno2"]

    from app.pipeline.tracks import annotate_instrument_names

    annotate_instrument_names(mid)
    pm2 = pretty_midi.PrettyMIDI(str(mid))
    assert [inst.name for inst in pm2.instruments] == ["Pno0", "Pno1", "Pno2"]


def test_write_subset_and_per_track(tmp_path: Path):
    mid = _multi_track_midi(tmp_path / "raw.mid")
    out = write_track_subset(mid, tmp_path / "v.mid", [1])
    pm = pretty_midi.PrettyMIDI(str(out))
    assert len(pm.instruments) == 1
    assert pm.instruments[0].program == 40
    assert len(pm.instruments[0].notes) == 1

    written = write_per_track_midis(mid, tmp_path / "tracks")
    assert len(written) == 3
    assert (tmp_path / "tracks" / "track_00.mid").is_file()


def test_parse_track_indices():
    assert parse_track_indices(None, track_count=3) is None
    assert parse_track_indices("", track_count=3) is None
    assert parse_track_indices("0,1,2", track_count=3) is None
    assert parse_track_indices("2,0", track_count=3) == [2, 0]
    with pytest.raises(TrackError):
        parse_track_indices("9", track_count=3)
    with pytest.raises(TrackError):
        parse_track_indices("x", track_count=3)


def test_subset_exports_musicxml_abc(tmp_path: Path):
    mid = _multi_track_midi(tmp_path / "raw.mid")
    subset = write_track_subset(mid, tmp_path / "piano.mid", [0])
    xml = midi_to_musicxml(subset, tmp_path / "piano.musicxml")
    assert "<score-partwise" in xml.read_text(encoding="utf-8")
    abc = midi_to_abc(subset, tmp_path / "piano.abc", title="Piano")
    text = abc.read_text(encoding="utf-8")
    assert text.lstrip().startswith("X:")
