"""FastAPI entrypoint for the audio/video -> MusicXML backend."""
from __future__ import annotations

import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import MAX_UPLOAD_BYTES
from .runner import submit
from .schemas import JobCreated, JobStatus, JobState
from .store import store

app = FastAPI(title="Jianpu Staff Backend", version="0.1.0")


@app.get("/")
def health() -> dict:
    return {"status": "ok", "max_upload_bytes": MAX_UPLOAD_BYTES}


@app.post("/jobs", response_model=JobCreated)
async def create_job(
    file: UploadFile = File(...),
    remove_vocals: bool = Form(True),
    model: str = Form("basic_pitch"),
) -> JobCreated:
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    dest = job_dir / (file.filename or "upload.bin")

    # Stream to disk, enforcing the 100 MB ceiling as we go.
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
                )
            out.write(chunk)

    if size == 0:
        raise HTTPException(status_code=400, detail="Empty upload")

    store.create(job_id)
    submit(job_id, str(dest), remove_vocals, model)
    return JobCreated(job_id=job_id, status=JobState.queued)


@app.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str) -> JobStatus:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return JobStatus(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
    )


@app.get("/jobs/{job_id}/musicxml")
def job_musicxml(job_id: str) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    if job.status != JobState.done or job.result_path is None:
        raise HTTPException(status_code=409, detail="Result not ready")
    return FileResponse(
        path=str(job.result_path),
        media_type="application/vnd.recordare.musicxml+xml",
        filename="score.musicxml",
    )
