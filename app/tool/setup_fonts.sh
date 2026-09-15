#!/usr/bin/env bash
# Copy Roboto from the local Flutter SDK so web can run offline (no fonts.gstatic.com).
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
