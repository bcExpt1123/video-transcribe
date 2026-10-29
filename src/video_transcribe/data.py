"""Plain data types passed between pipeline steps (JSON serialisable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Word:
    text: str            # as produced by Whisper (EN words carry a leading space)
    start: float         # seconds on the video timeline
    end: float
    score: float = 1.0   # Whisper probability or alignment confidence
    aligned: bool = False


@dataclass
class Segment:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[Segment]
    model: str = ""
    aligned: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs = [
            Segment(
                text=s["text"], start=s["start"], end=s["end"],
                words=[Word(**w) for w in s.get("words", [])],
            )
            for s in d["segments"]
        ]
        return cls(
            language=d["language"], duration=d["duration"], segments=segs,
            model=d.get("model", ""), aligned=d.get("aligned", False),
        )


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)
