"""End-to-end pipeline: uploaded media -> MusicXML + MIDI + ABC + PDF.

Stages:
  extract → Demucs vocals (optional) → transcribe → exports from raw MIDI
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..config import DEMUCS_MODEL, DEFAULT_MODEL, VIDEO_EXTENSIONS
from ..logging_zh import get_logger
from .extract import extract_audio
from .separate import separate_for_melody
from .to_abc import midi_to_abc
from .to_musicxml import midi_to_musicxml
from .to_pdf import PdfError, musicxml_to_pdf
from .tracks import write_per_track_midis, write_tracks_manifest
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
    extract_vocals_melody: bool = True,
    model: str | None = None,
    allow_separation_passthrough: bool = False,
    on_progress: ProgressCB | None = None,
) -> Path:
    """Run the full pipeline and return the path to the resulting MusicXML.

    All score exports (MusicXML / MIDI / ABC / PDF) are generated from
    ``transcription_raw.mid`` — the direct MT3 / Basic Pitch output — without
    skyline collapse or beat re-quantization.
    """
    cb = on_progress or _noop
    model = model or DEFAULT_MODEL
    input_path = Path(input_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    log.info("流水线开始：输入=%s 工作目录=%s", input_path.name, workdir)

    cb("extract", 0.02)
    log.info("① 提取/规范化音轨…")
    wav = workdir / "audio.wav"
    extract_audio(input_path, wav)
    log.info("① 音轨就绪：%s（%.1f KB）", wav.name, wav.stat().st_size / 1024)
    cb("extract", 0.10)

    prefer_vocals = extract_vocals_melody and not remove_vocals_first
    to_transcribe = wav
    if extract_vocals_melody or remove_vocals_first:
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
    log.info("③ 转录为 MIDI（引擎=%s）…", model)
    raw_midi = workdir / "transcription_raw.mid"
    transcribe_to_midi(to_transcribe, raw_midi, model=model)
    log.info("③ 原始 MIDI 已写出：%s", raw_midi.name)
    cb("transcribe", 0.72)

    # Keep raw MIDI as the canonical multi-track source; also mirror as
    # transcription.mid for older clients.
    midi = workdir / "transcription.mid"
    shutil.copyfile(raw_midi, midi)
    log.info("④ 保留原始 MIDI：%s（并镜像 %s）", raw_midi.name, midi.name)

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
    log.info("⑤ 由原始 MIDI 生成 MusicXML（全轨）…")
    xml = workdir / "score.musicxml"
    midi_to_musicxml(raw_midi, xml)
    log.info("⑤ MusicXML 完成：%s（%.1f KB）", xml.name, xml.stat().st_size / 1024)

    cb("abc", 0.90)
    log.info("⑥ 由原始 MIDI 生成 ABC（全轨）…")
    abc_path = workdir / "score.abc"
    try:
        midi_to_abc(raw_midi, abc_path, title=title)
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
