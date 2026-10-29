"""Chinese text helpers: script conversion and character classes."""

from __future__ import annotations

import unicodedata
from functools import lru_cache

from .data import Transcript

SENTENCE_END = set("。！？!?…;；")
SOFT_BREAK = set("，、,：:；;")


@lru_cache(maxsize=2)
def _converter(script: str):
    import opencc

    return opencc.OpenCC({"simplified": "t2s", "traditional": "s2t"}[script])


def convert_text(text: str, script: str) -> str:
    if script == "none" or not text:
        return text
    return _converter(script).convert(text)


def convert_transcript(tr: Transcript, script: str) -> None:
    """Convert every word in place. Word boundaries (and so timings) are preserved."""
    if script == "none":
        return
    for seg in tr.segments:
        for w in seg.words:
            w.text = convert_text(w.text, script)
        seg.text = "".join(w.text for w in seg.words).strip()


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF   # Extension A
        or 0x20000 <= cp <= 0x2EBEF # Extensions B-F
        or 0xF900 <= cp <= 0xFAFF   # Compatibility Ideographs
        or 0x3000 <= cp <= 0x303F   # CJK punctuation
        or 0xFF00 <= cp <= 0xFFEF   # Full-width forms
    )


def display_width(text: str, language: str) -> float:
    """Width in 'characters' as counted by segmentation.max_chars.

    For Chinese, max_chars counts full-width characters, so Latin letters,
    digits and spaces count as half a character.
    """
    if language != "zh":
        return float(len(text))
    width = 0.0
    for ch in text:
        if is_cjk(ch) or unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 1.0
        else:
            width += 0.5
    return width
