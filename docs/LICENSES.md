# 开源组件与许可合规 (License compliance)

目标:面向商用可分发的 Android App + 云后端,避免 **GPL/AGPL 传染**,并区分「代码许可」与「模型权重许可」。

## 客户端 (Flutter / Dart)

| 组件 | 用途 | 许可 | 备注 |
| --- | --- | --- | --- |
| Flutter / Dart | 框架 | BSD-3 | ✅ |
| `jianpu_core`（自研） | 简谱解析 + MusicXML/MIDI | 本项目 | ✅ 不内嵌 GPL 的 `jianpu-ly` |
| `verovio_flutter` / Verovio | 五线谱刻谱 | **LGPL-3.0** | ✅ 动态链接(FFI)方式使用,闭源 App 可用;需遵守 LGPL 动态链接义务 |
| `flutter_svg` | SVG 显示 | MIT | ✅ |
| `flutter_riverpod`, `go_router` | 状态/路由 | MIT | ✅ |
| `record`, `just_audio` | 录音/播放 | MIT | ✅ |
| `pitch_detector_dart` | 端上音高(YIN) | MIT | ✅ 端上功能2 用,**避免 TarsosDSP(GPL)** |
| `file_picker`, `image_picker`, `permission_handler` | 选择文件/权限 | MIT/BSD | ✅ |
| `pdf`, `printing` | 导出 PDF | Apache-2.0 / MIT | ✅ |
| `http`, `path_provider`, `path` | 网络/存储 | BSD/MIT | ✅ |
| Jianpu OMR (`omr.dart` + `POST /omr`) | 图片简谱纠偏/识别 | 本项目 + Pillow (HPND) | ✅ 端上投影剖面纠偏 + 字形分类;服务端可选 pytesseract(Apache-2.0);手写仍需用户校对 |

## 后端 (Python)

| 组件 | 用途 | 代码许可 | 权重/数据许可 | 备注 |
| --- | --- | --- | --- | --- |
| FastAPI / Starlette | API | MIT / BSD | — | ✅ |
| Celery / Redis-py | 任务队列 | BSD / MIT | — | ✅ |
| ffmpeg | 提取音轨 | **LGPL** 或 GPL | — | ⚠️ 选 **LGPL 构建**(不启用 GPL 组件如 `--enable-gpl`);Debian `ffmpeg` 默认可能含 GPL,分发时改用自建 LGPL 版 |
| HT-Demucs (`demucs`) | 去人声 | MIT | 权重 MIT | ✅ SOTA;`htdemucs`/`htdemucs_ft` |
| Basic Pitch | 复音转录(默认) | Apache-2.0 | 权重 Apache-2.0 | ✅ 轻量、乐器无关 |
| MT3 (Magenta) | 复音转录(高精度可选) | Apache-2.0 | ⚠️ 需核对 checkpoint 许可 | 体积大,按需 |
| music21 | MIDI→MusicXML | BSD | 语料(corpus)另有许可,**不随产品分发 corpus** | ✅ 仅用其转换/量化 API |
| `pretty_midi` | MIDI 处理 | MIT | — | ✅ |
| onnxruntime / PyTorch | 推理运行时 | MIT / BSD | — | ✅ |
| verovio (py) | 服务端校验渲染 | LGPL-3.0 | — | 仅内部校验/可选 |

## 明确规避 (Excluded to avoid GPL/AGPL)

- **TarsosDSP**(GPL)→ 端上音高改用 `pitch_detector_dart`(MIT)。
- **aubio**(GPL)→ onset/节拍自研或用 MIT 方案。
- **jianpu-ly**(GPL)→ 仅参考思路,简谱解析 **完全自研**(`jianpu_core`)。
- **Spleeter**(过时且依赖较重)→ 用 HT-Demucs(MIT)。
- 商用慎用 **Ultralytics YOLOv8/v11**(AGPL)→ 若做简谱图片 OMR,选非 AGPL 检测器或自训练轻量模型。

## 待办核对项 (Checklist before release)

- [ ] 打包/CI 中固定使用 **LGPL ffmpeg** 构建,记录 build flags。
- [ ] 核对 MT3 checkpoint 的分发许可(如启用高精度档)。
- [ ] 随 App 附带 **第三方许可清单**(含 Verovio LGPL 声明与获取源码方式)。
- [ ] 确认不随产品分发 music21 `corpus`(仅用其转换 API)。
- [ ] 若引入简谱 OMR 模型,记录训练数据与权重许可。
