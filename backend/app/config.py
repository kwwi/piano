"""Runtime configuration for the transcription backend."""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent


def _load_dotenv() -> None:
    """Load KEY=VALUE from ``backend/.env`` and repo ``.env`` (no python-dotenv).

    Existing process environment wins. Later files do not override earlier keys
    already present in ``os.environ``; both files are read so either location works.
    """
    for env_path in (_BACKEND_ROOT / ".env", _REPO_ROOT / ".env"):
        if not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = val.strip().strip("'").strip('"')


_load_dotenv()

# Root directory where uploads and results are stored.
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", _BACKEND_ROOT / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Hard upload ceiling (bytes). Mirrors the client-side guard: 100 MB.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

# Celery / Redis. When CELERY_BROKER_URL is unset, the API runs jobs in a local
# background thread pool so it works standalone (dev/demo/tests) with no broker.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL or "")

# Default transcription model:
#   muscriptor   — multi-instrument full-mix (Kyutai×Mirelo; recommended)
#   mt3          — mt3-infer PyTorch ports
#   basic_pitch  — light polyphonic
#   crepe        — monophonic F0 (vocals)
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "muscriptor")

# MuScriptor (model=muscriptor). Size: small | medium | large.
# Weights are CC BY-NC — accept HF license; put HF_TOKEN in backend/.env.
MUSCRIPTOR_SIZE = os.getenv("MUSCRIPTOR_SIZE", "medium").strip().lower()
MUSCRIPTOR_DEVICE = os.getenv("MUSCRIPTOR_DEVICE", "auto").strip().lower()
MUSCRIPTOR_QUANTIZE = os.getenv("MUSCRIPTOR_QUANTIZE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Hugging Face token for gated MuScriptor weights (also read as HF_TOKEN).
HF_TOKEN = (
    os.getenv("HF_TOKEN", "").strip()
    or os.getenv("HUGGING_FACE_HUB_TOKEN", "").strip()
)
if HF_TOKEN:
    # huggingface_hub / muscriptor download path.
    os.environ.setdefault("HF_TOKEN", HF_TOKEN)
    os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", HF_TOKEN)

# mt3-infer (PyTorch MT3 family). Used when model=mt3.
# Variants: mt3_pytorch (default/accuracy), mr_mt3 (faster), yourmt3 (8-stem).
MT3_INFER_MODEL = os.getenv("MT3_INFER_MODEL", "mt3_pytorch")
# Device: auto | cpu | cuda
MT3_DEVICE = os.getenv("MT3_DEVICE", "auto")
# Optional local checkpoint override; empty → auto-download into package cache.
MT3_CHECKPOINT = os.getenv("MT3_CHECKPOINT", "").strip()
MT3_SAMPLE_RATE = int(os.getenv("MT3_SAMPLE_RATE", "16000"))

# Split long audio into chunks before transcription (helps MT3 on long mixes).
SPLIT_AUDIO_DEFAULT = os.getenv("SPLIT_AUDIO_DEFAULT", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SPLIT_SECONDS_DEFAULT = float(os.getenv("SPLIT_SECONDS_DEFAULT", "30"))
SPLIT_OVERLAP_SECONDS = float(os.getenv("SPLIT_OVERLAP_SECONDS", "1.0"))

# Arrangement is always multi-track model output. Kept for API/env compat;
# non-full values are ignored by the pipeline (client selects tracks instead).
ARRANGEMENT_DEFAULT = os.getenv("ARRANGEMENT_DEFAULT", "full").strip().lower()

# torchcrepe (model=crepe): monophonic F0 → Melody MIDI (best on Demucs vocals).
# Default ``tiny`` — ``full`` on CPU can take tens of minutes for a 5‑minute song.
CREPE_MODEL = os.getenv("CREPE_MODEL", "tiny").strip().lower()  # tiny | full
CREPE_DEVICE = os.getenv("CREPE_DEVICE", "auto").strip().lower()  # auto | cpu | cuda
CREPE_SAMPLE_RATE = int(os.getenv("CREPE_SAMPLE_RATE", "16000"))
CREPE_HOP_LENGTH = int(os.getenv("CREPE_HOP_LENGTH", "160"))  # 10 ms @ 16 kHz
CREPE_FMIN = float(os.getenv("CREPE_FMIN", "50"))
CREPE_FMAX = float(os.getenv("CREPE_FMAX", "1100"))
CREPE_PERIODICITY = float(os.getenv("CREPE_PERIODICITY", "0.35"))
CREPE_MIN_DUR = float(os.getenv("CREPE_MIN_DUR", "0.06"))
CREPE_CHUNK_SECONDS = float(os.getenv("CREPE_CHUNK_SECONDS", "20"))
CREPE_TORCH_THREADS = int(os.getenv("CREPE_TORCH_THREADS", "2"))
# After CREPE melody, optionally run Basic Pitch on the full mix for chord
# estimation. Disabled by default — a second full-mix pass is as heavy as CREPE.
CREPE_HARMONY_BP = os.getenv("CREPE_HARMONY_BP", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CREPE_HARMONY_MAX_SECONDS = float(os.getenv("CREPE_HARMONY_MAX_SECONDS", "90"))

# Demucs model tier for vocal removal.
DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "htdemucs")
# Audio extensions we treat as video (audio is extracted server-side).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
