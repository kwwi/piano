"""Monophonic melody transcription via ``torchcrepe`` (CREPE pitch tracker).

Designed for vocal / single-pitch stems (typically Demucs ``vocals.wav``).
Outputs a one-track MIDI named ``Melody``.

Performance notes (CPU):
  - Default model is ``tiny`` (``full`` is ~5–10× slower).
  - Audio is processed in short windows with limited torch threads so a long
    mix cannot pin every core for tens of minutes.
"""
from __future__ import annotations

from pathlib import Path

from ..config import (
    CREPE_CHUNK_SECONDS,
    CREPE_DEVICE,
    CREPE_FMAX,
    CREPE_FMIN,
    CREPE_HOP_LENGTH,
    CREPE_MIN_DUR,
    CREPE_MODEL,
    CREPE_PERIODICITY,
    CREPE_SAMPLE_RATE,
    CREPE_TORCH_THREADS,
)
from ..logging_zh import get_logger

log = get_logger("piano.crepe")


class CrepeNotProvisioned(RuntimeError):
    pass


def crepe_available() -> bool:
    try:
        import torchcrepe  # noqa: F401

        return True
    except Exception:
        return False


def _resolve_device(requested: str) -> str:
    req = (requested or "auto").strip().lower()
    if req == "cpu":
        return "cpu"
    try:
        import torch

        if req in {"cuda", "auto"} and torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _hz_to_midi(freq: float) -> int | None:
    if freq is None or freq <= 0:
        return None
    import math

    midi = int(round(69.0 + 12.0 * math.log2(float(freq) / 440.0)))
    if midi < 21 or midi > 108:
        return None
    return midi


def _limit_torch_threads(n: int) -> None:
    try:
        import torch

        n = max(1, int(n))
        torch.set_num_threads(n)
        torch.set_num_interop_threads(1)
    except Exception:
        pass


def run_crepe(audio_path: Path, out_midi: Path) -> Path:
    """Estimate F0 with torchcrepe and write a monophonic Melody MIDI."""
    if not crepe_available():
        raise CrepeNotProvisioned(
            "torchcrepe is not installed. pip install torchcrepe "
            "(see requirements-ml.txt)"
        )

    import numpy as np
    import pretty_midi
    import torch
    import torchcrepe

    audio_path = Path(audio_path)
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if not audio_path.is_file():
        raise CrepeNotProvisioned(f"audio not found: {audio_path}")

    try:
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise CrepeNotProvisioned("soundfile is required for CREPE") from exc

    _limit_torch_threads(CREPE_TORCH_THREADS)

    target_sr = int(CREPE_SAMPLE_RATE)
    wav, sr = sf.read(str(audio_path), always_2d=False)
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim == 2:
        wav = wav.mean(axis=1).astype(np.float32)
    if int(sr) != target_sr:
        try:
            import librosa

            wav = librosa.resample(wav, orig_sr=int(sr), target_sr=target_sr)
            wav = np.asarray(wav, dtype=np.float32)
            sr = target_sr
        except Exception as exc:
            raise CrepeNotProvisioned(
                "librosa is required to resample audio for CREPE"
            ) from exc

    if wav.size == 0:
        raise CrepeNotProvisioned("empty audio for CREPE")

    device = _resolve_device(CREPE_DEVICE)
    hop = int(CREPE_HOP_LENGTH)
    model = (CREPE_MODEL or "tiny").strip().lower()
    if model not in {"tiny", "full"}:
        model = "tiny"

    duration = float(wav.shape[0]) / float(sr)
    chunk_sec = max(5.0, float(CREPE_CHUNK_SECONDS))
    log.info(
        "CREPE 推理：sr=%d hop=%d model=%s device=%s threads=%s len=%.1fs chunk=%.0fs",
        sr,
        hop,
        model,
        device,
        CREPE_TORCH_THREADS,
        duration,
        chunk_sec,
    )

    # Process in time chunks so long songs stay responsive and log progress.
    chunk_samples = int(chunk_sec * sr)
    # Overlap ~0.25s so notes at boundaries are not clipped.
    overlap = int(0.25 * sr)
    hop_samples = max(1, chunk_samples - overlap)

    pitch_parts: list[np.ndarray] = []
    peri_parts: list[np.ndarray] = []
    # Frames already covered (absolute frame index along the full file).
    covered_frames = 0
    frame_sec = float(hop) / float(sr)
    n_chunks = max(1, int(np.ceil(max(1, wav.shape[0] - overlap) / hop_samples)))

    with torch.no_grad():
        for ci, start in enumerate(range(0, wav.shape[0], hop_samples)):
            end = min(wav.shape[0], start + chunk_samples)
            if end - start < hop:
                break
            piece = wav[start:end]
            audio_t = torch.from_numpy(piece).float().unsqueeze(0).to(device)
            pitch, periodicity = torchcrepe.predict(
                audio_t,
                sr,
                hop_length=hop,
                fmin=float(CREPE_FMIN),
                fmax=float(CREPE_FMAX),
                model=model,
                return_periodicity=True,
                batch_size=512,
                device=device,
                pad=True,
            )
            p = pitch.detach().cpu().numpy().reshape(-1)
            peri = periodicity.detach().cpu().numpy().reshape(-1)

            # Drop overlapped frames for chunks after the first.
            if start > 0:
                skip = int(round(overlap / hop))
                if skip > 0 and skip < len(p):
                    p = p[skip:]
                    peri = peri[skip:]
                elif skip >= len(p):
                    continue

            pitch_parts.append(p)
            peri_parts.append(peri)
            covered_frames += len(p)
            log.info(
                "CREPE 分段 %d/%d（%.1f–%.1fs，累计帧 %d）",
                ci + 1,
                n_chunks,
                start / float(sr),
                end / float(sr),
                covered_frames,
            )
            if end >= wav.shape[0]:
                break

    if not pitch_parts:
        raise CrepeNotProvisioned("CREPE produced empty pitch contour")

    pitch_arr = np.concatenate(pitch_parts)
    peri_arr = np.concatenate(peri_parts)
    thr = float(CREPE_PERIODICITY)
    min_dur = float(CREPE_MIN_DUR)

    notes: list[tuple[float, float, int, int]] = []
    i = 0
    n = len(pitch_arr)
    while i < n:
        if peri_arr[i] < thr:
            i += 1
            continue
        midi = _hz_to_midi(float(pitch_arr[i]))
        if midi is None:
            i += 1
            continue
        j = i + 1
        while j < n and peri_arr[j] >= thr:
            m2 = _hz_to_midi(float(pitch_arr[j]))
            if m2 != midi:
                break
            j += 1
        start_t = i * frame_sec
        end_t = j * frame_sec
        if end_t - start_t >= min_dur:
            conf = float(np.mean(peri_arr[i:j]))
            vel = int(max(40, min(110, round(40 + conf * 80))))
            notes.append((start_t, end_t, midi, vel))
        i = j

    if not notes:
        raise CrepeNotProvisioned(
            "CREPE produced no notes (try lowering CREPE_PERIODICITY or "
            "ensure the input is a vocal stem)"
        )

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="Melody")
    for start_t, end_t, midi, vel in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=vel, pitch=midi, start=start_t, end=end_t)
        )
    pm.instruments.append(inst)
    pm.write(str(out_midi))
    log.info(
        "CREPE 完成：%s → %s（%d 音，%.1f KB）",
        audio_path.name,
        out_midi.name,
        len(notes),
        out_midi.stat().st_size / 1024,
    )
    return out_midi
