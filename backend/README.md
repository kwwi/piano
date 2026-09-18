# Backend — 音频/视频转五线谱 (audio/video → MusicXML)

FastAPI service that turns an uploaded audio or video file into MusicXML:

```
upload → ffmpeg extract → MuScriptor (default) / MT3 / Basic Pitch / CREPE → MusicXML
```

MuScriptor is the default multi-instrument engine for **full mixes** (Demucs is
skipped for that model). The client (Flutter) renders MusicXML with Verovio.

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI endpoints (`/jobs`, `/jobs/{id}`, `/jobs/{id}/musicxml`) |
| `app/pipeline/extract.py` | ffmpeg audio extraction / normalisation |
| `app/pipeline/separate.py` | HT-Demucs vocal removal (two-stem `no_vocals`) |
| `app/pipeline/transcribe.py` | MuScriptor (default) / MT3 / Basic Pitch / CREPE → MIDI |
| `app/pipeline/muscriptor_runner.py` | MuScriptor load + multi-track MIDI write |
| `app/pipeline/mt3_runner.py` | mt3-infer load + 16 kHz resample + MIDI write |
| `app/pipeline/to_musicxml.py` | MuseScore CLI（优先）/ music21 → MusicXML |
| `app/pipeline/arrange_piano/` | 选轨 → lead → 钢琴编配（texture/rule）→ RH/LH |
| `app/pipeline/to_abc.py` | MIDI → standard ABC |
| `app/pipeline/to_pdf.py` | MusicXML → PDF (Verovio) |
| `app/pipeline/orchestrator.py` | chains the stages with progress reporting |
| `app/runner.py` | Celery (prod) or local thread-pool (dev) execution |
| `app/celery_app.py`, `app/tasks.py` | Celery worker path |

## Endpoints

- `POST /jobs` — multipart `file` + form `remove_vocals` (bool), `extract_melody` (bool), `model` (`muscriptor` default \| `mt3` \| `basic_pitch` \| `crepe`), optional `split_audio` / `split_seconds`. Always keeps **multi-track MIDI**; clients select tracks for MusicXML/MIDI export and in-app audition. Enforces the **100 MB** upload ceiling (HTTP 413 if exceeded). Returns `{job_id, status}`.
- `GET /jobs/{id}` — `{job_id, status, progress, stage, error}`.
- `GET /jobs/{id}/midi` — MIDI for selection tokens (`tracks=0,m0,c1`: source / melody / chords); omit for full multi-track. Add `arrange=piano` for playable piano reduction (`piano_style=pop|ballad|drive`, `piano_chords=auto|off`).
- `GET /jobs/{id}/midi/raw` — always full multi-track `transcription_raw.mid`.
- `GET /jobs/{id}/musicxml` — MusicXML for the same selection tokens (`arrange=piano` → piano grand-staff).
- `GET /jobs/{id}/tracks` — instrument list (`index`, `name`, `program`, `note_count`, …).
- `GET /jobs/{id}/abc` — standard ABC (`?tracks=` optional).
- `GET /jobs/{id}/pdf` — PDF engraved from that MusicXML (Verovio; needs SVG→PNG tool).

## Run locally (no broker needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # base API + music21 + verovio
pip install -r requirements-ml.txt       # heavy: muscriptor, basic-pitch, demucs, torch, mt3-infer
uvicorn app.main:app --reload
```

**MuScriptor** (default, `model=muscriptor`) is the recommended multi-instrument
engine for full mixes. First run downloads weights from Hugging Face after you:

1. Accept the CC BY-NC license on
   [muscriptor-medium](https://huggingface.co/MuScriptor/muscriptor-medium)
   (or small/large).
2. Put your token in ``backend/.env`` (copy from ``.env.example``):

```bash
cp .env.example .env
# edit .env → HF_TOKEN=hf_...
```

```bash
export DEFAULT_MODEL=muscriptor
export MUSCRIPTOR_SIZE=medium   # small (CPU) | medium | large (GPU)
export MUSCRIPTOR_DEVICE=auto
export MUSCRIPTOR_QUANTIZE=1    # default: snap MIDI to beat grid before score export
# HF_TOKEN is normally set in backend/.env (loaded automatically)
# export MUSESCORE_PATH="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
```

MuScriptor already windows audio in 5s chunks internally; external「分段转录」
and Demucs vocal extraction are skipped for this model.

**MIDI → MusicXML:** prefers **MuseScore CLI** (`mscore` / `MUSESCORE_PATH`) for
readable engraving; falls back to music21 when MuseScore is not installed.

MT3 remains available via **mt3-infer** (`model=mt3`: `mt3_pytorch` / `mr_mt3` /
`yourmt3`). Configure with:

```bash
export DEFAULT_MODEL=mt3
export MT3_INFER_MODEL=mt3_pytorch   # or mr_mt3
export MT3_DEVICE=auto               # auto | cpu | cuda
# export MT3_CHECKPOINT=/path/to/weights   # optional local override
# export SPLIT_AUDIO_DEFAULT=false         # or enable chunked transcription by default
# export SPLIT_SECONDS_DEFAULT=30
```

Long audio (MT3 / Basic Pitch) can be **split into fixed chunks** (UI: 分段转录),
transcribed per chunk, then MIDI timelines are merged before MusicXML.

**CREPE** (`model=crepe`): Demucs vocals → ``torchcrepe`` F0 → single Melody MIDI
track. Clients can still filter/export that track like any other job.

**Important:** keep `transformers` on **4.35–4.43.x** (see `requirements-ml.txt`).
`transformers` 5.x breaks mt3-infer (`T5Stack` missing `get_extended_attention_mask`).

If MuScriptor fails, the pipeline falls back to MT3 then Basic Pitch.
If mt3-infer is missing or fails, it falls back to Basic Pitch.

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
