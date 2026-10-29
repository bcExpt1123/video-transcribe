#!/usr/bin/env bash
# Bootstraps video-transcribe on Linux / macOS. Everything is installed INSIDE this folder.
#
#   ./setup.sh                      # runtime + packages + fonts
#   ./setup.sh --with-models small  # also pre-download models for offline use
#   ./setup.sh --dev                # also install pytest
#
# ffmpeg: on Linux x86_64 a static build is downloaded into .runtime/ffmpeg/bin.
# On other platforms, put ffmpeg + ffprobe (with libass) into .runtime/ffmpeg/bin yourself,
# or set `ffmpeg_path` in your YAML config.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/.runtime"
UV_DIR="$RUNTIME/uv"
FF_BIN="$RUNTIME/ffmpeg/bin"
FONTS="$ROOT/fonts"
TMPD="$RUNTIME/tmp"

WITH_MODELS=""
DEV=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-models) WITH_MODELS="${2:-small}"; shift 2 || shift ;;
    --dev) DEV=1; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

mkdir -p "$UV_DIR" "$FF_BIN" "$FONTS" "$TMPD"

export UV_CACHE_DIR="$RUNTIME/uv-cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_PYTHON_PREFERENCE=only-managed
export UV_PROJECT_ENVIRONMENT="$ROOT/.venv"
export UV_TOOL_DIR="$RUNTIME/uv-tools"
export UV_NO_MODIFY_PATH=1
export PIP_CACHE_DIR="$RUNTIME/pip-cache"
export TMPDIR="$TMPD"

fetch() { echo "  downloading $1"; curl -fL --retry 3 -o "$2" "$1"; }

# ---------------------------------------------------------------- uv
if [[ ! -x "$UV_DIR/uv" ]]; then
  echo "[1/5] Installing uv into $UV_DIR"
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)  T=uv-x86_64-unknown-linux-gnu ;;
    Linux-aarch64) T=uv-aarch64-unknown-linux-gnu ;;
    Darwin-arm64)  T=uv-aarch64-apple-darwin ;;
    Darwin-x86_64) T=uv-x86_64-apple-darwin ;;
    *) echo "unsupported platform"; exit 1 ;;
  esac
  fetch "https://github.com/astral-sh/uv/releases/latest/download/$T.tar.gz" "$TMPD/uv.tgz"
  tar -xzf "$TMPD/uv.tgz" -C "$TMPD"
  cp "$TMPD/$T/uv" "$UV_DIR/uv"
  rm -rf "$TMPD/uv.tgz" "$TMPD/$T"
else
  echo "[1/5] uv already present"
fi

# ---------------------------------------------------------------- ffmpeg
if [[ ! -x "$FF_BIN/ffmpeg" ]]; then
  if [[ "$(uname -s)-$(uname -m)" == "Linux-x86_64" ]]; then
    echo "[2/5] Installing static ffmpeg into $FF_BIN"
    fetch "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" "$TMPD/ff.txz"
    mkdir -p "$TMPD/ff" && tar -xJf "$TMPD/ff.txz" -C "$TMPD/ff" --strip-components=1
    cp "$TMPD/ff/ffmpeg" "$TMPD/ff/ffprobe" "$FF_BIN/"
    rm -rf "$TMPD/ff" "$TMPD/ff.txz"
  else
    echo "[2/5] Please place ffmpeg and ffprobe (built with libass) into $FF_BIN"
  fi
else
  echo "[2/5] ffmpeg already present"
fi

# ---------------------------------------------------------------- fonts
echo "[3/5] Checking fonts"
BASE="https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC"
for f in NotoSansSC-Regular.otf NotoSansSC-Bold.otf; do
  [[ -f "$FONTS/$f" ]] || fetch "$BASE/$f" "$FONTS/$f"
done

# ---------------------------------------------------------------- python + packages
echo "[4/5] Installing Python 3.12 and packages"
cd "$ROOT"
"$UV_DIR/uv" python install 3.12
if [[ -n "$DEV" ]]; then
  "$UV_DIR/uv" sync --python 3.12 --extra dev
else
  "$UV_DIR/uv" sync --python 3.12
fi

# ---------------------------------------------------------------- models
if [[ -n "$WITH_MODELS" ]]; then
  echo "[5/5] Downloading models"
  "$ROOT/vt.sh" download-models --model "$WITH_MODELS"
else
  echo "[5/5] Skipping model download (use --with-models <size>)"
fi

echo
echo "Done. Try:  ./vt.sh doctor   and   ./vt.sh run path/to/video.mp4"
