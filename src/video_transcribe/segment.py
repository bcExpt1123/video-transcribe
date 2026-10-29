"""Turn timed words into subtitle cues.

Timing rules (seconds, from config.segmentation):
  * a cue starts ``lead_in`` before its first word and ends ``end_padding`` after
    its last word
  * short cues are stretched to ``min_duration`` - but only into silence
  * cues never overlap and are separated by at least ``min_gap``
  * a cue never lasts longer than ``max_duration``
Grouping rules: a new cue starts at sentence ends, at pauses >= ``pause_split``,
when the text no longer fits in ``max_lines`` x ``max_chars``, or when the cue would
exceed ``max_duration``.
"""

from __future__ import annotations

import re

from .chinese import SENTENCE_END as ZH_SENTENCE_END
from .chinese import SOFT_BREAK, display_width
from .config import per_language
from .data import Cue, Transcript, Word

SENTENCE_END = set(".?!") | ZH_SENTENCE_END
_space_re = re.compile(r"\s+")


def join_words(words: list[Word], language: str) -> str:
    text = "".join(w.text for w in words)
    text = _space_re.sub(" ", text).strip()
    if language == "zh":
        # Remove spaces Whisper sometimes puts between CJK characters.
        text = re.sub(r"(?<=[　-〿一-鿿＀-￯]) (?=[　-〿一-鿿＀-￯])", "", text)
    return text


def _ends_with(word: Word, chars: set[str]) -> bool:
    t = word.text.strip()
    return bool(t) and t[-1] in chars


# --------------------------------------------------------------------- line breaking


def wrap_lines(words: list[Word], language: str, max_chars: int, max_lines: int) -> list[str] | None:
    """Split words into <= max_lines balanced lines of <= max_chars. None if impossible."""
    full = join_words(words, language)
    if display_width(full, language) <= max_chars or max_lines == 1:
        return [full] if display_width(full, language) <= max_chars else None
    best: tuple[float, list[str]] | None = None
    n = len(words)
    # Try every split point (2-line case recursively generalised).
    for k in range(1, n):
        first = join_words(words[:k], language)
        if display_width(first, language) > max_chars:
            break
        rest = wrap_lines(words[k:], language, max_chars, max_lines - 1)
        if rest is None:
            continue
        lines = [first] + rest
        widths = [display_width(x, language) for x in lines]
        cost = max(widths) - min(widths)
        # Prefer breaking after punctuation.
        if _ends_with(words[k - 1], SOFT_BREAK | SENTENCE_END):
            cost -= max_chars * 0.25
        if best is None or cost < best[0]:
            best = (cost, lines)
    return best[1] if best else None


def _fits(words: list[Word], language: str, max_chars: int, max_lines: int) -> bool:
    if display_width(join_words(words, language), language) > max_chars * max_lines:
        return False
    return wrap_lines(words, language, max_chars, max_lines) is not None


# --------------------------------------------------------------------- grouping


def group_words(words: list[Word], language: str, seg: dict) -> list[list[Word]]:
    max_chars = int(seg["max_chars"][language])
    max_lines = int(seg["max_lines"])
    max_dur = float(seg["max_duration"])
    pause = float(seg["pause_split"])

    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            too_long = (w.end - cur[0].start) > max_dur
            if gap >= pause or too_long or not _fits(cur + [w], language, max_chars, max_lines):
                # Overflow: prefer to cut at the last comma in the latter 2/3 of the cue.
                if gap < pause:
                    cut = _soft_cut(cur)
                    if cut:
                        groups.append(cur[:cut])
                        cur = cur[cut:]
                        if (
                            _fits(cur + [w], language, max_chars, max_lines)
                            and (w.end - cur[0].start) <= max_dur
                        ):
                            cur.append(w)
                            continue
                groups.append(cur)
                cur = []
        cur.append(w)
        if _ends_with(w, SENTENCE_END):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return [g for g in groups if join_words(g, language)]


def _soft_cut(cur: list[Word]) -> int | None:
    lo = max(1, len(cur) // 3)
    for i in range(len(cur) - 1, lo - 1, -1):
        if _ends_with(cur[i], SOFT_BREAK):
            return i + 1 if i + 1 < len(cur) else None
    return None


# --------------------------------------------------------------------- timing


def time_cues(groups: list[list[Word]], language: str, seg: dict, duration: float) -> list[Cue]:
    lead = float(seg["lead_in"])
    pad = float(per_language(seg["end_padding"], language))
    min_dur = float(seg["min_duration"])
    max_dur = float(seg["max_duration"])
    gap = float(seg["min_gap"])
    offset = float(seg.get("time_offset", 0.0))
    max_chars = int(seg["max_chars"][language])
    max_lines = int(seg["max_lines"])

    raw = [(g[0].start + offset, g[-1].end + offset) for g in groups]
    starts = [max(0.0, s - lead) for s, _ in raw]
    # A cue may not start before the previous cue's speech has finished.
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], raw[i - 1][1] + gap / 2)
        starts[i] = min(starts[i], raw[i][0])

    cues: list[Cue] = []
    for i, g in enumerate(groups):
        start = starts[i]
        speech_end = raw[i][1]
        end = speech_end + pad
        end = max(end, start + min_dur)
        end = min(end, start + max(max_dur, speech_end - start))
        if i + 1 < len(groups):
            nxt = starts[i + 1]
            end = min(end, nxt - gap)
            # Never cut off our own speech, unless the next cue already starts.
            end = max(end, min(speech_end, nxt))
        if duration > 0:
            end = min(end, duration)
        if end <= start:
            end = start + 0.05
        lines = wrap_lines(g, language, max_chars, max_lines) or [join_words(g, language)]
        cues.append(Cue(start=round(start, 3), end=round(end, 3), lines=lines))
    return cues


def build_cues(tr: Transcript, seg_cfg: dict) -> list[Cue]:
    words = [w for s in tr.segments for w in s.words if w.text.strip()]
    if not words:
        return []
    groups = group_words(words, tr.language, seg_cfg)
    return time_cues(groups, tr.language, seg_cfg, tr.duration)
