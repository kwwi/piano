# Backend — 音频/视频转五线谱 (audio/video → MusicXML)

FastAPI service that turns an uploaded audio or video file into MusicXML:

```
upload → ffmpeg extract → HT-Demucs vocal removal → Basic Pitch / MT3 → music21 → MusicXML
```

The client (Flutter) renders the returned MusicXML to staff with Verovio.

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI endpoints (`/jobs`, `/jobs/{id}`, `/jobs/{id}/musicxml`) |
| `app/pipeline/extract.py` | ffmpeg audio extraction / normalisation |
| `app/pipeline/separate.py` | HT-Demucs vocal removal (two-stem `no_vocals`) |
| `app/pipeline/transcribe.py` | Basic Pitch (default) / MT3 (optional) → MIDI |
| `app/pipeline/to_musicxml.py` | music21 quantise + key/time inference → MusicXML |
| `app/pipeline/orchestrator.py` | chains the stages with progress reporting |
| `app/runner.py` | Celery (prod) or local thread-pool (dev) execution |
| `app/celery_app.py`, `app/tasks.py` | Celery worker path |

## Endpoints

- `POST /jobs` — multipart `file` + form `remove_vocals` (bool), `model` (`basic_pitch`\|`mt3`). Enforces the **100 MB** upload ceiling (HTTP 413 if exceeded). Returns `{job_id, status}`.
- `GET /jobs/{id}` — `{job_id, status, progress, stage, error}`.
- `GET /jobs/{id}/musicxml` — the resulting MusicXML file.

## Run locally (no broker needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # base API + music21 + verovio
pip install -r requirements-ml.txt       # heavy: basic-pitch, demucs, torch
uvicorn app.main:app --reload
```

Without a `CELERY_BROKER_URL`, jobs run on a local thread pool so the API is
fully self-contained for development and demos.

## Run with Docker (Celery + Redis)

```bash
docker compose up --build
```

`api` serves HTTP; `worker` (built with `INSTALL_ML=true`) runs the heavy models;
`redis` is the broker/result backend.

## Tests

```bash
pytest            # base suite; ML-only tests self-skip when deps are absent
```

The base suite validates the API lifecycle, ffmpeg extraction, and the
music21 MIDI→MusicXML stage for real. Installing `requirements-ml.txt` enables
the full audio→MusicXML integration test.

## Licensing

ffmpeg is expected to be the LGPL build. See `../docs/LICENSES.md`.
