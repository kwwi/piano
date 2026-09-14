"""Celery task wrapping the pipeline (used when a broker is configured)."""
from __future__ import annotations

from pathlib import Path

from .celery_app import celery_app
from .pipeline.orchestrator import run_pipeline
from .schemas import JobState
from .store import store


@celery_app.task(name="process_job")
def process_job(job_id: str, input_path: str, remove_vocals: bool, model: str) -> str:
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
            on_progress=progress,
        )
        store.update(
            job_id,
            status=JobState.done,
            stage="done",
            progress=1.0,
            result_path=Path(xml),
        )
        return str(xml)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status=JobState.error, error=str(exc))
        raise
