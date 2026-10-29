"""End-to-end processing of one video: audio -> transcript -> cues -> subtitles -> video."""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import chinese, media, paths, render, segment, subtitles
from .config import style_for
from .data import Cue, Transcript

log = logging.getLogger(__name__)


@dataclass
class Result:
    input: Path
    language: str = ""
    video: Path | None = None
    subtitle_files: list[Path] = field(default_factory=list)
    cues: int = 0
    seconds: float = 0.0


class Models:
    """Keeps loaded models alive across a batch of videos."""

    def __init__(self):
        self.whisper = None
        self.aligners: dict[str, object] = {}


def output_dir(cfg: dict, override: str | None = None) -> Path:
    d = Path(override or cfg["output"]["dir"])
    return d if d.is_absolute() else (paths.PROJECT_ROOT / d)


def output_names(info: media.MediaInfo, cfg: dict, out_dir: Path, language: str) -> dict[str, Path]:
    stem = info.path.stem
    names = {fmt: out_dir / f"{stem}.{language}.{fmt}" for fmt in cfg["output"]["formats"]}
    if cfg["output"]["mode"] != "none":
        names["video"] = out_dir / f"{stem}{cfg['output']['suffix']}{info.path.suffix.lower()}"
    return names


def _check_overwrite(files: list[Path], cfg: dict, input_path: Path) -> None:
    for f in files:
        if f.resolve() == input_path.resolve():
            raise FileExistsError(f"output would overwrite the input file: {f}")
        if f.exists() and not cfg["output"]["overwrite"]:
            raise FileExistsError(f"{f} already exists (use --overwrite)")


def transcribe_video(info: media.MediaInfo, cfg: dict, work: Path, models: Models) -> Transcript:
    from . import transcribe

    ffdir = cfg.get("ffmpeg_path")
    t0 = time.time()
    wav = media.extract_audio(info, work / "audio.wav", ffdir)
    audio = media.load_wav(wav)
    log.info("[1/4] audio extracted (%.1fs of audio, %.1fs)", len(audio) / media.SAMPLE_RATE, time.time() - t0)

    t0 = time.time()
    if models.whisper is None:
        models.whisper = transcribe.load_model(cfg["transcription"], cfg["download"])
    tr = transcribe.transcribe(audio, cfg["language"], cfg["transcription"], models.whisper)
    tr.duration = info.duration or tr.duration
    log.info("[2/4] transcribed: %s, %d segments (%.1fs)", tr.language, len(tr.segments), time.time() - t0)

    if tr.language == "zh":
        chinese.convert_transcript(tr, cfg["chinese"]["script"])

    if cfg["alignment"]["enabled"] and tr.segments:
        from . import align

        t0 = time.time()
        model_name = cfg["alignment"]["models"][tr.language]
        models.aligners[tr.language] = align.align_transcript(
            tr, audio, model_name, float(cfg["alignment"]["min_score"]),
            models.aligners.get(tr.language), int(cfg["download"]["chunk_mb"]),
        )
        log.info("[3/4] word timings aligned (%.1fs)", time.time() - t0)
    else:
        log.info("[3/4] alignment skipped")
    (work / "transcript.json").write_text(
        json.dumps(tr.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return tr


def write_subtitles(cues: list[Cue], info: media.MediaInfo, cfg: dict, names: dict, language: str, work: Path) -> tuple[list[Path], Path, Path]:
    """Write requested formats; also return the ASS and SRT files used for rendering."""
    style = style_for(cfg, language)
    ass_text = subtitles.to_ass(cues, style, info.width, info.height)
    srt_text = subtitles.to_srt(cues)
    written = []
    for fmt, path in names.items():
        if fmt == "srt":
            written.append(subtitles.write(path, srt_text))
        elif fmt == "ass":
            written.append(subtitles.write(path, ass_text))
        elif fmt == "vtt":
            written.append(subtitles.write(path, subtitles.to_vtt(cues)))
    ass_work = subtitles.write(work / "subs.ass", ass_text)
    sub_work = subtitles.write(
        work / ("subs.vtt" if info.container == "webm" else "subs.srt"),
        subtitles.to_vtt(cues) if info.container == "webm" else srt_text,
    )
    return written, ass_work, sub_work


def render_video(info, cfg, names, ass_work, sub_work, language) -> Path | None:
    mode = cfg["output"]["mode"]
    if mode == "burn":
        return render.burn(info, ass_work, names["video"], cfg)
    if mode == "soft":
        return render.soft(info, sub_work, names["video"], cfg, language)
    return None


def _work_dir(cfg: dict, out_dir: Path, stem: str) -> Path:
    if cfg["output"]["keep_work_files"]:
        d = out_dir / f"{stem}_work"
    else:
        d = paths.TMP_DIR / f"job-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process(input_path: Path, cfg: dict, out_dir: Path, models: Models) -> Result:
    started = time.time()
    res = Result(input=input_path)
    info = media.probe(input_path, cfg.get("ffmpeg_path"))
    log.info(
        "%s: %s %dx%d, %.1fs, audio %s starts at %.3fs",
        input_path.name, info.container.upper(), info.width, info.height,
        info.duration, info.audio_codec, info.audio_offset,
    )
    # Fail before the slow work if outputs already exist. With language=auto the
    # subtitle names are not known yet; the video name does not depend on language.
    if cfg["language"] != "auto":
        _check_overwrite(list(output_names(info, cfg, out_dir, cfg["language"]).values()), cfg, input_path)
    elif cfg["output"]["mode"] != "none":
        _check_overwrite([output_names(info, cfg, out_dir, "en")["video"]], cfg, input_path)

    work = _work_dir(cfg, out_dir, input_path.stem)
    try:
        tr = transcribe_video(info, cfg, work, models)
        res.language = tr.language
        names = output_names(info, cfg, out_dir, tr.language)
        _check_overwrite(list(names.values()), cfg, input_path)
        cues = segment.build_cues(tr, cfg["segmentation"])
        if not cues:
            log.warning("no speech found in %s", input_path.name)
        res.cues = len(cues)
        res.subtitle_files, ass_work, sub_work = write_subtitles(cues, info, cfg, names, tr.language, work)
        log.info("[4/4] %d subtitle cues written", len(cues))
        res.video = render_video(info, cfg, names, ass_work, sub_work, tr.language)
    finally:
        if not cfg["output"]["keep_work_files"]:
            shutil.rmtree(work, ignore_errors=True)
    res.seconds = time.time() - started
    return res


def burn_existing(video: Path, subs: Path, cfg: dict, out_dir: Path, language: str | None, out_file: Path | None = None) -> Result:
    """Add an existing SRT/VTT/ASS file to a video (re-style or hand-edited subtitles)."""
    started = time.time()
    info = media.probe(video, cfg.get("ffmpeg_path"))
    res = Result(input=video)
    work = paths.TMP_DIR / f"job-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        if subs.suffix.lower() == ".ass":
            if cfg["output"]["mode"] == "soft":
                raise ValueError("soft mode needs an .srt or .vtt file (use burn mode for .ass)")
            ass_work = render.copy_if_needed(subs, work / "subs.ass")
            sub_work = ass_work
            language = language or "en"
        else:
            cues = subtitles.read_cues(subs)
            if not cues:
                raise ValueError(f"no cues found in {subs}")
            shift = float(cfg["segmentation"].get("time_offset") or 0.0)
            if shift:
                for c in cues:
                    c.start, c.end = max(0.0, c.start + shift), max(0.0, c.end + shift)
                cues = [c for c in cues if c.end > c.start]
            if not language or language == "auto":
                text = "".join(c.text for c in cues)
                cjk = sum(1 for ch in text if chinese.is_cjk(ch))
                language = "zh" if cjk > len(text) * 0.2 else "en"
            style = style_for(cfg, language)
            ass_work = subtitles.write(work / "subs.ass", subtitles.to_ass(cues, style, info.width, info.height))
            ext = "vtt" if info.container == "webm" else "srt"
            sub_work = subtitles.write(
                work / f"subs.{ext}", subtitles.to_vtt(cues) if ext == "vtt" else subtitles.to_srt(cues)
            )
            res.cues = len(cues)
        res.language = language
        mode = cfg["output"]["mode"] if cfg["output"]["mode"] != "none" else "burn"
        target = out_file or out_dir / f"{video.stem}{cfg['output']['suffix']}{video.suffix.lower()}"
        _check_overwrite([target], cfg, video)
        names = {"video": target}
        cfg = {**cfg, "output": {**cfg["output"], "mode": mode}}
        res.video = render_video(info, cfg, names, ass_work, sub_work, language)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    res.seconds = time.time() - started
    return res
