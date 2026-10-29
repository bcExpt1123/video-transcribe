"""ffprobe / ffmpeg helpers: probing and audio extraction."""

from __future__ import annotations

import json
import logging
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import paths

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".webm"}
SAMPLE_RATE = 16000


class MediaError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    path: Path
    container: str          # "mp4" or "webm"
    duration: float
    width: int
    height: int
    format_start: float     # container start_time (ffmpeg's timeline zero)
    audio_start: float      # audio stream start_time
    video_start: float      # video stream start_time
    audio_codec: str
    video_codec: str

    @property
    def audio_offset(self) -> float:
        """Where the first audio sample sits on ffmpeg's output timeline."""
        return max(0.0, self.audio_start - self.format_start)


def run(cmd: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaError(f"command failed ({proc.returncode}): {Path(cmd[0]).name}\n{tail}")
    return proc


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_probe(path: Path, data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if audio is None:
        raise MediaError(f"{path.name}: no audio stream found")
    if video is None:
        raise MediaError(f"{path.name}: no video stream found")
    duration = _f(fmt.get("duration")) or _f(video.get("duration")) or _f(audio.get("duration"))
    container = "webm" if path.suffix.lower() == ".webm" else "mp4"
    return MediaInfo(
        path=path,
        container=container,
        duration=duration,
        width=int(video.get("width") or 1920),
        height=int(video.get("height") or 1080),
        format_start=_f(fmt.get("start_time")),
        audio_start=_f(audio.get("start_time")),
        video_start=_f(video.get("start_time")),
        audio_codec=audio.get("codec_name", "?"),
        video_codec=video.get("codec_name", "?"),
    )


def probe(path: str | Path, ffmpeg_dir: str | None = None) -> MediaInfo:
    path = Path(path).resolve()
    if not path.is_file():
        raise MediaError(f"file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise MediaError(
            f"{path.name}: unsupported format '{path.suffix}'. Supported: MP4, WEBM"
        )
    ffprobe = paths.find_tool("ffprobe", ffmpeg_dir)
    proc = run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    info = parse_probe(path, json.loads(proc.stdout))
    log.debug(
        "probe: %s %dx%d dur=%.3f start(format=%.3f audio=%.3f video=%.3f)",
        info.container, info.width, info.height, info.duration,
        info.format_start, info.audio_start, info.video_start,
    )
    return info


def extract_audio(info: MediaInfo, out_wav: Path, ffmpeg_dir: str | None = None) -> Path:
    """Decode the first audio track to 16 kHz mono 16-bit WAV on the VIDEO timeline.

    ``aresample=async=1:first_pts=0`` pads the beginning with silence when the audio
    stream starts later than the container (and fills timestamp gaps), so that
    sample N of the WAV is exactly at time N/16000 on the same timeline that the
    burn-in filter and soft-subtitle muxing use. This removes constant offsets caused
    by edit lists, encoder delay, or recordings whose audio begins late.
    """
    ffmpeg = paths.find_tool("ffmpeg", ffmpeg_dir)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run([
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-i", str(info.path),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-af", "aresample=async=1:first_pts=0",
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
        str(out_wav),
    ])
    return out_wav


def load_wav(path: Path) -> np.ndarray:
    """Read a 16 kHz mono 16-bit WAV as float32 in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise MediaError(f"{path}: expected 16 kHz mono 16-bit WAV")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
