#!/usr/bin/env bash
# Install local fonts so Flutter Web can run offline (no fonts.gstatic.com):
#   - Roboto from the Flutter SDK (Latin UI)
#   - Noto Sans SC subset (Simplified Chinese UI + score titles)
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FLUTTER_BIN="$(command -v flutter || true)"
if [[ -z "$FLUTTER_BIN" ]]; then
  FLUTTER_BIN="${APP_DIR}/../.toolchain/flutter/bin/flutter"
fi
ROOT="$(cd "$(dirname "$FLUTTER_BIN")/.." && pwd)"
SRC="$ROOT/bin/cache/artifacts/material_fonts"
DST="$APP_DIR/assets/fonts"
mkdir -p "$DST"

cp -f "$SRC/Roboto-Regular.ttf" "$SRC/Roboto-Medium.ttf" "$SRC/Roboto-Bold.ttf" "$DST/"
echo "Copied Roboto fonts into $DST"

NOTO="$DST/NotoSansSC-Regular.otf"
if [[ ! -f "$NOTO" || ! -s "$NOTO" ]]; then
  echo "Downloading Noto Sans SC (Simplified Chinese subset)…"
  URL="https://cdn.jsdelivr.net/gh/googlefonts/noto-cjk@main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
  curl -fsSL --retry 3 -o "$NOTO" "$URL"
fi
echo "Noto Sans SC ready: $NOTO ($(du -h "$NOTO" | awk '{print $1}'))"
