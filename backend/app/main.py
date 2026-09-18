"""FastAPI entrypoint for the audio/video -> MusicXML backend."""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .config import (
    DEFAULT_MODEL,
    MAX_UPLOAD_BYTES,
    SPLIT_AUDIO_DEFAULT,
    SPLIT_SECONDS_DEFAULT,
)
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
    from .pipeline.transcribe import (
        basic_pitch_available,
        crepe_available,
        mt3_available,
    )

    log.info(
        "后端已启动（OpenCV=%s, jianpu-ly=%s, mt3-infer=%s, basic_pitch=%s, crepe=%s）",
        opencv_available(),
        jianpu_ly_available(),
        mt3_available(),
        basic_pitch_available(),
        crepe_available(),
    )


@app.get("/")
def health() -> dict:
    from .config import (
        DEFAULT_MODEL,
        MT3_DEVICE,
        MT3_INFER_MODEL,
        PIANO_ARRANGER_BACKEND,
        PIANO_ARRANGER_STYLE,
    )
    from .pipeline.jianpu_ly_export import jianpu_ly_available
    from .pipeline.omr_cv import opencv_available
    from .pipeline.transcribe import (
        basic_pitch_available,
        crepe_available,
        mt3_available,
    )

    return {
        "status": "ok",
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "opencv": opencv_available(),
        "jianpu_ly": jianpu_ly_available(),
        "default_model": DEFAULT_MODEL,
        "mt3_infer": mt3_available(),
        "mt3_infer_model": MT3_INFER_MODEL,
        "mt3_device": MT3_DEVICE,
        "basic_pitch": basic_pitch_available(),
        "crepe": crepe_available(),
        "piano_arranger_backend": PIANO_ARRANGER_BACKEND,
        "piano_arranger_style": PIANO_ARRANGER_STYLE,
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
    extract_melody: bool = Form(False),
    model: str | None = Form(None),
    split_audio: bool | None = Form(None),
    split_seconds: float | None = Form(None),
    arrangement: str | None = Form(None),  # ignored; always multi-track
) -> JobCreated:
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    dest = job_dir / (file.filename or "upload.bin")
    model = (model or DEFAULT_MODEL).strip().lower()
    do_split = SPLIT_AUDIO_DEFAULT if split_audio is None else bool(split_audio)
    chunk_sec = (
        float(SPLIT_SECONDS_DEFAULT)
        if split_seconds is None
        else float(split_seconds)
    )
    if chunk_sec < 5 or chunk_sec > 180:
        raise HTTPException(
            status_code=400,
            detail="split_seconds must be between 5 and 180",
        )
    # Legacy clients may still send arrangement; pipeline always keeps multi-track.
    _ = arrangement

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
        "【音视频任务】已创建 job=%s 文件=%s 大小=%.1f MB 主旋律=%s 模型=%s 分段=%s",
        job_id[:8],
        file.filename,
        size / (1024 * 1024),
        "是" if extract_melody and not remove_vocals else "否",
        model,
        f"{chunk_sec:.0f}s" if do_split else "关",
    )
    store.create(job_id)
    submit(
        job_id,
        str(dest),
        remove_vocals=remove_vocals,
        extract_melody=extract_melody,
        model=model,
        split_audio=do_split,
        split_seconds=chunk_sec,
        arrangement="full",
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


def _job_track_count(job_id: str) -> int:
    job_dir = store.job_dir(job_id)
    manifest = job_dir / "tracks.json"
    if manifest.is_file():
        import json

        data = json.loads(manifest.read_text(encoding="utf-8"))
        n = len(data.get("tracks") or [])
        if n > 0:
            return n
    from .pipeline.tracks import list_midi_tracks

    return len(list_midi_tracks(_job_raw_midi(job_id)))


def _parse_arrange(arrange: str | None) -> str | None:
    if arrange is None or not str(arrange).strip():
        return None
    val = str(arrange).strip().lower()
    if val in {"", "none", "full", "0", "false", "off"}:
        return None
    if val in {"piano", "piano_score", "1", "true", "on"}:
        return "piano"
    raise HTTPException(
        status_code=400,
        detail=f"invalid arrange={arrange!r} (use piano or omit)",
    )


def _subset_midi_bytes(
    job_id: str,
    tracks: str | None,
    *,
    arrange: str | None = None,
    piano_style: str | None = None,
    piano_chords: str | None = None,
) -> tuple[bytes, str | None]:
    """Return MIDI bytes for optional track filter / piano arrangement.

    ``cache_key`` is ``None`` when returning the full score MIDI unchanged.
    ``tracks`` may mix source indices with derived tokens ``mN`` / ``cN``.
    ``arrange=piano`` runs lead→piano arranger→RH/LH postprocess.
    """
    from .pipeline.track_derive import (
        assemble_selection_midi,
        parse_track_selection,
    )
    from .pipeline.tracks import TrackError, resolve_score_midi

    score = resolve_score_midi(store.job_dir(job_id))
    job_dir = store.job_dir(job_id)
    try:
        track_count = _job_track_count(job_id)
        selection = parse_track_selection(tracks, track_count=track_count)
    except TrackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    arrange_mode = _parse_arrange(arrange)
    if arrange_mode == "piano":
        from .config import PIANO_ARRANGER_AUTO_CHORDS, PIANO_ARRANGER_STYLE
        from .pipeline.arrange_piano import ArrangePianoError, arrange_for_piano

        style = (piano_style or PIANO_ARRANGER_STYLE or "pop").strip().lower()
        auto_chords = PIANO_ARRANGER_AUTO_CHORDS
        if piano_chords is not None and str(piano_chords).strip():
            pc = str(piano_chords).strip().lower()
            if pc in {"off", "0", "false", "no"}:
                auto_chords = False
            elif pc in {"auto", "on", "1", "true", "yes"}:
                auto_chords = True

        sel_key = selection.cache_key if selection is not None else "all"
        chord_tag = "cauto" if auto_chords else "coff"
        cache_key = f"piano_{sel_key}_{style}_{chord_tag}"
        cache = job_dir / "exports" / f"{cache_key}.mid"
        if not cache.is_file():
            try:
                arrange_for_piano(
                    job_dir,
                    selection,
                    cache,
                    style=style,
                    auto_chords=auto_chords,
                )
            except ArrangePianoError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except TrackError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return cache.read_bytes(), cache_key

    if selection is None:
        return score.read_bytes(), None

    cache_key = selection.cache_key
    cache = job_dir / "exports" / f"sel_{cache_key}.mid"
    if not cache.is_file():
        try:
            assemble_selection_midi(job_dir, selection, cache)
        except TrackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cache.read_bytes(), cache_key


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
        description="Selection tokens: 0,1,m0,c1 — omit for all source tracks",
    ),
    arrange: str | None = Query(
        None,
        description="piano = arrange selection into playable piano grand-staff",
    ),
    piano_style: str | None = Query(None, description="pop | ballad | drive"),
    piano_chords: str | None = Query(
        None, description="auto | off — auto-estimate chords when unset"
    ),
):
    job = _require_done_job(job_id)
    arrange_mode = _parse_arrange(arrange)

    if arrange_mode == "piano":
        from .pipeline.arrange_piano.to_grand_staff import piano_midi_to_musicxml

        job_dir = store.job_dir(job_id)
        midi_bytes, cache_key = _subset_midi_bytes(
            job_id,
            tracks,
            arrange=arrange,
            piano_style=piano_style,
            piano_chords=piano_chords,
        )
        xml_path = job_dir / "exports" / f"{cache_key or 'piano'}_gs.musicxml"
        if not xml_path.is_file():
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
                tmp.write(midi_bytes)
                tmp_path = Path(tmp.name)
            try:
                piano_midi_to_musicxml(tmp_path, xml_path)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            tmp_path.unlink(missing_ok=True)
        return FileResponse(
            path=str(xml_path),
            media_type="application/vnd.recordare.musicxml+xml",
            filename="piano.musicxml",
        )

    if tracks is None or not tracks.strip():
        if job.result_path is None:
            raise HTTPException(status_code=409, detail="Result not ready")
        return FileResponse(
            path=str(job.result_path),
            media_type="application/vnd.recordare.musicxml+xml",
            filename="score.musicxml",
        )

    from .pipeline.track_derive import parse_track_selection
    from .pipeline.tracks import (
        TrackError,
        filter_musicxml_by_part_indices,
        resolve_full_musicxml,
    )

    job_dir = store.job_dir(job_id)
    try:
        track_count = _job_track_count(job_id)
        selection = parse_track_selection(tracks, track_count=track_count)
    except TrackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if selection is None:
        if job.result_path is None:
            raise HTTPException(status_code=409, detail="Result not ready")
        return FileResponse(
            path=str(job.result_path),
            media_type="application/vnd.recordare.musicxml+xml",
            filename="score.musicxml",
        )

    cache_key = selection.cache_key
    xml_path = job_dir / "exports" / f"sel_{cache_key}.musicxml"
    if not xml_path.is_file():
        use_filter = (
            not selection.has_derived
            and bool(selection.sources)
        )
        wrote = False
        if use_filter:
            full_xml = resolve_full_musicxml(job_dir)
            if full_xml is None and job.result_path is not None:
                p = Path(job.result_path)
                full_xml = p if p.is_file() else None
            if full_xml is not None:
                try:
                    filter_musicxml_by_part_indices(
                        full_xml, xml_path, selection.sources
                    )
                    wrote = True
                except TrackError:
                    wrote = False
        if not wrote:
            import tempfile

            from .pipeline.to_musicxml import midi_to_musicxml

            midi_bytes, _ = _subset_midi_bytes(job_id, tracks)
            with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
                tmp.write(midi_bytes)
                tmp_path = Path(tmp.name)
            try:
                midi_to_musicxml(tmp_path, xml_path)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        description="Selection tokens: 0,1,m0,c1 — omit for full multi-track MIDI",
    ),
    arrange: str | None = Query(
        None,
        description="piano = arrange selection into playable piano MIDI",
    ),
    piano_style: str | None = Query(None, description="pop | ballad | drive"),
    piano_chords: str | None = Query(None, description="auto | off"),
):
    """MIDI for selected source / derived parts (default: full transcription)."""
    _require_done_job(job_id)
    data, cache_key = _subset_midi_bytes(
        job_id,
        tracks,
        arrange=arrange,
        piano_style=piano_style,
        piano_chords=piano_chords,
    )
    if cache_key is None:
        name = "transcription.mid"
    elif str(cache_key).startswith("piano_"):
        name = f"{cache_key}.mid"
    else:
        name = f"sel_{cache_key}.mid"
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
    arrange: str | None = Query(
        None,
        description="piano = ABC from arranged piano MIDI",
    ),
    piano_style: str | None = Query(None, description="pop | ballad | drive"),
    piano_chords: str | None = Query(None, description="auto | off"),
):
    """ABC for selected tracks (default: full-score score.abc)."""
    _require_done_job(job_id)
    job_dir = store.job_dir(job_id)
    arrange_mode = _parse_arrange(arrange)

    if arrange_mode == "piano" or (tracks is not None and tracks.strip()):
        midi_bytes, cache_key = _subset_midi_bytes(
            job_id,
            tracks,
            arrange=arrange,
            piano_style=piano_style,
            piano_chords=piano_chords,
        )
        key = cache_key or "all"
        prefix = "" if str(key).startswith("piano_") else "sel_"
        abc_path = job_dir / "exports" / f"{prefix}{key}.abc"
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
