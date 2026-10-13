"""Beat-grid quantisation for transcribed MIDI (librosa / aubio when present).

Collapses free-timing Basic Pitch output onto a musical grid so exported
MusicXML/MIDI keep readable rhythm for the main melody.
"""
from __future__ import annotations

from pathlib import Path


def quantize_midi_to_beats(
    midi_path: str | Path,
    audio_path: str | Path | None,
    out_midi: str | Path,
    *,
    grid: float = 0.25,
) -> Path:
    """Snap note onsets/offsets to a beat subdivision grid.

    Prefers librosa beat tracking on ``audio_path``; falls back to the MIDI
    file's embedded tempo. ``grid`` is in quarter-notes (0.25 = sixteenth).
    """
    try:
        import pretty_midi
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pretty_midi required") from exc

    midi_path = Path(midi_path)
    out_midi = Path(out_midi)
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    bpm = _tempo_bpm(pm, audio_path)
    sec_per_quarter = 60.0 / max(bpm, 1e-6)
    step = grid * sec_per_quarter

    def snap(t: float) -> float:
        return round(t / step) * step

    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            start = snap(n.start)
            end = snap(n.end)
            if end <= start:
                end = start + step
            n.start = max(0.0, start)
            n.end = end

    out_midi.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(out_midi))
    return out_midi


def _tempo_bpm(pm, audio_path: str | Path | None) -> float:
    if audio_path is not None:
        audio_path = Path(audio_path)
        if audio_path.is_file():
            bpm = _librosa_tempo(audio_path)
            if bpm:
                return bpm
            bpm = _aubio_tempo(audio_path)
            if bpm:
                return bpm
    try:
        _times, tempos = pm.get_tempo_changes()
        if len(tempos):
            return float(tempos[0])
    except Exception:
        pass
    return 120.0


def _librosa_tempo(path: Path) -> float | None:
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(str(path), sr=22050, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        if isinstance(tempo, np.ndarray):
            tempo = float(tempo[0]) if tempo.size else 0.0
        tempo = float(tempo)
        return tempo if 40 <= tempo <= 240 else None
    except Exception:
        return None


def _aubio_tempo(path: Path) -> float | None:
    """Optional GPL aubio beat tracker when installed."""
    try:
        import aubio
        import numpy as np

        src = aubio.source(str(path), 0, 512)
        win, hop = 1024, 512
        tempo = aubio.tempo("default", win, hop, src.samplerate)
        beats = []
        while True:
            samples, read = src()
            if tempo(samples):
                beats.append(tempo.get_last_s())
            if read < hop:
                break
        if len(beats) < 2:
            return None
        intervals = np.diff(beats)
        med = float(np.median(intervals))
        if med <= 0:
            return None
        bpm = 60.0 / med
        return bpm if 40 <= bpm <= 240 else None
    except Exception:
        return None
