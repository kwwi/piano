"""Tests for arrange_for_piano (M1 rule + M2 texture)."""
from pathlib import Path

import pretty_midi
import pytest

from app.pipeline.arrange_piano import arrange_for_piano
from app.pipeline.arrange_piano.fallback_rule import arrange_rule
from app.pipeline.arrange_piano.lead_input import build_lead_midi
from app.pipeline.arrange_piano.postprocess import postprocess_piano_midi
from app.pipeline.arrange_piano.texture_model import arrange_texture
from app.pipeline.track_derive import parse_track_selection


def _guitarish_job(tmp_path: Path) -> Path:
    job = tmp_path / "job"
    job.mkdir()
    pm = pretty_midi.PrettyMIDI(initial_tempo=100)
    gtr = pretty_midi.Instrument(program=25, name="Guitar")
    # Busy strumming-ish texture + melody on top.
    for bar in range(4):
        t0 = bar * 2.4
        for i, pitch in enumerate([52, 55, 59, 64, 67, 71]):
            gtr.notes.append(
                pretty_midi.Note(75, pitch, t0 + i * 0.2, t0 + i * 0.2 + 0.18)
            )
        gtr.notes.append(pretty_midi.Note(95, 76, t0, t0 + 0.8))
        gtr.notes.append(pretty_midi.Note(95, 74, t0 + 0.8, t0 + 1.6))
        gtr.notes.append(pretty_midi.Note(95, 72, t0 + 1.6, t0 + 2.4))
    pm.instruments.append(gtr)
    mid = job / "transcription.mid"
    pm.write(str(mid))
    (job / "transcription_raw.mid").write_bytes(mid.read_bytes())
    return job


def test_lead_and_rule_arrange(tmp_path: Path):
    job = _guitarish_job(tmp_path)
    sel = parse_track_selection("m0,c0", track_count=1)
    lead = build_lead_midi(job, sel, job / "derived" / "lead.mid", auto_chords=True)
    pm = pretty_midi.PrettyMIDI(str(lead))
    names = [(i.name or "").lower() for i in pm.instruments]
    assert any("melody" in n for n in names)

    raw = arrange_rule(lead, job / "derived" / "rule.mid")
    rpm = pretty_midi.PrettyMIDI(str(raw))
    assert len(rpm.instruments) == 2
    assert sum(len(i.notes) for i in rpm.instruments) > 0

    out = postprocess_piano_midi(raw, job / "exports" / "piano.mid")
    opm = pretty_midi.PrettyMIDI(str(out))
    assert [i.name for i in opm.instruments] == ["Piano RH", "Piano LH"]
    for inst in opm.instruments:
        for n in inst.notes:
            assert 21 <= n.pitch <= 108


def test_texture_arrange(tmp_path: Path):
    job = _guitarish_job(tmp_path)
    sel = parse_track_selection("0", track_count=1)
    lead = build_lead_midi(job, sel, job / "derived" / "lead2.mid", auto_chords=True)
    out = arrange_texture(lead, job / "derived" / "tex.mid", style="pop")
    pm = pretty_midi.PrettyMIDI(str(out))
    assert any(i.notes for i in pm.instruments)
    assert any("RH" in (i.name or "") for i in pm.instruments)


def test_arrange_for_piano_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PIANO_ARRANGER_BACKEND", "texture")
    # Re-import config values used inside arrange_for_piano via module attrs.
    import app.config as cfg

    monkeypatch.setattr(cfg, "PIANO_ARRANGER_BACKEND", "texture")
    monkeypatch.setattr(cfg, "PIANO_ARRANGER_STYLE", "pop")
    monkeypatch.setattr(cfg, "PIANO_ARRANGER_AUTO_CHORDS", True)

    job = _guitarish_job(tmp_path)
    sel = parse_track_selection("m0,c0", track_count=1)
    out = arrange_for_piano(job, sel, job / "exports" / "piano_final.mid")
    assert out.is_file()
    pm = pretty_midi.PrettyMIDI(str(out))
    assert len(pm.instruments) == 2
    assert sum(len(i.notes) for i in pm.instruments) >= 4


def test_arrange_rule_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "PIANO_ARRANGER_BACKEND", "rule")
    monkeypatch.setattr(cfg, "PIANO_ARRANGER_STYLE", "pop")
    monkeypatch.setattr(cfg, "PIANO_ARRANGER_AUTO_CHORDS", True)

    job = _guitarish_job(tmp_path)
    out = arrange_for_piano(
        job, None, job / "exports" / "piano_all.mid", backend="rule"
    )
    pm = pretty_midi.PrettyMIDI(str(out))
    assert pm.instruments
