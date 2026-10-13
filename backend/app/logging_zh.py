"""后端处理日志（中文）。

在 uvicorn 终端打印简谱 OMR / 音视频流水线各阶段进度，便于排查。
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False

# 任务 stage 英文码 → 中文说明（写入 store 的仍是英文码，日志用中文）
STAGE_ZH: dict[str, str] = {
    "extract": "提取音轨",
    "separate": "分离主旋律/人声",
    "transcribe": "音频转 MIDI",
    "arrange": "编配主旋律/和弦",
    "midi": "导出 MIDI / 音轨清单",
    "melody": "提取单音主旋律",
    "quantize": "节拍网格量化",
    "musicxml": "生成 MusicXML",
    "abc": "生成 ABC 记谱",
    "pdf": "生成 PDF",
    "done": "完成",
    "error": "失败",
    "queued": "排队中",
    "processing": "处理中",
}


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(level)
    # 压低第三方噪音
    for name in ("uvicorn.access", "multipart", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str = "piano") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def stage_zh(stage: str) -> str:
    return STAGE_ZH.get(stage, stage)
