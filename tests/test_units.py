import numpy as np
import pytest

from video_transcribe import config, subtitles
from video_transcribe.align import ctc_viterbi
from video_transcribe.chinese import display_width
from video_transcribe.data import Cue, Word
from video_transcribe.media import parse_probe
from video_transcribe.segment import build_cues, group_words, time_cues, wrap_lines
from video_transcribe.data import Segment, Transcript

SEG = config.load_config()["segmentation"]


# ------------------------------------------------------------------ time formats

@pytest.mark.parametrize("t,srt,ass", [
    (0, "00:00:00,000", "0:00:00.00"),
    (1.2346, "00:00:01,235", "0:00:01.23"),
    (59.9996, "00:01:00,000", "0:01:00.00"),
    (3725.006, "01:02:05,006", "1:02:05.01"),
])
def test_time_formats(t, srt, ass):
    assert subtitles.srt_time(t) == srt
    assert subtitles.ass_time(t) == ass
    assert subtitles.vtt_time(t) == srt.replace(",", ".")


def test_quantize_never_overlaps():
    cues = [Cue(1.004, 2.006, ["a"]), Cue(2.004, 3.0, ["b"])]
    q = subtitles._quantize(cues, 0.01)
    assert q[1][0] >= q[0][1]


def test_srt_roundtrip():
    cues = [Cue(1.0, 2.5, ["hello", "world"]), Cue(3.25, 4.0, ["你好"])]
    parsed = subtitles.parse_srt_or_vtt(subtitles.to_srt(cues))
    assert [(c.start, c.end, c.lines) for c in parsed] == [(c.start, c.end, c.lines) for c in cues]
    parsed = subtitles.parse_srt_or_vtt(subtitles.to_vtt(cues))
    assert [c.start for c in parsed] == [1.0, 3.25]


# ------------------------------------------------------------------ ASS style

def test_ass_color():
    assert subtitles.ass_color("#FFFFFF") == "&H00FFFFFF"
    assert subtitles.ass_color("#112233") == "&H00332211"
    assert subtitles.ass_color("#80000000") == "&H7F000000"
    assert subtitles.ass_color("#00FF0000") == "&HFF0000FF"


def test_ass_style_scales_with_height():
    st = config.style_for(config.load_config(), "en")
    line = subtitles.ass_style_line(st, 540)
    fields = line.split(": ", 1)[1].split(",")
    assert fields[1] == "Noto Sans SC"
    assert float(fields[2]) == pytest.approx(26)       # 52 px at 1080p -> 26 px at 540p
    assert fields[18] == "2"                           # bottom-center


def test_ass_escapes_braces():
    out = subtitles.to_ass([Cue(0, 1, ["a {b}", "c"])], config.style_for(config.load_config(), "en"), 1920, 1080)
    assert "a ｛b｝\\Nc" in out


# ------------------------------------------------------------------ config

def test_config_merge_and_override(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("style:\n  font_size: 70\n  overrides:\n    zh: {primary_color: '#FFFF00'}\n", encoding="utf-8")
    cfg = config.load_config(f, {"output": {"mode": "soft"}})
    assert cfg["style"]["font_size"] == 70
    assert cfg["style"]["outline"] == 2.5         # untouched default kept
    assert cfg["output"]["mode"] == "soft"
    assert config.style_for(cfg, "zh")["primary_color"] == "#FFFF00"
    assert config.style_for(cfg, "en")["primary_color"] == "#FFFFFF"


def test_config_unknown_key_suggests(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("style:\n  font_szie: 70\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="font_size"):
        config.load_config(f)


def test_config_bad_values(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("style:\n  primary_color: white\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load_config(f)
    with pytest.raises(config.ConfigError):
        config.load_config(None, {"output": {"mode": "hard"}})


# ------------------------------------------------------------------ media

def test_probe_offset():
    data = {
        "format": {"start_time": "0.000", "duration": "10.0"},
        "streams": [
            {"codec_type": "video", "codec_name": "vp9", "width": 1280, "height": 720, "start_time": "0.000"},
            {"codec_type": "audio", "codec_name": "opus", "start_time": "1.500"},
        ],
    }
    from pathlib import Path

    info = parse_probe(Path("x.webm"), data)
    assert info.container == "webm"
    assert info.audio_offset == pytest.approx(1.5)
    assert (info.width, info.height) == (1280, 720)


# ------------------------------------------------------------------ CTC aligner

def _emission(path, C=5, T=None):
    T = T or len(path)
    lp = np.full((T, C), np.log(0.01))
    for t, c in enumerate(path):
        lp[t, c] = np.log(0.96)
    return lp


def test_ctc_viterbi_known_path():
    # blank=0; tokens 1,2,2,3  ("A B B C" with repeated B needing a blank between)
    path = [0, 0, 1, 1, 0, 2, 0, 2, 2, 0, 0, 3, 0]
    spans = ctc_viterbi(_emission(path), [1, 2, 2, 3], blank=0)
    assert [(a, b) for a, b, _ in spans] == [(2, 4), (5, 6), (7, 9), (11, 12)]
    assert all(p > 0.9 for *_, p in spans)


def test_ctc_viterbi_too_short():
    from video_transcribe.align import AlignmentFailed

    with pytest.raises(AlignmentFailed):
        ctc_viterbi(_emission([1, 2]), [1, 2, 2, 3], blank=0)


# ------------------------------------------------------------------ segmentation

def _words(spec):
    """spec: list of (text, start, end)"""
    return [Word(t, s, e) for t, s, e in spec]


def test_split_on_pause_and_sentence():
    words = _words([(" Hello", 0.5, 0.8), (" there.", 0.85, 1.2), (" How", 1.4, 1.6),
                    (" are", 1.6, 1.8), (" you", 3.0, 3.3)])
    groups = group_words(words, "en", SEG)
    assert [[w.text.strip() for w in g] for g in groups] == [["Hello", "there."], ["How", "are"], ["you"]]


def test_cue_timing_rules():
    words = _words([(" One.", 1.00, 1.20), (" Two.", 1.30, 1.50), (" Three", 5.0, 5.4)])
    groups = group_words(words, "en", SEG)
    cues = time_cues(groups, "en", SEG, duration=10)
    # starts lead_in before speech
    assert cues[0].start == pytest.approx(1.00 - SEG["lead_in"])
    # no overlaps, min_gap respected where possible
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start
    # a short cue never runs into the next cue's speech
    assert cues[0].end <= words[1].start
    # every cue covers its own speech
    assert cues[0].end >= 1.20 and cues[2].end >= 5.4
    # min_duration extension into silence
    assert cues[2].end - cues[2].start >= SEG["min_duration"] - 1e-6


def test_max_duration_and_chars():
    words = [Word(f" w{i:02d}", i * 0.5, i * 0.5 + 0.4) for i in range(40)]
    cues = time_cues(group_words(words, "en", SEG), "en", SEG, duration=30)
    for c in cues:
        assert c.end - c.start <= SEG["max_duration"] + 1e-6
        assert len(c.lines) <= SEG["max_lines"]
        assert all(len(l) <= SEG["max_chars"]["en"] for l in c.lines)


def test_wrap_lines_zh_balanced():
    words = [Word(ch, i * 0.2, i * 0.2 + 0.2) for i, ch in enumerate("我们今天来讨论一下视频转录工具的时间轴问题")]
    lines = wrap_lines(words, "zh", 18, 2)
    assert len(lines) == 2
    assert all(display_width(l, "zh") <= 18 for l in lines)
    assert "".join(lines) == "我们今天来讨论一下视频转录工具的时间轴问题"


def test_time_offset_applied():
    seg = dict(SEG, time_offset=2.0)
    tr = Transcript("en", 20, [Segment("Hi.", 1.0, 1.5, _words([(" Hi.", 1.0, 1.5)]))])
    cues = build_cues(tr, seg)
    assert cues[0].start == pytest.approx(3.0 - SEG["lead_in"])
