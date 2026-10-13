# Backend — 音频/视频转五线谱 (audio/video → MusicXML)

FastAPI service that turns an uploaded audio or video file into MusicXML:

```
upload → ffmpeg extract → MuScriptor (default) / MT3 / Basic Pitch / CREPE → MIDI
       → MIDI2ScoreTransformer (pitched) / music21 rules (drums) → MusicXML
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
| `app/pipeline/score_m2s/` | MIDI2ScoreTransformer worker client + score_mode 分发 + MusicXML 合并 |
| `app/pipeline/to_musicxml.py` | music21 规则 MIDI → MusicXML（鼓轨 / 非 M2S 轨） |
| `m2s_worker/` | M2S 常驻 worker（独立 Python 3.11 venv）+ `setup_m2s.sh` |
| `app/pipeline/arrange_piano/` | 选轨 → lead → 钢琴编配（texture/rule）→ RH/LH |
| `app/pipeline/to_abc.py` | MIDI → standard ABC |
| `app/pipeline/to_pdf.py` | MusicXML → PDF (Verovio) |
| `app/pipeline/orchestrator.py` | chains the stages with progress reporting |
| `app/runner.py` | Celery (prod) or local thread-pool (dev) execution |
| `app/celery_app.py`, `app/tasks.py` | Celery worker path |

## Endpoints

- `POST /jobs` — multipart `file` + form `remove_vocals` (bool), `extract_melody` (bool), `model` (`muscriptor` default \| `mt3` \| `basic_pitch` \| `crepe`), optional `split_audio` / `split_seconds` / `score_mode`. Always keeps **multi-track MIDI**; clients select tracks for MusicXML/MIDI export and in-app audition. Enforces the **100 MB** upload ceiling (HTTP 413 if exceeded). Returns `{job_id, status}`.
- `GET /jobs/{id}` — `{job_id, status, progress, stage, error}`.
- `GET /jobs/{id}/midi` — MIDI for selection tokens (`tracks=0,m0,c1`: source / melody / chords); omit for full multi-track. Add `arrange=piano` for playable piano reduction (`piano_style=pop|ballad|drive`, `piano_chords=auto|off`).
- `GET /jobs/{id}/midi/raw` — always full multi-track `transcription_raw.mid`.
- `GET /jobs/{id}/musicxml` — MusicXML for the same selection tokens (`arrange=piano` → piano grand-staff); `score_mode=per_track|piano_only|reduce_all`.
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
export MUSCRIPTOR_QUANTIZE=0    # default: keep performance timing for M2S
# HF_TOKEN is normally set in backend/.env (loaded automatically)
```

MuScriptor already windows audio in 5s chunks internally; external「分段转录」
and Demucs vocal extraction are skipped for this model.

### MIDI → MusicXML: MIDI2ScoreTransformer (required)

Pitched tracks are engraved by
[MIDI2ScoreTransformer](https://github.com/TimFelixBeyer/MIDI2ScoreTransformer)
(M2S). It needs Python 3.11 and a patched music21 fork, so it runs as a
long-lived worker in its **own venv**; the API talks to it over JSON lines.
Drum tracks use the music21 rule path (`to_musicxml.py`).

```bash
# needs python3.11 on PATH (or PYTHON311=/path/to/python3.11)
bash m2s_worker/setup_m2s.sh        # venv + repo @115432b + deps + MIDI2ScoreTF.ckpt (~390 MB)
```

Everything lands in `backend/.m2s/` (the defaults for `M2S_PYTHON`, `M2S_ROOT`,
`M2S_CKPT`). Override in `backend/.env` if installed elsewhere; `M2S_DEVICE`
picks `cuda` / `mps` / `cpu` (default `auto` = CUDA if present, else CPU — on
Apple silicon CPU decoding is >10× faster than MPS; a 6-minute MuScriptor
transcription engraves in ~40 s per_track on an M-series CPU). There is **no fallback**: if the
worker cannot start, MusicXML requests fail with an explicit error.
`GET /` reports `m2s_ready`.

Score generation mode (`score_mode`, UI「谱面生成」):

| mode | behaviour |
| --- | --- |
| `per_track` (default) | every non-drum track → its own M2S grand-staff part; drums via rules |
| `piano_only` | GM piano tracks (program 0–7) via M2S, other tracks via rules |
| `reduce_all` | all non-drum tracks merged → one M2S piano score; drums dropped |

`arrange=piano` output always goes through M2S. Parts are merged at XML level
(ids renumbered, short parts padded with empty measures); meters are inferred
per track and are not force-aligned.

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

If MuScriptor fails, the job errors with ``MuScriptor 暂时不可用`` (no MT3 /
Basic Pitch fallback). Users may still pick ``model=mt3`` / ``basic_pitch`` /
``crepe`` explicitly. If mt3-infer is missing or fails, it falls back to Basic Pitch.

## Run with Docker (Celery + Redis)

```bash
docker compose up --build
```

`api` serves HTTP; `worker` (built with `INSTALL_ML=true`) runs the heavy models;
`redis` is the broker/result backend. Both images install MIDI2ScoreTransformer
under `/opt/m2s` (build arg `INSTALL_M2S=true`, default).

## Tests

```bash
pytest            # base suite; ML-only tests self-skip when deps are absent
```

The base suite validates the API lifecycle, ffmpeg extraction, and the
music21 rule MIDI→MusicXML stage for real. MIDI2ScoreTransformer is replaced by
a fake worker speaking the same JSON-lines protocol (`tests/fake_m2s_worker.py`),
so the suite does not need the M2S venv. Installing `requirements-ml.txt`
enables the full audio→MusicXML integration test.

## Licensing

ffmpeg is expected to be the LGPL build. See `../docs/LICENSES.md`.
