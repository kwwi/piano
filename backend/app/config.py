"""Runtime configuration for the transcription backend."""
from __future__ import annotations

import os
from pathlib import Path

# Root directory where uploads and results are stored.
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", Path(__file__).resolve().parent.parent / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Hard upload ceiling (bytes). Mirrors the client-side guard: 100 MB.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

# Celery / Redis. When CELERY_BROKER_URL is unset, the API runs jobs in a local
# background thread pool so it works standalone (dev/demo/tests) with no broker.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL or "")

# Default transcription model: "mt3" (high accuracy) or "basic_pitch" (light).
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "mt3")

# Demucs model tier for vocal removal.
DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "htdemucs")

# Audio extensions we treat as video (audio is extracted server-side).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
