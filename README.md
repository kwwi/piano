# 简谱 / 听音 / 音频 转五线谱

Android-first app that converts three kinds of input into **staff notation
(五线谱)**, all converging on **MusicXML** and engraved on-device with Verovio:

1. **简谱转五线谱** — numbered-notation (jianpu) text → staff (offline).
2. **听音转五线谱** — microphone → real-time monophonic pitch → staff (on-device).
3. **上传音频/视频转五线谱** — upload a file (≤100 MB); the backend extracts
   audio, removes vocals, transcribes, and returns MusicXML.

```
        ┌────────────── Flutter client (Android) ──────────────┐
1  简谱 →│ jianpu_core (Dart DSL→IR→MusicXML/MIDI)               │
2  麦克风→│ record + pitch_detector + MelodyTranscriber → MusicXML │→ Verovio → 五线谱
3  文件 →│ upload ──────────────────────┐                        │   + 导出 MusicXML/MIDI/PDF
        └─────────────────────────────┼────────────────────────┘
                                        ▼ HTTPS (≤100MB)
        ┌──────────────── Python backend (heavy compute) ───────┐
        │ FastAPI + Celery/Redis                                 │
        │ ffmpeg 提取 → HT-Demucs 去人声 → Basic Pitch/MT3 → music21 │→ MusicXML
        └───────────────────────────────────────────────────────┘
```

## Repository layout

| Path | What |
| --- | --- |
| [`packages/jianpu_core`](packages/jianpu_core) | Pure-Dart engine: DSL parser, editable IR, pitch resolution, MusicXML + MIDI builders, monophonic transcriber. **23 unit tests** (`dart test`). |
| [`app`](app) | Flutter app: home + three feature screens, Verovio rendering, export, backend client. |
| [`backend`](backend) | FastAPI + Celery pipeline: ffmpeg → Demucs → Basic Pitch/MT3 → music21. Docker/compose. |
| [`docs/LICENSES.md`](docs/LICENSES.md) | Component / license notes (mature stacks preferred; GPL allowed when useful). |

## Data-format convergence

Every input path produces **MusicXML**, so rendering (Verovio) and export
(MusicXML / MIDI / PDF) are shared across all three features. The jianpu path
also keeps an **editable IR** (`JianpuScore`) as the source of truth so users can
tweak the recognised/entered notation before conversion.

## Quick start

```bash
# Core engine tests (Dart SDK only)
cd packages/jianpu_core && dart pub get && dart test

# Backend (standalone, no broker needed)
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pytest
uvicorn app.main:app --reload

# App
cd app && flutter pub get && flutter run
```

## Tech stack & licensing

See [`docs/LICENSES.md`](docs/LICENSES.md) for the current component list.
Mature stacks (OpenCV OMR, Demucs vocals, librosa/aubio beat quantize,
jianpu-ly) are preferred for quality; GPL components may be used when they
are the better tool.
