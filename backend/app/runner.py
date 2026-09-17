"""Executes pipeline jobs, updating the job store as it goes.

Uses Celery when a broker is configured; otherwise runs the job on a local
thread pool so the API works standalone.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import CELERY_BROKER_URL, DEFAULT_MODEL, STORAGE_DIR
from .logging_zh import get_logger, stage_zh
from .pipeline.orchestrator import run_pipeline
from .schemas import JobState
from .store import store

log = get_logger("piano.job")

# librosa/numba (pulled in by Basic Pitch) fails in worker threads when it
# cannot write a function cache next to the installed package. Point the cache
# at a writable directory under our storage root before any ML import happens.
_numba_cache = STORAGE_DIR / ".numba_cache"
_numba_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(_numba_cache))

_executor = ThreadPoolExecutor(max_workers=2)


def _run(
    job_id: str,
    input_path: str,
    *,
    remove_vocals: bool,
    extract_melody: bool,
    model: str,
    split_audio: bool = False,
    split_seconds: float | None = None,
    arrangement: str | None = None,
) -> None:
    short = job_id[:8]
    log.info(
        "【任务 %s】开始处理：模型=%s 提取主旋律=%s 分段=%s 编配=%s",
        short,
        model,
        extract_melody,
        split_audio,
        arrangement or "full",
    )
    store.update(job_id, status=JobState.processing, stage="extract", progress=0.01)
    job_dir = store.job_dir(job_id)
    try:
        def progress(stage: str, value: float) -> None:
            store.update(job_id, stage=stage, progress=value)
            log.info(
                "【任务 %s】%s（进度 %.0f%%）",
                short,
                stage_zh(stage),
                value * 100,
            )

        xml = run_pipeline(
            input_path,
            job_dir,
            remove_vocals_first=remove_vocals,
            extract_vocals_melody=extract_melody,
            model=model,
            split_audio=split_audio,
            split_seconds=split_seconds,
            arrangement=arrangement,
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
        log.info("【任务 %s】成功完成 → %s", short, xml)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status=JobState.error, error=str(exc))
        log.exception("【任务 %s】失败：%s", short, exc)


def submit(
    job_id: str,
    input_path: str,
    *,
    remove_vocals: bool = False,
    extract_melody: bool = False,
    model: str | None = None,
    split_audio: bool = False,
    split_seconds: float | None = None,
    arrangement: str | None = None,
) -> None:
    """Enqueue a job for execution."""
    model = model or DEFAULT_MODEL
    log.info("【任务 %s】已入队", job_id[:8])
    if CELERY_BROKER_URL:
        from .tasks import process_job

        process_job.delay(
            job_id,
            input_path,
            remove_vocals,
            extract_melody,
            model,
            split_audio,
            split_seconds,
            arrangement,
        )
    else:
        _executor.submit(
            _run,
            job_id,
            input_path,
            remove_vocals=remove_vocals,
            extract_melody=extract_melody,
            model=model,
            split_audio=split_audio,
            split_seconds=split_seconds,
            arrangement=arrangement,
        )
