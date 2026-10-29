#!/usr/bin/env bash
# Launcher: runs the CLI with every cache/model directory pointed inside this project.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HF_HOME="$ROOT/models/hf"
export HF_HUB_CACHE="$ROOT/models/hf/hub"
export HF_HUB_DISABLE_TELEMETRY=1
export TORCH_HOME="$ROOT/models/torch"
export XDG_CACHE_HOME="$ROOT/.runtime/cache"
export PIP_CACHE_DIR="$ROOT/.runtime/pip-cache"
export TMPDIR="$ROOT/.runtime/tmp"
export PYTHONUTF8=1
mkdir -p "$TMPDIR"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$ROOT/.venv/Scripts/python.exe"
if [[ ! -x "$PY" ]]; then echo ".venv not found. Run ./setup.sh first." >&2; exit 1; fi
exec "$PY" -m video_transcribe "$@"
