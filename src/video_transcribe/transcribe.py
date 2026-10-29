"""Speech-to-text with faster-whisper (local, CPU friendly)."""

from __future__ import annotations

import logging
import sys
import time

import numpy as np

from .data import Segment, Transcript, Word
from .media import SAMPLE_RATE

log = logging.getLogger(__name__)

# Nudges Whisper towards Simplified Chinese with punctuation.
ZH_PROMPT = "以下是普通话的句子，使用简体中文和标点符号。"


def load_model(tcfg: dict, dcfg: dict | None = None):
    from faster_whisper import WhisperModel

    from . import downloader

    dcfg = dcfg or {}
    model_path = downloader.resolve_whisper(tcfg["model"], int(dcfg.get("chunk_mb", 100)))
    log.info("loading whisper model '%s' (%s, %s)", tcfg["model"], tcfg["device"], tcfg["compute_type"])
    return WhisperModel(
        model_path,
        device=tcfg["device"],
        compute_type=tcfg["compute_type"],
        cpu_threads=int(tcfg.get("cpu_threads") or 0),
    )


def detect_language(model, audio: np.ndarray, use_vad: bool) -> tuple[str, float]:
    """Pick between English and Chinese only."""
    try:
        _, _, probs = model.detect_language(audio=audio, vad_filter=use_vad)
        scores = dict(probs)
    except (AttributeError, TypeError):
        # Older faster-whisper: fall back to the first 30 s of a normal run.
        _, info = model.transcribe(audio[: 30 * SAMPLE_RATE], vad_filter=use_vad)
        scores = dict(info.all_language_probs or [(info.language, info.language_probability)])
    en, zh = scores.get("en", 0.0), scores.get("zh", 0.0)
    best = max(scores.items(), key=lambda kv: kv[1])
    if best[0] not in ("en", "zh"):
        log.warning(
            "detected language '%s' (p=%.2f) is not supported; using %s. Pass --lang to choose.",
            best[0], best[1], "zh" if zh > en else "en",
        )
    lang = "zh" if zh > en else "en"
    return lang, max(en, zh)


def _progress(done: float, total: float, started: float) -> None:
    if not sys.stderr.isatty() or total <= 0:
        return
    frac = min(1.0, done / total)
    bar = "#" * int(frac * 30)
    sys.stderr.write(f"\r  transcribing [{bar:<30}] {frac*100:5.1f}%  {time.time()-started:6.1f}s")
    sys.stderr.flush()


def transcribe(audio: np.ndarray, language: str, tcfg: dict, model=None) -> Transcript:
    model = model or load_model(tcfg)
    duration = len(audio) / SAMPLE_RATE
    use_vad = bool(tcfg.get("vad", True))

    if language == "auto":
        language, p = detect_language(model, audio, use_vad)
        log.info("detected language: %s (p=%.2f)", language, p)

    prompt = tcfg.get("initial_prompt")
    if language == "zh":
        prompt = f"{ZH_PROMPT}{prompt or ''}"

    vad_params = {
        "min_silence_duration_ms": int(tcfg.get("vad_min_silence_ms", 500)),
        "speech_pad_ms": int(tcfg.get("vad_speech_pad_ms", 200)),
    }
    seg_iter, _info = model.transcribe(
        audio,
        language=language,
        task="transcribe",
        beam_size=int(tcfg.get("beam_size", 5)),
        word_timestamps=True,
        vad_filter=use_vad,
        vad_parameters=vad_params if use_vad else None,
        # Not feeding previous text back prevents runaway repetition and
        # timestamp drift on long videos.
        condition_on_previous_text=False,
        initial_prompt=prompt,
    )

    segments: list[Segment] = []
    started = time.time()
    for s in seg_iter:
        words = [
            Word(text=w.word, start=float(w.start), end=float(w.end), score=float(w.probability))
            for w in (s.words or [])
            if w.word.strip()
        ]
        if not words:
            continue
        segments.append(Segment(text=s.text.strip(), start=words[0].start, end=words[-1].end, words=words))
        _progress(s.end, duration, started)
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    return Transcript(language=language, duration=duration, segments=segments, model=tcfg["model"])
