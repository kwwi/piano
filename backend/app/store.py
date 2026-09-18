"""In-process job store used when running without Celery/Redis.

Keeps job status in memory and results on disk under ``STORAGE_DIR``. For
production scale the same jobs are executed by Celery workers; this store keeps
the API self-contained for local dev, demos and tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import STORAGE_DIR
from .schemas import JobState


@dataclass
class Job:
    id: str
    status: JobState = JobState.queued
    progress: float = 0.0
    stage: str | None = None
    error: str | None = None
    result_path: Path | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str) -> Job:
        with self._lock:
            job = Job(id=job_id)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for k, v in changes.items():
                setattr(job, k, v)

    def job_dir(self, job_id: str) -> Path:
        d = STORAGE_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d


store = JobStore()
