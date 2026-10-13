"""Celery application for distributed job processing (production path)."""
from __future__ import annotations

from celery import Celery

from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "jianpu_backend",
    broker=CELERY_BROKER_URL or "redis://localhost:6379/0",
    backend=CELERY_RESULT_BACKEND or "redis://localhost:6379/0",
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=60 * 30,  # 30 min hard cap per job
    worker_max_tasks_per_child=8,
)
