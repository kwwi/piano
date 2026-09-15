"""Executes pipeline jobs, updating the job store as it goes.

Uses Celery when a broker is configured; otherwise runs the job on a local
thread pool so the API works standalone.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import CELERY_BROKER_URL, STORAGE_DIR
from .pipeline.orchestrator import run_pipeline
from .schemas import JobState
from .store import store

# librosa/numba (pulled in by Basic Pitch) fails in worker threads when it
# cannot write a function cache next to the installed package. Point the cache
# at a writable directory under our storage root before any ML import happens.
_numba_cache = STORAGE_DIR / ".numba_cache"
_numba_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(_numba_cache))

_executor = ThreadPoolExecutor(max_workers=2)


def _run(job_id: str, input_path: str, remove_vocals: bool, model: str) -> None:
    store.update(job_id, status=JobState.processing, stage="extract", progress=0.01)
    job_dir = store.job_dir(job_id)
    try:
        def progress(stage: str, value: float) -> None:
            store.update(job_id, stage=stage, progress=value)

        xml = run_pipeline(
            input_path,
            job_dir,
            remove_vocals_first=remove_vocals,
            model=model,
            # In dev/demo without the Demucs weights, don't hard-fail: fall back
            # to analysing the full mix so the pipeline still yields a score.
            allow_separation_passthrough=True,
            on_progress=progress,
        )
        store.update(
            job_id,
            status=JobState.done,
            stage="done",
            progress=1.0,
            result_path=Path(xml),
        )
    except Exception as exc:  # noqa: BLE001 - surface any stage failure to client
        store.update(job_id, status=JobState.error, error=str(exc))


def submit(job_id: str, input_path: str, remove_vocals: bool, model: str) -> None:
    """Enqueue a job for execution."""
    if CELERY_BROKER_URL:
        from .tasks import process_job  # local import to avoid celery at import time

        process_job.delay(job_id, input_path, remove_vocals, model)
    else:
        _executor.submit(_run, job_id, input_path, remove_vocals, model)
