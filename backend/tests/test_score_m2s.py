"""MIDI2ScoreTransformer integration: worker protocol, routing, MusicXML merge, API."""
import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pretty_midi
import pytest
from fastapi.testclient import TestClient

from app.pipeline.score_m2s import client as m2s_client
from app.pipeline.score_m2s import (
    M2SError,
    ScoreRouteError,
    build_score_xml_from_midi,
    merge_musicxml,
    normalize_score_mode,
    reshape_midi_for_score_mode,
)
from app.pipeline.score_m2s.musicxml_merge import empty_part_score
from app.pipeline.tracks import write_tracks_manifest

from conftest import make_fake_m2s_client


def _band_midi(path: Path) -> Path:
    """Piano (prog 0), guitar (prog 25), drums."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(program=0, name="Piano")
    guitar = pretty_midi.Instrument(program=25, name="Guitar")
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    for i in range(8):
        t = i * 0.5
        piano.notes.append(pretty_midi.Note(90, 60 + (i % 5), t, t + 0.45))
        guitar.notes.append(pretty_midi.Note(80, 52 + (i % 3), t, t + 0.45))
        drums.notes.append(pretty_midi.Note(100, 36 if i % 2 == 0 else 38, t, t + 0.1))
    pm.instruments.extend([piano, guitar, drums])
    pm.write(str(path))
    return path


def _requests(client) -> list[dict]:
    log = Path(client.request_log)
    if not log.is_file():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln]


def _parts(xml_path: Path) -> list[tuple[str, str]]:
    root = ET.parse(str(xml_path)).getroot()
    names = {
        sp.get("id"): (sp.findtext("part-name") or "")
        for sp in root.find("part-list").findall("score-part")
    }
    return [(p.get("id"), names.get(p.get("id"), "")) for p in root.findall("part")]


# --------------------------------------------------------------------- client
def test_client_converts_and_reuses_worker(tmp_path):
    client = make_fake_m2s_client(tmp_path)
    try:
        mid = _band_midi(tmp_path / "band.mid")
        out1 = client.convert(mid, tmp_path / "a.musicxml", name="Guitar")
        pid = client._proc.pid
        out2 = client.convert(mid, tmp_path / "b.musicxml")
        assert client._proc.pid == pid  # persistent process
        assert "<part-name>Guitar</part-name>" in out1.read_text(encoding="utf-8")
        assert out2.is_file()
        assert client.ping()
        assert client.device == "cpu"
    finally:
        client.close()
    assert not client.running


def test_client_not_ready_raises(tmp_path):
    client = make_fake_m2s_client(tmp_path, mode="not_ready")
    with pytest.raises(M2SError, match="checkpoint missing"):
        client.convert(_band_midi(tmp_path / "x.mid"), tmp_path / "x.musicxml")


def test_client_timeout_kills_worker(tmp_path):
    client = make_fake_m2s_client(tmp_path, mode="hang", timeout=1.0)
    with pytest.raises(M2SError, match="超时"):
        client.convert(_band_midi(tmp_path / "x.mid"), tmp_path / "x.musicxml")
    assert not client.running
    assert client.last_error


def test_client_restarts_after_crash(tmp_path):
    client = make_fake_m2s_client(tmp_path, mode="crash_once")
    try:
        out = client.convert(_band_midi(tmp_path / "x.mid"), tmp_path / "x.musicxml")
        assert out.is_file()
        assert (tmp_path / "fake_m2s_crashed").is_file()
        assert client.running
    finally:
        client.close()


def test_get_client_requires_install(tmp_path, monkeypatch):
    from app import config

    m2s_client.set_client(None)
    monkeypatch.setattr(config, "M2S_PYTHON", str(tmp_path / "missing-python"))
    with pytest.raises(M2SError, match="setup_m2s.sh"):
        m2s_client.get_client()
    status = m2s_client.status()
    assert status["m2s_ready"] is False
    assert "M2S_PYTHON" in status["m2s_error"]


# --------------------------------------------------------------------- router
def test_normalize_score_mode():
    assert normalize_score_mode("per-track") == "per_track"
    assert normalize_score_mode("reduce") == "reduce_all"
    assert normalize_score_mode(None) in ("per_track", "piano_only", "reduce_all")
    with pytest.raises(ScoreRouteError):
        normalize_score_mode("nope")


def test_reshape_midi_for_score_modes(tmp_path):
    mid = _band_midi(tmp_path / "band.mid")
    per = reshape_midi_for_score_mode(mid, tmp_path / "per.mid", score_mode="per_track")
    assert len(pretty_midi.PrettyMIDI(str(per)).instruments) == 3

    piano = reshape_midi_for_score_mode(mid, tmp_path / "po.mid", score_mode="piano_only")
    po = pretty_midi.PrettyMIDI(str(piano))
    assert len(po.instruments) == 1
    assert int(po.instruments[0].program) == 0
    assert not po.instruments[0].is_drum

    red = reshape_midi_for_score_mode(mid, tmp_path / "red.mid", score_mode="reduce_all")
    rm = pretty_midi.PrettyMIDI(str(red))
    assert len(rm.instruments) == 1
    assert not rm.instruments[0].is_drum
    assert len(rm.instruments[0].notes) == 16  # piano + guitar


def test_per_track_routes_drums_to_rules(tmp_path, fake_m2s):
    mid = _band_midi(tmp_path / "band.mid")
    out = build_score_xml_from_midi(mid, tmp_path / "per.musicxml", score_mode="per_track")
    parts = _parts(out)
    assert [pid for pid, _ in parts] == ["P1", "P2", "P3"]
    assert [name for _, name in parts] == ["Piano", "Guitar", "Drums"]
    reqs = _requests(fake_m2s)
    assert sorted(r["name"] for r in reqs) == ["Guitar", "Piano"]


def test_piano_only_sends_only_piano_programs(tmp_path, fake_m2s):
    mid = _band_midi(tmp_path / "band.mid")
    out = build_score_xml_from_midi(mid, tmp_path / "po.musicxml", score_mode="piano_only")
    assert len(_parts(out)) == 3
    assert [r["name"] for r in _requests(fake_m2s)] == ["Piano"]


def test_reduce_all_outputs_single_part(tmp_path, fake_m2s):
    mid = _band_midi(tmp_path / "band.mid")
    out = build_score_xml_from_midi(mid, tmp_path / "red.musicxml", score_mode="reduce_all")
    assert _parts(out) == [("P1", "Piano")]
    reqs = _requests(fake_m2s)
    assert len(reqs) == 1
    merged = pretty_midi.PrettyMIDI(reqs[0]["midi"])
    assert len(merged.instruments) == 1
    assert not merged.instruments[0].is_drum
    assert len(merged.instruments[0].notes) == 16  # piano + guitar, no drums


def test_arranged_piano_always_m2s(tmp_path, fake_m2s):
    pm = pretty_midi.PrettyMIDI(initial_tempo=100)
    for name, pitch in (("Piano RH", 72), ("Piano LH", 48)):
        inst = pretty_midi.Instrument(program=0, name=name)
        inst.notes.append(pretty_midi.Note(80, pitch, 0.0, 1.0))
        pm.instruments.append(inst)
    mid = tmp_path / "arr.mid"
    pm.write(str(mid))
    out = build_score_xml_from_midi(
        mid, tmp_path / "arr.musicxml", score_mode="piano_only", arranged_piano=True
    )
    assert _parts(out) == [("P1", "Piano")]
    assert len(_requests(fake_m2s)) == 1


def test_router_caches_per_track_results(tmp_path, fake_m2s):
    mid = _band_midi(tmp_path / "band.mid")
    cache = tmp_path / "cache"
    build_score_xml_from_midi(mid, tmp_path / "1.musicxml", score_mode="per_track", cache_dir=cache)
    n = len(_requests(fake_m2s))
    build_score_xml_from_midi(mid, tmp_path / "2.musicxml", score_mode="per_track", cache_dir=cache)
    assert len(_requests(fake_m2s)) == n


def test_router_surfaces_m2s_errors(tmp_path):
    m2s_client.set_client(make_fake_m2s_client(tmp_path, mode="not_ready"))
    try:
        with pytest.raises(M2SError):
            build_score_xml_from_midi(
                _band_midi(tmp_path / "band.mid"), tmp_path / "x.musicxml", score_mode="per_track"
            )
    finally:
        m2s_client.set_client(None)


# ---------------------------------------------------------------------- merge
def _one_part(path: Path, name: str, measures: int, part_id: str = "P1") -> Path:
    body = "".join(
        f'<measure number="{i + 1}">'
        + (
            "<attributes><divisions>2</divisions><time><beats>3</beats>"
            "<beat-type>4</beat-type></time></attributes>"
            if i == 0
            else ""
        )
        + "<note><pitch><step>E</step><octave>4</octave></pitch><duration>6</duration></note>"
        "</measure>"
        for i in range(measures)
    )
    path.write_text(
        '<?xml version="1.0"?><score-partwise version="3.1"><part-list>'
        '<part-group number="1" type="start"><group-symbol>brace</group-symbol></part-group>'
        f'<score-part id="{part_id}"><part-name>{name}</part-name>'
        f'<score-instrument id="{part_id}-I1"><instrument-name>x</instrument-name></score-instrument>'
        f'<midi-instrument id="{part_id}-I1"><midi-channel>1</midi-channel></midi-instrument>'
        '</score-part><part-group number="1" type="stop"/></part-list>'
        f'<part id="{part_id}">{body}</part></score-partwise>',
        encoding="utf-8",
    )
    return path


def test_merge_renumbers_parts_and_pads(tmp_path):
    a = _one_part(tmp_path / "a.xml", "Violin", 3)
    b = _one_part(tmp_path / "b.xml", "Cello", 1)
    out = merge_musicxml([a, b], tmp_path / "m.musicxml")
    root = ET.parse(str(out)).getroot()
    sps = root.find("part-list").findall("score-part")
    assert [sp.get("id") for sp in sps] == ["P1", "P2"]
    assert [sp.find("score-instrument").get("id") for sp in sps] == ["P1-I1", "P2-I1"]
    assert [sp.find("midi-instrument").get("id") for sp in sps] == ["P1-I1", "P2-I1"]
    groups = [g.get("number") for g in root.find("part-list").findall("part-group")]
    assert groups == ["1", "1", "2", "2"]
    parts = root.findall("part")
    assert [p.get("id") for p in parts] == ["P1", "P2"]
    assert [len(p.findall("measure")) for p in parts] == [3, 3]
    padded = parts[1].findall("measure")[-1]
    assert padded.get("number") == "3"
    rest = padded.find("note")
    assert rest.find("rest").get("measure") == "yes"
    assert rest.findtext("duration") == "6"  # 3/4 at divisions=2
    assert "<!DOCTYPE score-partwise" in out.read_text(encoding="utf-8")


def test_merge_part_name_override_and_empty_placeholder(tmp_path):
    a = _one_part(tmp_path / "a.xml", "Old", 2)
    e = empty_part_score("Strings", tmp_path / "e.xml")
    out = merge_musicxml([a, e], tmp_path / "m.musicxml", part_names=["Lead", None])
    names = [n for _, n in _parts(out)]
    assert names == ["Lead", "Strings"]
    parts = ET.parse(str(out)).getroot().findall("part")
    assert len(parts[1].findall("measure")) == 2


# ------------------------------------------------------------------------ API
def _done_job(tmp_path) -> str:
    from app.schemas import JobState
    from app.store import store

    job_id = uuid.uuid4().hex
    store.create(job_id)
    job_dir = store.job_dir(job_id)
    raw = _band_midi(job_dir / "transcription_raw.mid")
    (job_dir / "transcription.mid").write_bytes(raw.read_bytes())
    write_tracks_manifest(raw, job_dir / "tracks.json")
    store.update(job_id, status=JobState.done, progress=1.0, result_path=None)
    return job_id


def test_api_musicxml_score_mode_and_cache_keys(tmp_path, fake_m2s):
    from app.main import app
    from app.store import store

    api = TestClient(app)
    job_id = _done_job(tmp_path)
    exports = store.job_dir(job_id) / "exports"

    r = api.get(f"/jobs/{job_id}/musicxml", params={"tracks": "0,1", "score_mode": "per_track"})
    assert r.status_code == 200
    assert (exports / "sel_0_1_per_track.musicxml").is_file()
    assert (exports / "full_per_track.musicxml").is_file()  # filter fast path
    assert r.text.count("<score-part ") == 2

    r = api.get(f"/jobs/{job_id}/musicxml", params={"tracks": "0,1", "score_mode": "reduce_all"})
    assert r.status_code == 200
    assert (exports / "sel_0_1_reduce_all.musicxml").is_file()
    assert not (exports / "full_reduce_all.musicxml").exists()  # regenerated, not filtered
    assert r.text.count("<score-part ") == 1

    r = api.get(f"/jobs/{job_id}/musicxml", params={"score_mode": "piano_only"})
    assert r.status_code == 200
    assert (exports / "full_piano_only.musicxml").is_file()
    assert r.text.count("<score-part ") == 3

    r = api.get(f"/jobs/{job_id}/musicxml", params={"score_mode": "wat"})
    assert r.status_code == 400


def test_api_midi_score_mode_matches_audition_shape(tmp_path, fake_m2s):
    from app.main import app
    from app.store import store

    api = TestClient(app)
    job_id = _done_job(tmp_path)

    r = api.get(f"/jobs/{job_id}/midi", params={"score_mode": "reduce_all"})
    assert r.status_code == 200
    red = tmp_path / "resp_reduce.mid"
    red.write_bytes(r.content)
    pm = pretty_midi.PrettyMIDI(str(red))
    assert len(pm.instruments) == 1
    assert not pm.instruments[0].is_drum
    assert (store.job_dir(job_id) / "exports" / "sel_all_reduce_all.mid").is_file()

    r = api.get(f"/jobs/{job_id}/midi", params={"tracks": "0,1", "score_mode": "piano_only"})
    assert r.status_code == 200
    po = tmp_path / "resp_piano.mid"
    po.write_bytes(r.content)
    pm = pretty_midi.PrettyMIDI(str(po))
    assert len(pm.instruments) == 1
    assert int(pm.instruments[0].program) == 0


def test_api_musicxml_m2s_missing_is_503(tmp_path):
    from app.main import app

    m2s_client.set_client(make_fake_m2s_client(tmp_path, mode="not_ready"))
    try:
        api = TestClient(app)
        job_id = _done_job(tmp_path)
        r = api.get(f"/jobs/{job_id}/musicxml", params={"tracks": "1", "score_mode": "per_track"})
        assert r.status_code == 503
        assert "checkpoint missing" in r.json()["detail"]
    finally:
        m2s_client.set_client(None)
