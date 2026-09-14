"""End-to-end pipeline: uploaded media -> MusicXML.

Stages (with progress weights):
  extract (0.10) -> separate/vocal-removal (0.45) -> transcribe (0.80)
  -> musicxml (1.00)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..config import DEMUCS_MODEL, VIDEO_EXTENSIONS
from .extract import extract_audio
from .separate import remove_vocals
from .to_musicxml import midi_to_musicxml
from .transcribe import transcribe_to_midi

ProgressCB = Callable[[str, float], None]


def _noop(stage: str, progress: float) -> None:  # pragma: no cover
    pass


def run_pipeline(
    input_path: str | Path,
    workdir: str | Path,
    *,
    remove_vocals_first: bool = True,
    model: str = "basic_pitch",
    allow_separation_passthrough: bool = False,
    on_progress: ProgressCB | None = None,
) -> Path:
    """Run the full pipeline and return the path to the resulting MusicXML."""
    cb = on_progress or _noop
    input_path = Path(input_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Extract / normalise audio (also handles video containers).
    cb("extract", 0.02)
    wav = workdir / "audio.wav"
    extract_audio(input_path, wav)
    cb("extract", 0.10)

    # 2. Vocal removal (optional).
    to_transcribe = wav
    if remove_vocals_first:
        cb("separate", 0.15)
        instrumental = workdir / "instrumental.wav"
        to_transcribe = remove_vocals(
            wav,
            instrumental,
            model=DEMUCS_MODEL,
            allow_passthrough=allow_separation_passthrough,
        )
        cb("separate", 0.45)

    # 3. Transcribe to MIDI.
    cb("transcribe", 0.50)
    midi = workdir / "transcription.mid"
    transcribe_to_midi(to_transcribe, midi, model=model)
    cb("transcribe", 0.80)

    # 4. MIDI -> MusicXML.
    cb("musicxml", 0.85)
    xml = workdir / "score.musicxml"
    midi_to_musicxml(midi, xml)
    cb("musicxml", 1.0)
    return xml


def is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS
