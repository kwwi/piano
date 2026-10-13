#!/usr/bin/env bash
# Install MIDI2ScoreTransformer for the API's score pipeline.
#
# Creates (by default under backend/.m2s/):
#   venv/                      Python 3.11 venv with torch + music21 fork
#   MIDI2ScoreTransformer/     upstream checkout pinned to M2S_COMMIT
#   MIDI2ScoreTF.ckpt          release v0.0.1 checkpoint (~390 MB)
#
# Env overrides: M2S_HOME, PYTHON311 (base interpreter), M2S_COMMIT.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
M2S_HOME="${M2S_HOME:-$BACKEND/.m2s}"
M2S_COMMIT="${M2S_COMMIT:-115432bda16ca16e0fec2e9465788f2ba369971f}"
REPO_URL="https://github.com/TimFelixBeyer/MIDI2ScoreTransformer.git"
CKPT_URL="https://github.com/TimFelixBeyer/MIDI2ScoreTransformer/releases/download/v0.0.1/MIDI2ScoreTF.ckpt"
CKPT_BYTES=389829880

pick_python() {
  if [[ -n "${PYTHON311:-}" ]]; then
    echo "$PYTHON311"
    return
  fi
  for cand in python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
      command -v "$cand"
      return
    fi
  done
  echo ""
}

PY="$(pick_python)"
if [[ -z "$PY" ]]; then
  echo "python3.11 not found. Install it (e.g. 'brew install python@3.11')" >&2
  echo "or point PYTHON311=/path/to/python3.11." >&2
  exit 1
fi
echo "[m2s] base interpreter: $PY ($("$PY" -V 2>&1))"

mkdir -p "$M2S_HOME"

if [[ ! -x "$M2S_HOME/venv/bin/python" ]]; then
  echo "[m2s] creating venv → $M2S_HOME/venv"
  "$PY" -m venv "$M2S_HOME/venv"
fi
VPY="$M2S_HOME/venv/bin/python"
"$VPY" -m pip install --upgrade pip wheel >/dev/null
echo "[m2s] installing requirements (torch, transformers, music21 fork …)"
"$VPY" -m pip install -r "$HERE/requirements.txt"

REPO="$M2S_HOME/MIDI2ScoreTransformer"
if [[ ! -d "$REPO/.git" ]]; then
  echo "[m2s] cloning $REPO_URL"
  git clone "$REPO_URL" "$REPO"
fi
git -C "$REPO" fetch --quiet origin || true
git -C "$REPO" checkout --quiet "$M2S_COMMIT"
echo "[m2s] repo @ $(git -C "$REPO" rev-parse --short HEAD)"

CKPT="$M2S_HOME/MIDI2ScoreTF.ckpt"
size_of() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1"; }
if [[ ! -f "$CKPT" || "$(size_of "$CKPT")" != "$CKPT_BYTES" ]]; then
  echo "[m2s] downloading checkpoint (~390 MB)"
  curl -L --fail --retry 3 -C - -o "$CKPT.part" "$CKPT_URL"
  mv "$CKPT.part" "$CKPT"
fi
echo "[m2s] checkpoint: $CKPT ($(size_of "$CKPT") bytes)"

echo "[m2s] smoke test: loading model …"
M2S_ROOT="$REPO" M2S_CKPT="$CKPT" M2S_DEVICE="${M2S_DEVICE:-auto}" \
  "$VPY" - "$HERE/worker.py" <<'EOF'
import json, subprocess, sys, os
proc = subprocess.Popen([sys.executable, sys.argv[1]], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, text=True, env=os.environ)
first = json.loads(proc.stdout.readline())
proc.stdin.write(json.dumps({"id": 1, "cmd": "exit"}) + "\n")
proc.stdin.flush()
proc.wait(timeout=60)
if not first.get("ready"):
    sys.exit(f"worker failed: {first.get('error')}")
print(f"[m2s] worker ready on {first.get('device')}")
EOF

cat <<EOF

MIDI2ScoreTransformer installed. Defaults already match this layout; to use a
different location add to backend/.env:

  M2S_PYTHON=$VPY
  M2S_ROOT=$REPO
  M2S_CKPT=$CKPT
EOF
