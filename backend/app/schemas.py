"""Pydantic models and the job state machine."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class JobState(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    error = "error"


class JobCreated(BaseModel):
    job_id: str
    status: JobState = JobState.queued


class JobStatus(BaseModel):
    job_id: str
    status: JobState
    progress: float = 0.0  # 0..1
    stage: str | None = None
    error: str | None = None
