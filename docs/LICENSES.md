# 开源组件与许可说明 (License notes)

**项目决策（2026-09）：** 产品侧明确要求优先使用成熟组件提升识别/转录质量，
**不再以规避 GPL/AGPL 作为技术选型硬约束**。下列组件可按需要引入；若对外
商用分发，仍须由法务确认 GPL 传染面与源码提供义务。

## 客户端 (Flutter / Dart)

| 组件 | 用途 | 许可 | 备注 |
| --- | --- | --- | --- |
| Flutter / Dart | 框架 | BSD-3 | |
| `jianpu_core`（自研） | 简谱解析 + MusicXML/MIDI/试听 WAV | 本项目 | 主路径仍自研 IR |
| `verovio_flutter` / Verovio | 五线谱刻谱 | LGPL-3.0 | FFI 动态链接 |
| `pitch_detector_dart` | 端上音高 | MIT | |
| 其余 UI/导出依赖 | 见 `app/pubspec.yaml` | MIT/BSD/Apache | |

## 后端 — 现用成熟栈

| 组件 | 用途 | 许可 | 备注 |
| --- | --- | --- | --- |
| **OpenCV** (`opencv-python-headless`) | 简谱 OMR：纠偏、投影分行、主旋律条带切割 | Apache-2.0 | 主 OMR 引擎 |
| Tesseract + pytesseract | 旋律数字 OCR | Apache-2.0 | 白名单不含 `'` |
| Pillow | 图像备选路径 | HPND | OpenCV 不足时回退 |
| ffmpeg | 音视频抽轨 | LGPL/GPL 构建均可 | |
| HT-Demucs | 人声/伴奏分离（主旋律取 vocals） | MIT | |
| Basic Pitch | 音频→MIDI | Apache-2.0 | |
| **MuScriptor** | 音频→多乐器 MIDI（默认） | 代码 MIT；权重 **CC BY-NC 4.0** | 需 HF 许可 + `HF_TOKEN`；非商用权重 |
| **MuseScore**（可选 CLI） | MIDI→MusicXML 排谱 | GPL-3.0 | 安装后自动优先于 music21；`MUSESCORE_PATH` |
| mt3-infer（MT3 PyTorch 族） | 音频→多乐器 MIDI | MIT（工具包）；权重各仓库自有许可 | 首次自动下载 checkpoint |
| **librosa** | 节拍估计 + MIDI 网格量化 | ISC | |
| **aubio**（可选） | GPL 节拍跟踪备选 | **GPL-3.0** | 已接线，安装即用 |
| pretty_midi / music21 | MIDI 主旋律 skyline、MusicXML | MIT / BSD | |
| **jianpu-ly** | 简谱→LilyPond 可选导出 | **GPL-3.0** | `pipeline/jianpu_ly_export.py` |

## 简谱 → 五线谱

主路径不变：`jianpu_core` DSL/IR → MusicXML → Verovio。  
可选：jianpu-ly → LilyPond（适合需要 LilyPond 排版时）。

## 音视频 → 五线谱（多乐器默认）

`extract → MuScriptor（完整混音，可选拍网格量化）→ 多轨 MIDI → MuseScore CLI（优先）/ music21 → MusicXML`  

客户端勾选音轨后导出 / 试听（试听在 App 内用 MIDI 合成）。  
备选：`model=mt3` / `basic_pitch`；人声可用 `model=crepe`。

## 历史「规避列表」（已解除硬限制）

此前为商用传染顾虑而避免的组件，现允许按效果选用：

- jianpu-ly（GPL）— 已接入可选导出
- aubio（GPL）— 已接入可选节拍
- TarsosDSP（GPL）— 端上仍用 MIT 方案，需要时可再换
- Ultralytics YOLO（AGPL）— 若做检测式 OMR 可评估
