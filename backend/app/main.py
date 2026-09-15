"""FastAPI entrypoint for the audio/video -> MusicXML backend."""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .config import DEFAULT_MODEL, MAX_UPLOAD_BYTES
from .logging_zh import get_logger, setup_logging
from .pipeline.omr import run_omr
from .runner import submit
from .schemas import JobCreated, JobStatus, JobState, JobTracks, MidiTrackInfo
from .store import store

setup_logging()
log = get_logger("piano.api")

app = FastAPI(title="Jianpu Staff Backend", version="0.1.0")

# Flutter Web (Chrome) calls this API from another origin/port; without CORS the
# browser blocks /omr and the app silently falls back to the weak on-device
# glyph classifier — producing digit soup that does not match the sheet.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    from .pipeline.jianpu_ly_export import jianpu_ly_available
    from .pipeline.omr_cv import opencv_available

    log.info("后端已启动（OpenCV=%s, jianpu-ly=%s）", opencv_available(), jianpu_ly_available())


@app.get("/")
def health() -> dict:
    from .pipeline.jianpu_ly_export import jianpu_ly_available
    from .pipeline.omr_cv import opencv_available

    return {
        "status": "ok",
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "opencv": opencv_available(),
        "jianpu_ly": jianpu_ly_available(),
    }


@app.post("/omr")
async def omr_jianpu(file: UploadFile = File(...)) -> JSONResponse:
    """Deskew + OCR a Jianpu photo; returns editable DSL for the client preview."""
    data = await file.read()
    name = file.filename or "image"
    log.info("【简谱OCR】收到图片 %s，大小 %.1f KB", name, len(data) / 1024)
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds 100MB limit")
    try:
        result = run_omr(data)
    except ValueError as exc:
        log.error("【简谱OCR】失败：%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    body_lines = [
        ln
        for ln in result.dsl.splitlines()
        if ln.strip() and not ln.startswith("#") and ":" not in ln and ln.strip() != "---"
    ]
    log.info(
        "【简谱OCR】完成：置信度=%.0f%%，旋律行=%d，说明=%s",
        result.confidence * 100,
        len(body_lines),
        result.message,
    )
    return JSONResponse(
        {
            "dsl": result.dsl,
            "confidence": result.confidence,
            "message": result.message,
            "deskewed_png_base64": base64.b64encode(result.deskewed_png).decode("ascii"),
        }
    )


@app.post("/jobs", response_model=JobCreated)
async def create_job(
    file: UploadFile = File(...),
    remove_vocals: bool = Form(False),
    extract_melody: bool = Form(True),
    model: str | None = Form(None),
) -> JobCreated:
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    dest = job_dir / (file.filename or "upload.bin")
    model = (model or DEFAULT_MODEL).strip().lower()

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

    log.info(
        "【音视频任务】已创建 job=%s 文件=%s 大小=%.1f MB 主旋律=%s 模型=%s",
        job_id[:8],
        file.filename,
        size / (1024 * 1024),
        "是" if extract_melody and not remove_vocals else "否",
        model,
    )
    store.create(job_id)
    submit(
        job_id,
        str(dest),
        remove_vocals=remove_vocals,
        extract_melody=extract_melody,
        model=model,
    )
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


def _require_done_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    if job.status != JobState.done:
        raise HTTPException(status_code=409, detail="Result not ready")
    return job


def _job_raw_midi(job_id: str) -> Path:
    from .pipeline.tracks import TrackError, resolve_raw_midi

    try:
        return resolve_raw_midi(store.job_dir(job_id))
    except TrackError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _subset_midi_bytes(job_id: str, tracks: str | None) -> tuple[bytes, list[int] | None]:
    """Return MIDI bytes for optional track filter; indices None = full raw."""
    from .pipeline.tracks import (
        TrackError,
        list_midi_tracks,
        parse_track_indices,
        write_track_subset,
    )

    raw = _job_raw_midi(job_id)
    try:
        meta = list_midi_tracks(raw)
        indices = parse_track_indices(tracks, track_count=len(meta))
    except TrackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if indices is None:
        return raw.read_bytes(), None

    cache_key = "_".join(f"{i:02d}" for i in indices)
    cache = store.job_dir(job_id) / "exports" / f"tracks_{cache_key}.mid"
    if not cache.is_file():
        try:
            write_track_subset(raw, cache, indices)
        except TrackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cache.read_bytes(), indices


@app.get("/jobs/{job_id}/tracks", response_model=JobTracks)
def job_tracks(job_id: str) -> JobTracks:
    """List instruments in transcription_raw.mid."""
    _require_done_job(job_id)
    job_dir = store.job_dir(job_id)
    manifest = job_dir / "tracks.json"
    if manifest.is_file():
        import json

        data = json.loads(manifest.read_text(encoding="utf-8"))
        return JobTracks(
            job_id=job_id,
            source=data.get("source", "transcription_raw.mid"),
            tracks=[MidiTrackInfo(**t) for t in data.get("tracks", [])],
        )

    from .pipeline.tracks import TrackError, list_midi_tracks, write_tracks_manifest

    raw = _job_raw_midi(job_id)
    try:
        tracks = list_midi_tracks(raw)
        write_tracks_manifest(raw, manifest)
    except TrackError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JobTracks(
        job_id=job_id,
        source="transcription_raw.mid",
        tracks=[MidiTrackInfo(**t) for t in tracks],
    )


@app.get("/jobs/{job_id}/midi/raw")
def job_midi_raw(job_id: str) -> FileResponse:
    """Always return the full multi-track transcription_raw.mid."""
    _require_done_job(job_id)
    raw = _job_raw_midi(job_id)
    return FileResponse(
        path=str(raw),
        media_type="audio/midi",
        filename="transcription_raw.mid",
    )


@app.get("/jobs/{job_id}/musicxml")
def job_musicxml(
    job_id: str,
    tracks: str | None = Query(
        None,
        description="Comma-separated instrument indices; omit for all tracks",
    ),
):
    job = _require_done_job(job_id)
    if tracks is None or not tracks.strip():
        if job.result_path is None:
            raise HTTPException(status_code=409, detail="Result not ready")
        return FileResponse(
            path=str(job.result_path),
            media_type="application/vnd.recordare.musicxml+xml",
            filename="score.musicxml",
        )

    midi_bytes, indices = _subset_midi_bytes(job_id, tracks)
    cache_key = "_".join(f"{i:02d}" for i in (indices or []))
    xml_path = store.job_dir(job_id) / "exports" / f"tracks_{cache_key}.musicxml"
    if not xml_path.is_file():
        import tempfile

        from .pipeline.to_musicxml import midi_to_musicxml

        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
            tmp.write(midi_bytes)
            tmp_path = Path(tmp.name)
        try:
            midi_to_musicxml(tmp_path, xml_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    return FileResponse(
        path=str(xml_path),
        media_type="application/vnd.recordare.musicxml+xml",
        filename="score.musicxml",
    )


@app.get("/jobs/{job_id}/midi")
def job_midi(
    job_id: str,
    tracks: str | None = Query(
        None,
        description="Comma-separated instrument indices; omit for full raw MIDI",
    ),
):
    """MIDI for selected tracks (default: full transcription_raw.mid)."""
    _require_done_job(job_id)
    data, indices = _subset_midi_bytes(job_id, tracks)
    name = (
        "transcription_raw.mid"
        if indices is None
        else f"tracks_{'_'.join(f'{i:02d}' for i in indices)}.mid"
    )
    return Response(
        content=data,
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/jobs/{job_id}/abc")
def job_abc(
    job_id: str,
    tracks: str | None = Query(
        None,
        description="Comma-separated instrument indices; omit for all tracks",
    ),
):
    """ABC for selected tracks (default: full-score score.abc)."""
    _require_done_job(job_id)
    job_dir = store.job_dir(job_id)

    if tracks is None or not tracks.strip():
        abc_path = job_dir / "score.abc"
        if not abc_path.is_file():
            raw = _job_raw_midi(job_id)
            try:
                from .pipeline.to_abc import midi_to_abc

                midi_to_abc(raw, abc_path, title="Transcription")
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"ABC generation failed: {exc}"
                ) from exc
        return FileResponse(
            path=str(abc_path),
            media_type="text/plain; charset=utf-8",
            filename="score.abc",
        )

    midi_bytes, indices = _subset_midi_bytes(job_id, tracks)
    cache_key = "_".join(f"{i:02d}" for i in (indices or []))
    abc_path = job_dir / "exports" / f"tracks_{cache_key}.abc"
    if not abc_path.is_file():
        import tempfile

        from .pipeline.to_abc import midi_to_abc

        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
            tmp.write(midi_bytes)
            tmp_path = Path(tmp.name)
        try:
            midi_to_abc(tmp_path, abc_path, title="Transcription")
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500, detail=f"ABC generation failed: {exc}"
            ) from exc
        tmp_path.unlink(missing_ok=True)
    return FileResponse(
        path=str(abc_path),
        media_type="text/plain; charset=utf-8",
        filename="score.abc",
    )


@app.get("/jobs/{job_id}/pdf")
def job_pdf(job_id: str) -> FileResponse:
    """Return PDF engraved from the job MusicXML (from transcription_raw.mid)."""
    job = _require_done_job(job_id)
    job_dir = store.job_dir(job_id)
    pdf_path = job_dir / "score.pdf"
    if not pdf_path.is_file():
        xml_path = job.result_path or (job_dir / "score.musicxml")
        if not Path(xml_path).is_file():
            raise HTTPException(status_code=404, detail="PDF not found for job")
        try:
            from .pipeline.to_pdf import musicxml_to_pdf

            musicxml_to_pdf(xml_path, pdf_path)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"PDF generation failed: {exc}"
            ) from exc
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="score.pdf",
    )
