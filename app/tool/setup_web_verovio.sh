#!/usr/bin/env bash
# Copies the Verovio web runtime (WASM toolkit + web worker) from the
# verovio_flutter package into app/web/ so that `flutter build web` / `flutter run
# -d chrome` can render staff notation in the browser.
#
# These files are large, vendored binaries that ship inside the pub package, so
# they are intentionally NOT committed to git. Run this once after `flutter pub
# get` when you want to build the *web* target. The Android/iOS targets do not
# need it.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

# Resolve the verovio_flutter package location from the pub cache.
PKG_URI="$(flutter pub deps --style=compact 2>/dev/null | true)"
VEROVIO_DIR="$(find "${PUB_CACHE:-$HOME/.pub-cache}" -type d -path '*verovio_flutter-*/web' 2>/dev/null | sort | tail -1)"

if [[ -z "${VEROVIO_DIR}" || ! -d "${VEROVIO_DIR}" ]]; then
  echo "ERROR: could not locate verovio_flutter package web assets in the pub cache." >&2
  echo "       Run 'flutter pub get' first, and ensure PUB_CACHE is set correctly." >&2
  exit 1
fi

echo "Copying Verovio web runtime from: ${VEROVIO_DIR}"
mkdir -p web/verovio
cp -f "${VEROVIO_DIR}/verovio_worker.dart.js" web/verovio_worker.dart.js
cp -Rf "${VEROVIO_DIR}/verovio/." web/verovio/
echo "Done. web/verovio/ and web/verovio_worker.dart.js are ready."
