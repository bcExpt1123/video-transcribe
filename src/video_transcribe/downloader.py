"""Chunked, resumable model downloader.

Large model files are fetched from Hugging Face with HTTP Range requests in pieces of
``chunk_mb`` (default 100 MB). Every piece is retried on its own, so a dropped
connection costs at most one piece, and an interrupted download continues where it
stopped (``<file>.part``). Finished files are verified against the repo's SHA-256.

Models are stored as plain folders in ``models/local/<org>--<name>/`` and loaded
from there, so no network access is needed once a model is complete.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

LOCAL_DIR = paths.MODELS_DIR / "local"
COMPLETE_MARK = ".complete"
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")

WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "preprocessor_config.json")


class DownloadError(RuntimeError):
    pass


def model_dir(repo_id: str) -> Path:
    return LOCAL_DIR / repo_id.replace("/", "--")


def is_complete(repo_id: str) -> bool:
    return (model_dir(repo_id) / COMPLETE_MARK).is_file()


def whisper_repo(name: str) -> str:
    """'small' -> 'Systran/faster-whisper-small'; repo ids pass through."""
    if "/" in name:
        return name
    from faster_whisper.utils import _MODELS

    if name not in _MODELS:
        raise DownloadError(f"unknown whisper model '{name}'. Choose from: {', '.join(_MODELS)}")
    return _MODELS[name]


# --------------------------------------------------------------------- file selection


def _wanted(files: list, kind: str) -> list:
    names = {f.rfilename for f in files}
    out = []
    for f in files:
        n = f.rfilename
        if "/" in n:
            continue
        if kind == "whisper":
            ok = n in WHISPER_FILES or n.startswith("vocabulary.")
        else:  # wav2vec2 (transformers): configs + one weights file
            ok = n.endswith(".json") or n == "model.safetensors" or (
                n == "pytorch_model.bin" and "model.safetensors" not in names
            )
        if ok:
            out.append(f)
    return out


# --------------------------------------------------------------------- helpers


def _fmt(n: float) -> str:
    return f"{n / 1e6:,.0f} MB"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _replace(src: Path, dst: Path) -> None:
    """os.replace with retries (antivirus scanners briefly lock fresh files on Windows)."""
    delay = 0.25
    for attempt in range(15):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 14:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)


def _seed_from_hf_cache(repo_id: str, sibling, part: Path, dest: Path) -> None:
    """Reuse a file (or a partial download) already in the huggingface_hub cache."""
    if dest.exists() or not sibling.lfs:
        return
    cache_roots = [paths.HF_HOME / "hub", paths.HF_HOME / "whisper"]
    folder = "models--" + repo_id.replace("/", "--")
    for root in cache_roots:
        blob = root / folder / "blobs" / sibling.lfs.sha256
        for candidate in (blob, blob.with_name(blob.name + ".incomplete")):
            if candidate.is_file() and candidate.stat().st_size > (part.stat().st_size if part.exists() else 0):
                log.info("  reusing %s already downloaded (%s)", sibling.rfilename, _fmt(candidate.stat().st_size))
                shutil.copyfile(candidate, part)
                return


def _download_file(url: str, part: Path, size: int, chunk: int, retries: int, label: str) -> None:
    import requests

    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    session = requests.Session()
    show = sys.stderr.isatty()
    started = time.time()
    start_have = have
    while have < size:
        end = min(have + chunk, size) - 1
        for attempt in range(1, retries + 1):
            try:
                r = session.get(url, headers={"Range": f"bytes={have}-{end}"}, stream=True, timeout=(15, 60))
                if r.status_code not in (200, 206):
                    raise DownloadError(f"HTTP {r.status_code}")
                if r.status_code == 200 and have > 0:
                    raise DownloadError("server ignored the Range request")
                with open(part, "ab") as f:
                    for block in r.iter_content(1 << 20):
                        f.write(block)
                        if r.status_code == 200 and f.tell() > end + 1:
                            break
                got = part.stat().st_size
                if got < end + 1:
                    raise DownloadError(f"piece incomplete ({got - have} of {end + 1 - have} bytes)")
                if got > end + 1:
                    with open(part, "r+b") as f:
                        f.truncate(end + 1)
                break
            except (requests.RequestException, DownloadError, OSError) as e:
                # Drop whatever arrived of this piece and try the same piece again.
                if part.exists() and part.stat().st_size > have:
                    with open(part, "r+b") as f:
                        f.truncate(have)
                if attempt == retries:
                    raise DownloadError(
                        f"{label}: piece {_fmt(have)}-{_fmt(end + 1)} failed {retries} times: {e}. "
                        "Run the command again to resume."
                    ) from e
                wait = min(2 ** attempt, 30)
                log.warning("  %s: piece at %s failed (%s), retry %d/%d in %ds",
                            label, _fmt(have), e, attempt, retries - 1, wait)
                time.sleep(wait)
        have = end + 1
        speed = (have - start_have) / max(time.time() - started, 1e-6)
        msg = f"  {label}: {_fmt(have)} / {_fmt(size)} ({have * 100 / size:4.1f}%, {speed / 1e6:.1f} MB/s)"
        if show:
            sys.stderr.write("\r" + msg)
            sys.stderr.flush()
        else:
            log.info(msg)
    if show:
        sys.stderr.write("\n")


# --------------------------------------------------------------------- public


def ensure_model(repo_id: str, kind: str, chunk_mb: int = 100, retries: int = 5) -> Path:
    """Download ``repo_id`` into models/local/ (if needed) and return its folder."""
    target = model_dir(repo_id)
    if is_complete(repo_id):
        return target
    from huggingface_hub import HfApi

    try:
        info = HfApi(endpoint=HF_ENDPOINT).model_info(repo_id, files_metadata=True)
    except Exception as e:  # network errors, unknown repo, ...
        raise DownloadError(f"cannot get file list for {repo_id}: {e}") from e
    files = _wanted(info.siblings or [], kind)
    if not files:
        raise DownloadError(f"{repo_id}: no usable model files found")
    total = sum(f.size or 0 for f in files)
    log.info("downloading %s (%s) in %d MB pieces -> %s", repo_id, _fmt(total), chunk_mb, target)
    target.mkdir(parents=True, exist_ok=True)
    chunk = max(1, int(chunk_mb)) * 1024 * 1024

    for f in files:
        dest = target / f.rfilename
        if dest.is_file() and (f.size is None or dest.stat().st_size == f.size):
            continue
        part = dest.with_name(dest.name + ".part")
        _seed_from_hf_cache(repo_id, f, part, dest)
        url = f"{HF_ENDPOINT}/{repo_id}/resolve/{info.sha}/{f.rfilename}"
        size = f.size or 0
        if size:
            _download_file(url, part, size, chunk, retries, f.rfilename)
        else:  # tiny file without a size in the listing
            import requests

            r = requests.get(url, timeout=60)
            r.raise_for_status()
            part.write_bytes(r.content)
        if f.lfs and f.lfs.sha256:
            digest = _sha256(part)
            if digest != f.lfs.sha256:
                part.unlink()
                raise DownloadError(f"{f.rfilename}: checksum mismatch, removed. Run again to re-download.")
        _replace(part, dest)

    (target / COMPLETE_MARK).write_text(info.sha or "", encoding="utf-8")
    log.info("%s ready", repo_id)
    return target


def resolve_whisper(name: str, chunk_mb: int = 100) -> str:
    """Local folder for a whisper model name/repo (downloading if needed)."""
    if Path(name).is_dir():
        return name
    return str(ensure_model(whisper_repo(name), "whisper", chunk_mb))


def resolve_wav2vec2(name: str, chunk_mb: int = 100) -> str:
    if Path(name).is_dir():
        return name
    return str(ensure_model(name, "wav2vec2", chunk_mb))
