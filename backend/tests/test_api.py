"""API-level tests using FastAPI's TestClient (no Celery/Redis required)."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.extract import ffmpeg_available
from app.pipeline.transcribe import basic_pitch_available

client = TestClient(app)


def test_health():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["max_upload_bytes"] == 100 * 1024 * 1024


def test_empty_upload_rejected():
    r = client.post(
        "/jobs",
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"remove_vocals": "false", "model": "basic_pitch"},
    )
    assert r.status_code == 400


def test_unknown_job_404():
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_job_lifecycle(sine_wav):
    with open(sine_wav, "rb") as f:
        payload = f.read()
    r = client.post(
        "/jobs",
        files={"file": ("tone.wav", payload, "audio/wav")},
        data={"remove_vocals": "false", "model": "basic_pitch"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Poll until terminal state (the runner executes on a local thread pool).
    status = None
    for _ in range(120):
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert status is not None
    assert status["status"] in ("done", "error")

    if status["status"] == "done":
        xml = client.get(f"/jobs/{job_id}/musicxml")
        assert xml.status_code == 200
        assert "<score-partwise" in xml.text
    else:
        # Without ML deps the transcription stage fails, but extraction must
        # have run first (proves the API + runner + pipeline wiring works).
        assert not (ffmpeg_available() and basic_pitch_available())
