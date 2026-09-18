"""End-to-end pipeline: uploaded media -> MusicXML + MIDI + ABC + PDF.

Stages:
  extract → Demucs (optional, non-MuScriptor) → transcribe → multi-track exports

Score exports keep the model’s multi-track MIDI as-is. Track subsetting for
preview/export is done on demand via the API (client selects tracks).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..config import (
    DEMUCS_MODEL,
    DEFAULT_MODEL,
    SPLIT_OVERLAP_SECONDS,
    SPLIT_SECONDS_DEFAULT,
    VIDEO_EXTENSIONS,
)
from ..logging_zh import get_logger
from .extract import extract_audio
from .separate import separate_for_melody
from .to_abc import midi_to_abc
from .to_musicxml import midi_to_musicxml
from .to_pdf import PdfError, musicxml_to_pdf
from .tracks import annotate_instrument_names, write_per_track_midis, write_tracks_manifest
from .transcribe import transcribe_to_midi

ProgressCB = Callable[[str, float], None]
log = get_logger("piano.pipeline")


def _noop(stage: str, progress: float) -> None:  # pragma: no cover
    pass


def run_pipeline(
    input_path: str | Path,
    workdir: str | Path,
    *,
    remove_vocals_first: bool = False,
    extract_vocals_melody: bool = False,
    model: str | None = None,
    allow_separation_passthrough: bool = False,
    split_audio: bool = False,
    split_seconds: float | None = None,
    arrangement: str | None = None,  # kept for API compat; always multi-track
    on_progress: ProgressCB | None = None,
) -> Path:
    """Run the full pipeline and return the path to the resulting MusicXML.

    ``transcription_raw.mid`` and ``transcription.mid`` both store the model’s
    multi-track MIDI (no skyline / lead-sheet rewrite). Clients pick tracks for
    export and MIDI audition.
    """
    cb = on_progress or _noop
    model = (model or DEFAULT_MODEL).strip().lower()
    chunk_sec = float(split_seconds if split_seconds is not None else SPLIT_SECONDS_DEFAULT)
    if arrangement and arrangement.strip().lower() not in {"", "full"}:
        log.info(
            "忽略编配选项 %r：仅输出模型多轨 MIDI（由客户端选轨）",
            arrangement,
        )
    use_external_split = bool(split_audio) and model not in {"crepe", "muscriptor"}
    input_path = Path(input_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    log.info(
        "流水线开始：输入=%s 工作目录=%s 模型=%s 分段=%s",
        input_path.name,
        workdir,
        model,
        f"{chunk_sec:.0f}s" if use_external_split else "关",
    )

    cb("extract", 0.02)
    log.info("① 提取/规范化音轨…")
    wav = workdir / "audio.wav"
    extract_audio(input_path, wav)
    log.info("① 音轨就绪：%s（%.1f KB）", wav.name, wav.stat().st_size / 1024)
    cb("extract", 0.10)

    prefer_vocals = extract_vocals_melody and not remove_vocals_first
    if model == "crepe":
        prefer_vocals = True
        if remove_vocals_first:
            log.warning("CREPE 忽略 remove_vocals，改用人声干声")
    to_transcribe = wav
    need_separate = False
    if model == "muscriptor":
        if extract_vocals_melody or remove_vocals_first:
            log.info(
                "② MuScriptor 使用完整混音（跳过 Demucs；多乐器转录不需要先分轨）"
            )
        cb("separate", 0.45)
    else:
        need_separate = (
            extract_vocals_melody or remove_vocals_first or model == "crepe"
        )
    if need_separate:
        cb("separate", 0.15)
        stem_label = "人声主旋律" if prefer_vocals else "伴奏（无人声）"
        log.info("② 源分离：提取%s（Demucs）…", stem_label)
        stem = workdir / ("vocals.wav" if prefer_vocals else "instrumental.wav")
        to_transcribe = separate_for_melody(
            wav,
            stem,
            prefer_vocals=prefer_vocals,
            model=DEMUCS_MODEL,
            allow_passthrough=allow_separation_passthrough,
        )
        if to_transcribe.resolve() == stem.resolve() and stem.is_file():
            log.info("② 分离完成：%s", stem.name)
        else:
            log.warning("② 分离不可用，回退使用完整混音")
        cb("separate", 0.45)

    cb("transcribe", 0.50)
    log.info(
        "③ 转录为 MIDI（引擎=%s%s）…",
        model,
        f"，分段 {chunk_sec:.0f}s" if use_external_split else "",
    )
    raw_midi = workdir / "transcription_raw.mid"

    def _chunk_progress(done: int, total: int) -> None:
        frac = done / max(total, 1)
        cb("transcribe", 0.50 + 0.20 * frac)

    transcribe_to_midi(
        to_transcribe,
        raw_midi,
        model=model,
        split_audio=use_external_split,
        split_seconds=chunk_sec,
        split_overlap=SPLIT_OVERLAP_SECONDS,
        chunks_dir=workdir / "chunks",
        on_chunk_progress=_chunk_progress if use_external_split else None,
    )
    try:
        annotate_instrument_names(raw_midi)
    except Exception as exc:
        log.warning("③ 音轨命名标注跳过：%s", exc)
    log.info("③ 原始 MIDI 已写出：%s", raw_midi.name)
    cb("transcribe", 0.70)

    # Keep score MIDI identical to the model output (multi-track).
    score_midi = workdir / "transcription.mid"
    cb("arrange", 0.72)
    shutil.copyfile(raw_midi, score_midi)
    log.info("④ 多轨 MIDI 就绪：%s", score_midi.name)
    cb("arrange", 0.76)

    tracks_json = workdir / "tracks.json"
    tracks_dir = workdir / "tracks"
    try:
        write_tracks_manifest(raw_midi, tracks_json)
        written = write_per_track_midis(raw_midi, tracks_dir)
        log.info("④ 音轨清单：%d 轨 → %s", len(written), tracks_json.name)
    except Exception as exc:
        log.warning("④ 音轨拆分失败（全曲导出仍可用）：%s", exc)
    cb("midi", 0.78)

    title = input_path.stem or "Transcription"

    cb("musicxml", 0.82)
    log.info("⑤ 生成 MusicXML（多轨）…")
    xml = workdir / "score.musicxml"
    midi_to_musicxml(score_midi, xml)
    log.info("⑤ MusicXML 完成：%s（%.1f KB）", xml.name, xml.stat().st_size / 1024)

    cb("abc", 0.90)
    log.info("⑥ 生成 ABC…")
    abc_path = workdir / "score.abc"
    try:
        midi_to_abc(score_midi, abc_path, title=title)
        log.info("⑥ ABC 完成：%s（%.1f KB）", abc_path.name, abc_path.stat().st_size / 1024)
    except Exception as exc:
        log.warning("⑥ ABC 生成失败（MusicXML 仍可用）：%s", exc)

    cb("pdf", 0.95)
    log.info("⑦ 由 MusicXML 生成 PDF…")
    pdf_path = workdir / "score.pdf"
    try:
        musicxml_to_pdf(xml, pdf_path)
        log.info("⑦ PDF 完成：%s（%.1f KB）", pdf_path.name, pdf_path.stat().st_size / 1024)
    except PdfError as exc:
        log.warning("⑦ PDF 跳过：%s", exc)
    except Exception as exc:
        log.warning("⑦ PDF 生成失败：%s", exc)

    cb("musicxml", 1.0)
    log.info("流水线结束")
    return xml


def is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS
