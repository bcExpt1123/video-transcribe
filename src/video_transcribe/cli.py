"""Command-line interface: `vt <command> ...` (see docs/USAGE.md)."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from . import __version__, paths
from .config import ConfigError, load_config
from .media import SUPPORTED_EXTENSIONS, MediaError

log = logging.getLogger("video_transcribe")


# --------------------------------------------------------------------- helpers


def _setup_logging(verbose: int, quiet: bool) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=level, format="%(message)s" if not verbose else "%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "urllib3", "huggingface_hub", "filelock", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not verbose else logging.INFO)
    if not verbose:
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


def _collect_inputs(items: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS)
        elif p.is_file():
            files.append(p)
        else:
            raise MediaError(f"not found: {p}")
    if not files:
        raise MediaError("no MP4/WEBM files found")
    return files


def _overrides(args) -> dict:
    o: dict = {}

    def put(section, key, value):
        if value is not None:
            o.setdefault(section, {})[key] = value

    if getattr(args, "lang", None):
        o["language"] = args.lang
    put("transcription", "model", getattr(args, "model", None))
    if getattr(args, "no_align", False):
        put("alignment", "enabled", False)
    put("output", "mode", getattr(args, "mode", None))
    if getattr(args, "formats", None):
        put("output", "formats", [f.strip() for f in args.formats.split(",") if f.strip()])
    if getattr(args, "overwrite", False):
        put("output", "overwrite", True)
    if getattr(args, "keep_work", False):
        put("output", "keep_work_files", True)
    if getattr(args, "offset", None) is not None:
        put("segmentation", "time_offset", args.offset)
    return o


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", help="YAML config file (merged over config/default.yaml)")
    p.add_argument("-o", "--output", help="output folder (default: output/ in the project)")
    p.add_argument("--overwrite", action="store_true", help="replace existing output files")
    p.add_argument("-v", "--verbose", action="count", default=0, help="show debug details")
    p.add_argument("-q", "--quiet", action="store_true", help="only warnings and errors")


def _add_transcribe_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("-l", "--lang", choices=["auto", "en", "zh"], help="spoken language (default: auto)")
    p.add_argument("-m", "--model", help="whisper model: tiny, base, small, medium, large-v3, ...")
    p.add_argument("--no-align", action="store_true", help="skip wav2vec2 forced alignment (faster, less precise)")
    p.add_argument("-f", "--formats", help="subtitle files to write, e.g. srt,ass,vtt")
    p.add_argument("--offset", type=float, help="shift all subtitles by N seconds (+ later / - earlier)")
    p.add_argument("--keep-work", action="store_true", help="keep extracted audio and transcript JSON")


# --------------------------------------------------------------------- commands


def cmd_run(args, mode_default: str | None = None) -> int:
    from . import pipeline

    ov = _overrides(args)
    if mode_default:
        ov.setdefault("output", {})["mode"] = mode_default
    cfg = load_config(args.config, ov)
    out_dir = pipeline.output_dir(cfg, args.output)
    inputs = _collect_inputs(args.inputs)
    models = pipeline.Models()
    failures = 0
    for i, f in enumerate(inputs, 1):
        if len(inputs) > 1:
            log.info("=== (%d/%d) %s", i, len(inputs), f)
        try:
            res = pipeline.process(f, cfg, out_dir, models)
        except (MediaError, FileExistsError, ValueError) as e:
            log.error("error: %s", e)
            failures += 1
            continue
        log.info("done in %.1fs (language: %s, %d cues)", res.seconds, res.language, res.cues)
        for p in res.subtitle_files:
            log.info("  subtitles: %s", p)
        if res.video:
            log.info("  video:     %s", res.video)
    return 1 if failures else 0


def cmd_burn(args) -> int:
    from . import pipeline

    ov = _overrides(args)
    if args.soft:
        ov.setdefault("output", {})["mode"] = "soft"
    cfg = load_config(args.config, ov)
    out_file = None
    out_dir = pipeline.output_dir(cfg, None)
    if args.output:
        o = Path(args.output)
        if o.suffix.lower() in SUPPORTED_EXTENSIONS:
            out_file = o
            out_dir = o.parent
        else:
            out_dir = o
    try:
        res = pipeline.burn_existing(
            Path(args.video), Path(args.subs), cfg, out_dir, args.lang, out_file
        )
    except (MediaError, FileExistsError, ValueError) as e:
        log.error("error: %s", e)
        return 1
    log.info("done in %.1fs -> %s", res.seconds, res.video)
    return 0


def cmd_init_config(args) -> int:
    dest = Path(args.path)
    if dest.exists() and not args.overwrite:
        log.error("%s already exists (use --overwrite)", dest)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.DEFAULT_CONFIG, dest)
    log.info("wrote %s - edit it and pass it with --config %s", dest, dest)
    return 0


def cmd_download_models(args) -> int:
    from . import downloader

    ov = _overrides(args)
    if args.chunk_mb:
        ov.setdefault("download", {})["chunk_mb"] = args.chunk_mb
    cfg = load_config(args.config, ov)
    chunk, retries = int(cfg["download"]["chunk_mb"]), int(cfg["download"]["retries"])

    jobs = [(downloader.whisper_repo(cfg["transcription"]["model"]), "whisper")]
    if not args.no_align:
        langs = [args.lang] if args.lang and args.lang != "auto" else ["en", "zh"]
        jobs += [(cfg["alignment"]["models"][lang], "wav2vec2") for lang in langs]
    try:
        for repo, kind in jobs:
            if downloader.is_complete(repo):
                log.info("%s: already downloaded", repo)
                continue
            downloader.ensure_model(repo, kind, chunk, retries)
    except downloader.DownloadError as e:
        log.error("download failed: %s", e)
        return 1
    log.info("models stored in %s", downloader.LOCAL_DIR)
    return 0


def _dir_size(p: Path) -> str:
    if not p.exists():
        return "missing"
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return f"{total / 1e6:,.0f} MB"


def cmd_doctor(args) -> int:
    import subprocess

    ok = True

    def row(name, value, good=True):
        nonlocal ok
        ok &= good
        print(f"  {'OK ' if good else 'BAD'}  {name:<22} {value}")

    print(f"video-transcribe {__version__}")
    print(f"project: {paths.PROJECT_ROOT}\n")
    row("python", sys.executable, paths.is_inside_project(sys.executable))
    for tool in ("ffmpeg", "ffprobe"):
        try:
            exe = paths.find_tool(tool)
            ver = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
            row(tool, f"{exe}  ({ver[:60]})", paths.is_inside_project(exe))
        except FileNotFoundError as e:
            row(tool, str(e), False)
    try:
        filters = subprocess.run(
            [paths.find_tool("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True
        ).stdout
        row("libass (burn-in)", "available" if " ass " in filters else "MISSING", " ass " in filters)
    except FileNotFoundError:
        pass
    fonts = sorted(p.name for p in paths.FONTS_DIR.glob("*.[ot]tf"))
    row("fonts", ", ".join(fonts) or "none (run setup)", bool(fonts))
    for key in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME", "XDG_CACHE_HOME", "TMP"):
        val = os.environ.get(key, "")
        row(key, val, bool(val) and paths.is_inside_project(val))
    row("models folder", f"{paths.MODELS_DIR} ({_dir_size(paths.MODELS_DIR)})")
    try:
        import ctranslate2
        import faster_whisper
        import torch
        import transformers

        row(
            "packages",
            f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, "
            f"torch {torch.__version__}, transformers {transformers.__version__}",
        )
    except ImportError as e:
        row("packages", str(e), False)
    try:
        load_config(args.config)
        row("config", args.config or str(paths.DEFAULT_CONFIG))
    except ConfigError as e:
        row("config", str(e), False)
    print("\nall good" if ok else "\nsome checks failed (see BAD lines)")
    return 0 if ok else 1


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="vt",
        description="Offline EN/CN video transcription with accurately timed, styled subtitles.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="audio -> transcript -> subtitles -> video (full pipeline)")
    p.add_argument("inputs", nargs="+", help="MP4/WEBM files or folders")
    p.add_argument("--mode", choices=["burn", "soft", "none"], help="how to add subtitles (default: burn)")
    _add_transcribe_opts(p)
    _add_common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("transcribe", help="only write subtitle files (no video output)")
    p.add_argument("inputs", nargs="+", help="MP4/WEBM files or folders")
    _add_transcribe_opts(p)
    _add_common(p)
    p.set_defaults(func=lambda a: cmd_run(a, mode_default="none"))

    p = sub.add_parser("burn", help="add an existing .srt/.vtt/.ass file to a video")
    p.add_argument("video", help="MP4/WEBM file")
    p.add_argument("-s", "--subs", required=True, help="subtitle file (.srt, .vtt or .ass)")
    p.add_argument("-l", "--lang", choices=["auto", "en", "zh"], help="selects style override (default: guess)")
    p.add_argument("--soft", action="store_true", help="add as a soft track instead of burning in")
    p.add_argument("--offset", type=float, help="shift subtitles by N seconds (.srt/.vtt input only)")
    _add_common(p)
    p.set_defaults(func=cmd_burn)

    p = sub.add_parser("init-config", help="copy the default YAML config so you can edit it")
    p.add_argument("path", nargs="?", default="my-config.yaml")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_init_config)

    p = sub.add_parser("download-models", help="pre-download models for offline use")
    p.add_argument("-m", "--model", help="whisper model to download (default: from config)")
    p.add_argument("-l", "--lang", choices=["auto", "en", "zh"], help="alignment model language (default: both)")
    p.add_argument("--no-align", action="store_true", help="skip the alignment models")
    p.add_argument("--chunk-mb", type=int, help="download piece size in MB (default: 100, from config)")
    p.add_argument("-c", "--config")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_download_models)

    p = sub.add_parser("doctor", help="check the installation")
    p.add_argument("-c", "--config")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose, args.quiet)
    try:
        return int(args.func(args) or 0)
    except ConfigError as e:
        log.error("config error: %s", e)
        return 2
    except (MediaError, FileNotFoundError, RuntimeError) as e:
        log.error("error: %s", e)
        return 1
    except KeyboardInterrupt:
        log.error("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
