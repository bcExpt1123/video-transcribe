"""Add subtitles to the video with ffmpeg: burn-in (hard subs) or a soft track."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import paths
from .media import MediaError, MediaInfo

log = logging.getLogger(__name__)

LANG_TAG = {"en": "eng", "zh": "chi"}


def _filter_path(p: Path, cwd: Path) -> str:
    """Path usable inside an ffmpeg filter argument (Windows drive colons escaped)."""
    try:
        rel = os.path.relpath(p, cwd)
    except ValueError:  # different drive on Windows
        rel = str(p)
    rel = rel.replace("\\", "/")
    return "'" + rel.replace("'", r"'\''").replace(":", r"\:") + "'"


def _run_with_progress(cmd: list[str], duration: float, cwd: Path, label: str) -> None:
    log.debug("run: %s", " ".join(cmd))
    show = sys.stderr.isatty() and duration > 0
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(
            cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:],
            cwd=cwd, stdout=subprocess.PIPE, stderr=err, text=True,
            encoding="utf-8", errors="replace",
        )
        started = time.time()
        assert proc.stdout is not None
        for line in proc.stdout:
            if show and line.startswith("out_time_us=") and line.strip()[12:].isdigit():
                frac = min(1.0, int(line.strip()[12:]) / 1e6 / duration)
                sys.stderr.write(
                    f"\r  {label} [{'#' * int(frac * 30):<30}] {frac*100:5.1f}%  {time.time()-started:6.1f}s"
                )
                sys.stderr.flush()
        proc.wait()
        if show:
            sys.stderr.write("\n")
        if proc.returncode != 0:
            err.seek(0)
            tail = "\n".join(err.read().strip().splitlines()[-15:])
            raise MediaError(f"ffmpeg failed ({proc.returncode}):\n{tail}")


def burn(info: MediaInfo, ass_file: Path, out: Path, cfg: dict) -> Path:
    ffmpeg = paths.find_tool("ffmpeg", cfg.get("ffmpeg_path"))
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Run inside the subtitle's folder so filter paths stay simple.
    cwd = ass_file.parent
    vf = f"ass={_filter_path(ass_file, cwd)}"
    if paths.FONTS_DIR.is_dir():
        vf += f":fontsdir={_filter_path(paths.FONTS_DIR, cwd)}"

    enc = cfg["encoding"][info.container]
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-i", str(info.path),
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", vf,
        "-c:v", enc["video_codec"],
    ]
    if enc.get("pix_fmt"):
        cmd += ["-pix_fmt", str(enc["pix_fmt"])]
    if info.container == "mp4":
        cmd += ["-crf", str(enc["crf"]), "-preset", str(enc["preset"]), "-movflags", "+faststart"]
    else:
        cmd += [
            "-crf", str(enc["crf"]), "-b:v", "0", "-row-mt", "1",
            "-cpu-used", str(enc["cpu_used"]), "-deadline", "good",
        ]
    cmd += ["-c:a", "copy", "-map_metadata", "0", str(out)]
    _run_with_progress(cmd, info.duration, cwd, "burning")
    return out


def soft(info: MediaInfo, sub_file: Path, out: Path, cfg: dict, language: str) -> Path:
    """Mux a selectable subtitle track without re-encoding."""
    ffmpeg = paths.find_tool("ffmpeg", cfg.get("ffmpeg_path"))
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    codec = "mov_text" if info.container == "mp4" else "webvtt"
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-i", str(info.path), "-i", str(sub_file),
        "-map", "0:v", "-map", "0:a?", "-map", "1:0",
        "-c:v", "copy", "-c:a", "copy", "-c:s", codec,
        "-metadata:s:s:0", f"language={LANG_TAG.get(language, 'und')}",
        "-disposition:s:0", "default",
        "-map_metadata", "0",
        str(out),
    ]
    _run_with_progress(cmd, info.duration, sub_file.parent, "muxing")
    return out


def copy_if_needed(src: Path, dst: Path) -> Path:
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    return dst
