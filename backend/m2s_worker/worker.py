"""Long-lived MIDI2ScoreTransformer worker (JSON lines over stdin/stdout).

Runs inside the dedicated M2S venv (Python 3.11 + TimFelixBeyer/music21 fork).
The API process (``app.pipeline.score_m2s.client``) spawns it once and keeps it
alive so the ~390 MB checkpoint is loaded only one time.

Protocol — one JSON object per line:

* on start-up the worker prints ``{"ready": true, "device": "..."}`` or
  ``{"ready": false, "error": "..."}`` (then exits);
* request  ``{"id": 1, "midi": "/abs/in.mid", "out": "/abs/out.musicxml", "name": "Piano"}``
  response ``{"id": 1, "ok": true, "notes": 123}`` / ``{"id": 1, "ok": false, "error": "..."}``;
* request  ``{"id": 2, "cmd": "ping"}`` → ``{"id": 2, "ok": true}``.

Environment: ``M2S_ROOT`` (repo checkout), ``M2S_CKPT`` (checkpoint path),
``M2S_DEVICE`` (auto | cuda | mps | cpu).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from pathlib import Path

# Everything the model code prints (progress, music21 warnings) must not corrupt
# the protocol channel.
_PROTO_OUT = sys.stdout
sys.stdout = sys.stderr


def _emit(obj: dict) -> None:
    _PROTO_OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _PROTO_OUT.flush()


def _pick_device(torch, requested: str) -> str:
    # ``auto`` skips MPS: token-by-token decoding at batch size 1 is launch-bound
    # and measured >10× slower on Apple GPUs than on CPU.
    requested = (requested or "auto").strip().lower()
    if requested in {"cuda", "mps", "cpu"}:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _infer(torch, x, model, overlap: int = 64, chunk: int = 512, kv_cache: bool = True):
    """Chunked autoregressive decoding (copied from upstream ``utils.infer``).

    Upstream hard-codes ``torch.autocast(device_type=<cuda|cpu>)``; autocast is
    only used on CUDA here so MPS/CPU run in full precision.

    Upstream also always decodes ``chunk`` steps; the decoder is causal and
    greedy, so stopping at the chunk's real note count yields the same tokens
    for every real note (a 48-note track needs 48 steps instead of 512) and
    never decodes phantom notes past the end of the input.
    """
    single_example = x["pitch"].ndim == 2
    if single_example:
        x = {k: v.unsqueeze(0) for k, v in x.items()}
    x = {k: v.to(model.device) for k, v in x.items()}
    if chunk <= overlap:
        raise ValueError("`chunk` must be greater than `overlap`.")
    use_autocast = model.device.type == "cuda"
    y_full = None
    for i in range(0, max(x["pitch"].shape[1] - overlap, 1), chunk - overlap):
        x_chunk = {k: v[:, i : i + chunk] for k, v in x.items()}
        steps = x_chunk["pitch"].shape[1]
        if i == 0 or overlap == 0:
            y_hat = model.generate(x=x_chunk, top_k=1, max_length=steps, kv_cache=kv_cache)
        else:
            y_hat_prev = {
                k: v[:, -overlap:] if k != "pad" else v[:, -overlap:, 0]
                for k, v in y_full.items()
            }
            ctx = (
                torch.autocast(device_type="cuda")
                if use_autocast
                else contextlib.nullcontext()
            )
            with ctx:
                y_hat = model.generate(
                    x=x_chunk, y=y_hat_prev, top_k=1, max_length=steps, kv_cache=kv_cache
                )
            y_hat = {k: v[:, overlap:] for k, v in y_hat.items()}
        if y_full is None:
            y_full = y_hat
        else:
            for k in y_full:
                y_full[k] = torch.cat((y_full[k], y_hat[k]), dim=1)
    if single_example:
        return {k: v[0].cpu() for k, v in y_full.items()}
    return {k: v.cpu() for k, v in y_full.items()}


def _as_grand_staff(score, name: str):
    """Turn M2S's two plain parts (RH / LH) into one braced piano part.

    music21 joins ``PartStaff`` objects grouped by a ``StaffGroup`` into a single
    MusicXML ``<part>`` with ``<staves>2</staves>``.
    """
    from music21 import instrument, layout, stream

    parts = list(score.parts)
    if len(parts) != 2:
        return score
    out = stream.Score()
    staffs = []
    for idx, p in enumerate(parts):
        ps = stream.PartStaff()
        for el in list(p.elements):
            if isinstance(el, instrument.Instrument):
                continue
            ps.insert(p.elementOffset(el), el)
        ps.id = f"P1-Staff{idx + 1}"
        staffs.append(ps)
    piano = instrument.Piano()
    piano.partName = name
    piano.partAbbreviation = name[:6] if len(name) <= 6 else None
    staffs[0].insert(0, piano)
    staffs[0].partName = name
    for ps in staffs:
        out.insert(0, ps)
    out.insert(0, layout.StaffGroup(staffs, name=name, symbol="brace", barTogether=True))
    return out


def _count_notes(midi_path: str) -> int:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(midi_path)
    return sum(len(i.notes) for i in pm.instruments if not i.is_drum)


def _handle(req: dict, *, torch, model, Tokenizer, postprocess_score) -> dict:
    midi = str(req.get("midi") or "")
    out = str(req.get("out") or "")
    name = str(req.get("name") or "Piano").strip() or "Piano"
    if not midi or not Path(midi).is_file():
        return {"ok": False, "error": f"MIDI not found: {midi}"}
    if not out:
        return {"ok": False, "error": "missing 'out'"}
    n_notes = _count_notes(midi)
    if n_notes == 0:
        return {"ok": False, "error": "MIDI has no pitched notes"}

    x = Tokenizer.tokenize_midi(midi)
    with torch.inference_mode():
        y_hat = _infer(torch, x, model)
    mxl = Tokenizer.detokenize_mxl(y_hat)
    mxl = postprocess_score(mxl)
    try:
        mxl = _as_grand_staff(mxl, name)
    except Exception as exc:  # keep two plain staves rather than fail
        print(f"[m2s] grand-staff grouping failed: {exc}", file=sys.stderr)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".part")
    # Upstream: scores must be written with makeNotation=False.
    mxl.write("musicxml", fp=str(tmp), makeNotation=False)
    written = tmp if tmp.is_file() else tmp.with_suffix(tmp.suffix + ".musicxml")
    if not written.is_file() or written.stat().st_size == 0:
        return {"ok": False, "error": "music21 did not write MusicXML"}
    os.replace(written, out_path)
    return {"ok": True, "notes": n_notes}


def main() -> int:
    root = os.environ.get("M2S_ROOT", "").strip()
    ckpt = os.environ.get("M2S_CKPT", "").strip()
    try:
        if not root or not (Path(root) / "midi2scoretransformer").is_dir():
            raise RuntimeError(f"M2S_ROOT is not a MIDI2ScoreTransformer checkout: {root!r}")
        if not ckpt or not Path(ckpt).is_file():
            raise RuntimeError(f"M2S_CKPT not found: {ckpt!r}")
        # Upstream modules use flat imports (``from constants import …``).
        sys.path.insert(0, str(Path(root) / "midi2scoretransformer"))

        import torch
        from models.roformer import Roformer
        from score_utils import postprocess_score
        from tokenizer import MultistreamTokenizer

        device = _pick_device(torch, os.environ.get("M2S_DEVICE", "auto"))
        model = Roformer.load_from_checkpoint(ckpt, map_location="cpu")
        model.to(device)
        model.eval()
    except Exception as exc:
        traceback.print_exc()
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _emit({"ready": True, "device": device})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({"ok": False, "error": f"bad JSON: {exc}"})
            continue
        rid = req.get("id")
        if req.get("cmd") == "ping":
            _emit({"id": rid, "ok": True})
            continue
        if req.get("cmd") == "exit":
            _emit({"id": rid, "ok": True})
            break
        try:
            resp = _handle(
                req,
                torch=torch,
                model=model,
                Tokenizer=MultistreamTokenizer,
                postprocess_score=postprocess_score,
            )
        except Exception as exc:
            traceback.print_exc()
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        resp["id"] = rid
        _emit(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
