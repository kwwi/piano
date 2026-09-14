"""Pipeline-level tests. Extraction runs for real (ffmpeg); transcription is
skipped when Basic Pitch is not installed in the current environment."""
import pytest

from app.pipeline.extract import extract_audio, ffmpeg_available
from app.pipeline.orchestrator import is_video, run_pipeline
from app.pipeline.transcribe import basic_pitch_available


def test_is_video():
    assert is_video("clip.mp4") is True
    assert is_video("song.mp3") is False


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_extract_audio_from_wav(sine_wav, tmp_path):
    out = extract_audio(sine_wav, tmp_path / "out.wav", sample_rate=22050)
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(
    not (ffmpeg_available() and basic_pitch_available()),
    reason="requires ffmpeg + basic-pitch",
)
def test_full_pipeline_produces_musicxml(sine_wav, tmp_path):
    xml = run_pipeline(
        sine_wav,
        tmp_path / "work",
        remove_vocals_first=False,  # skip demucs weights in tests
        model="basic_pitch",
    )
    text = xml.read_text(encoding="utf-8")
    assert "<score-partwise" in text
