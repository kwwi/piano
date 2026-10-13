# App — 简谱 / 听音 / 音频 转五线谱 (Flutter, Android-first)

Flutter client for the three conversion flows. All three converge on **MusicXML**
and are engraved to staff on-device with **Verovio** (`verovio_flutter`, LGPL).

## Features

1. **简谱转五线谱** (`features/jianpu`) — type/paste jianpu in a small DSL, see a
   live staff preview, and export MusicXML / MIDI / PDF. Fully offline; the
   engine is the pure-Dart [`jianpu_core`](../packages/jianpu_core) package.
2. **听音转五线谱** (`features/listen`) — microphone → `pitch_detector_dart`
   (YIN) → onset segmentation + tempo quantisation → monophonic MusicXML.
   Core logic lives in `jianpu_core`'s `MelodyTranscriber` (unit-tested).
3. **上传音频/视频转五线谱** (`features/upload`) — pick a file (≤100 MB), send to
   the backend, poll progress, render the returned MusicXML. Video audio is
   extracted server-side; vocals are removed before transcription.

## Jianpu DSL

```
key: 1=C        # tonic (also accepts `key: C`)
time: 4/4
tempo: 100
title: 小星星
---
1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
```

| Token | Meaning |
| --- | --- |
| `1`–`7` | scale degrees (movable-do); `0` = rest |
| `'` / `,` | octave up / down (repeatable) |
| `_` | halve duration (`1_` eighth, `1__` sixteenth) |
| `.` | dotted (×1.5) |
| `-` | extend previous note by one beat |
| `#` `b` `n` | sharp / flat / natural (prefix) |
| `\|` | barline |

## Structure

```
lib/
  main.dart, src/app.dart            # entry + go_router
  src/core/jianpu/jianpu.dart        # re-export of jianpu_core
  src/core/notation/                 # Verovio renderer + MusicXML/MIDI/PDF export
  src/core/backend/api_client.dart   # backend client (100MB guard)
  src/features/{home,jianpu,listen,upload}/
  src/widgets/score_view.dart        # MusicXML -> SVG display
```

## Develop

```bash
flutter pub get
flutter run                # Android device / emulator (or iOS Simulator)
flutter analyze
```

### Web (Chrome) — 国内网络注意

默认会从 `gstatic.com` 拉 CanvasKit / 字体，常被墙导致白屏。请用本地资源：

```bash
# 首次：拷贝 Verovio web 运行时
bash tool/setup_web_verovio.sh

# 关键 CDN，用本机 Flutter SDK 里的 CanvasKit
flutter run -d chrome --no-web-resources-cdn
```

Roboto 已打包进 `assets/fonts/`，不再依赖 `fonts.gstatic.com`。

> The heavy pure-Dart logic is tested in `../packages/jianpu_core`
> (`dart test`), independent of Flutter.
