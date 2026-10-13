"""Client for the long-lived MIDI2ScoreTransformer worker process.

The worker (``backend/m2s_worker/worker.py``) runs in its own venv and speaks
JSON lines over stdin/stdout. This client starts it lazily, serialises requests
with a lock, enforces timeouts, and restarts it after a crash. M2S is a required
dependency: every failure surfaces as :class:`M2SError` (no fallback).
"""
from __future__ import annotations

import collections
import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Optional, Sequence

from ...logging_zh import get_logger

log = get_logger("piano.m2s")

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
WORKER_SCRIPT = _BACKEND_ROOT / "m2s_worker" / "worker.py"


class M2SError(RuntimeError):
    pass


class M2SClient:
    def __init__(
        self,
        cmd: Sequence[str],
        *,
        env: Optional[dict] = None,
        timeout: float = 900.0,
        startup_timeout: float = 300.0,
    ) -> None:
        self._cmd = list(cmd)
        self._env = env
        self._timeout = float(timeout)
        self._startup_timeout = float(startup_timeout)
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr_tail: collections.deque = collections.deque(maxlen=40)
        self._next_id = 0
        self.device: Optional[str] = None
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------ process
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _stderr_hint(self) -> str:
        tail = [ln for ln in self._stderr_tail if ln.strip()]
        return (" | " + " / ".join(tail[-5:])) if tail else ""

    def _start(self) -> None:
        self._lines = queue.Queue()
        self._stderr_tail.clear()
        env = dict(os.environ)
        if self._env:
            env.update(self._env)
        try:
            proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise M2SError(f"M2S worker 无法启动：{exc}") from exc
        self._proc = proc

        def _pump_stdout(stream, sink):
            for line in stream:
                sink.put(line)
            sink.put(None)

        def _pump_stderr(stream, tail):
            for line in stream:
                tail.append(line.rstrip())
                log.debug("m2s: %s", line.rstrip())

        threading.Thread(target=_pump_stdout, args=(proc.stdout, self._lines), daemon=True).start()
        threading.Thread(target=_pump_stderr, args=(proc.stderr, self._stderr_tail), daemon=True).start()

        log.info("M2S worker 启动中：%s", " ".join(self._cmd))
        hello = self._read_json(self._startup_timeout, what="启动")
        if not hello.get("ready"):
            self._kill()
            raise M2SError(f"M2S worker 启动失败：{hello.get('error') or hello}")
        self.device = hello.get("device")
        log.info("M2S worker 就绪（device=%s）", self.device)

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.stdin.write(json.dumps({"id": -1, "cmd": "exit"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=5)
                except Exception:
                    pass
            self._kill()

    def _read_json(self, timeout: float, *, what: str) -> dict:
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                self._kill()
                raise M2SError(f"M2S worker {what}超时（{timeout:.0f}s）")
            if line is None:
                self._kill()
                raise _WorkerDied(f"M2S worker 意外退出{self._stderr_hint()}")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                log.debug("m2s 非协议输出：%s", line)

    # ----------------------------------------------------------------- requests
    def _request(self, payload: dict) -> dict:
        if not self.running:
            self._start()
        self._next_id += 1
        rid = self._next_id
        payload = {"id": rid, **payload}
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._kill()
            raise _WorkerDied(f"M2S worker 管道断开：{exc}") from exc
        while True:
            resp = self._read_json(self._timeout, what="推理")
            if resp.get("id") in (rid, None):
                return resp

    def _call(self, payload: dict) -> dict:
        with self._lock:
            try:
                return self._request(payload)
            except _WorkerDied as exc:
                log.warning("%s，重启后重试一次", exc)
                try:
                    return self._request(payload)
                except _WorkerDied as exc2:
                    raise M2SError(str(exc2)) from exc2

    def ping(self) -> bool:
        return bool(self._call({"cmd": "ping"}).get("ok"))

    def convert(self, midi_path: str | Path, out_xml: str | Path, *, name: str = "Piano") -> Path:
        midi_path = Path(midi_path).resolve()
        out_xml = Path(out_xml).resolve()
        out_xml.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = self._call({"midi": str(midi_path), "out": str(out_xml), "name": name})
        except M2SError as exc:
            self.last_error = str(exc)
            raise
        if not resp.get("ok"):
            self.last_error = str(resp.get("error") or "unknown error")
            raise M2SError(f"M2S 转谱失败（{midi_path.name}）：{self.last_error}")
        if not out_xml.is_file() or out_xml.stat().st_size == 0:
            raise M2SError(f"M2S 未写出 MusicXML：{out_xml}")
        self.last_error = None
        return out_xml


class _WorkerDied(M2SError):
    pass


# ---------------------------------------------------------------- module API
_client: Optional[M2SClient] = None
_client_lock = threading.Lock()


def config_problems() -> list[str]:
    """Missing pieces of the M2S install (empty list → configured)."""
    from ... import config

    problems = []
    if not Path(config.M2S_PYTHON).is_file():
        problems.append(f"M2S_PYTHON 不存在：{config.M2S_PYTHON}")
    if not (Path(config.M2S_ROOT) / "midi2scoretransformer").is_dir():
        problems.append(f"M2S_ROOT 不是 MIDI2ScoreTransformer 仓库：{config.M2S_ROOT}")
    if not Path(config.M2S_CKPT).is_file():
        problems.append(f"M2S_CKPT 不存在：{config.M2S_CKPT}")
    if not WORKER_SCRIPT.is_file():
        problems.append(f"worker 脚本缺失：{WORKER_SCRIPT}")
    return problems


def get_client() -> M2SClient:
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        problems = config_problems()
        if problems:
            raise M2SError(
                "MIDI2ScoreTransformer 未安装（运行 backend/m2s_worker/setup_m2s.sh）："
                + "；".join(problems)
            )
        from ... import config

        _client = M2SClient(
            [config.M2S_PYTHON, str(WORKER_SCRIPT)],
            env={
                "M2S_ROOT": config.M2S_ROOT,
                "M2S_CKPT": config.M2S_CKPT,
                "M2S_DEVICE": config.M2S_DEVICE,
                "PYTHONUNBUFFERED": "1",
            },
            timeout=config.M2S_TIMEOUT,
            startup_timeout=config.M2S_STARTUP_TIMEOUT,
        )
        return _client


def set_client(client: Optional[M2SClient]) -> None:
    """Replace the shared client (tests / shutdown)."""
    global _client
    with _client_lock:
        old, _client = _client, client
    if old is not None and old is not client:
        old.close()


def status() -> dict:
    """Cheap health info — never spawns the worker."""
    problems = [] if _client is not None else config_problems()
    return {
        "m2s_ready": not problems,
        "m2s_running": bool(_client and _client.running),
        "m2s_device": _client.device if _client else None,
        "m2s_error": "；".join(problems) if problems else (_client.last_error if _client else None),
    }


def midi_to_musicxml_m2s(midi_path: str | Path, out_xml: str | Path, *, name: str = "Piano") -> Path:
    return get_client().convert(midi_path, out_xml, name=name)
