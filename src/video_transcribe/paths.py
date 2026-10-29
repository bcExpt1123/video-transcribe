"""Project-local directories.

Importing this module points every cache used by Hugging Face, PyTorch, pip etc. at
folders inside the project, so nothing is written to the user's system cache folders.
It must be imported before any heavy library (``video_transcribe/__main__`` does that).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# src/video_transcribe/paths.py -> project root is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

RUNTIME_DIR = PROJECT_ROOT / ".runtime"
FFMPEG_BIN_DIR = RUNTIME_DIR / "ffmpeg" / "bin"
TMP_DIR = RUNTIME_DIR / "tmp"
MODELS_DIR = PROJECT_ROOT / "models"
HF_HOME = MODELS_DIR / "hf"
TORCH_HOME = MODELS_DIR / "torch"
FONTS_DIR = PROJECT_ROOT / "fonts"
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

_LOCAL_ENV = {
    "HF_HOME": HF_HOME,
    "HF_HUB_CACHE": HF_HOME / "hub",
    "TORCH_HOME": TORCH_HOME,
    "XDG_CACHE_HOME": RUNTIME_DIR / "cache",
    "PIP_CACHE_DIR": RUNTIME_DIR / "pip-cache",
}


def apply_local_env() -> None:
    """Force caches into the project. Called once at import time."""
    for key, value in _LOCAL_ENV.items():
        os.environ.setdefault(key, str(value))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for key in ("TMP", "TEMP", "TMPDIR"):
        os.environ[key] = str(TMP_DIR)
    import tempfile

    tempfile.tempdir = str(TMP_DIR)


apply_local_env()


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def find_tool(name: str, configured_dir: str | None = None) -> str:
    """Locate ffmpeg/ffprobe: configured dir -> bundled .runtime/ffmpeg/bin -> PATH."""
    candidates = []
    if configured_dir:
        p = Path(configured_dir)
        # Allow pointing directly at an ffmpeg executable or at its folder.
        candidates.append(p.parent / _exe(name) if p.is_file() else p / _exe(name))
    candidates.append(FFMPEG_BIN_DIR / _exe(name))
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name} not found. Run setup.ps1 / setup.sh, or set 'ffmpeg_path' in your config."
    )


def is_inside_project(path: str | os.PathLike) -> bool:
    try:
        Path(path).resolve().relative_to(PROJECT_ROOT)
        return True
    except ValueError:
        return False
