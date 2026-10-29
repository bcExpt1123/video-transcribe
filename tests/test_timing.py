"""End-to-end subtitle timing test (slow: runs the real models).

Synthesises speech with Windows TTS at known positions, runs the full pipeline and
checks that every subtitle starts within TOLERANCE of the real speech onset and does
not end before the speech ends.

    .venv\\Scripts\\python.exe -m pytest -m slow -s
"""

import math

import pytest

timing = pytest.importorskip("timing_harness")

pytestmark = pytest.mark.slow

TOLERANCE = 0.15   # seconds
END_SLACK = 0.10   # a cue may end at most this much before the speech ends


@pytest.fixture(scope="module")
def models():
    from video_transcribe import pipeline

    m = pipeline.Models()
    timing.run_case.models = m
    return m


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("variant,delay", [("mp4", 0.0), ("webm", 0.0), ("delayed.webm", 1.0)])
def test_subtitle_timing(models, tmp_path_factory, lang, variant, delay):
    if not timing.tts_available(lang):
        pytest.skip(f"no Windows TTS voice for {lang}")
    work = timing.paths.TMP_DIR / "timing-test"
    wav, truth = timing.build(lang, work)
    video = work / (f"{lang}_{variant}" if delay else f"{lang}.{variant}")
    if not video.exists():
        timing.make_video(wav, video, delay)
    rows, cues = timing.run_case(lang, video, tmp_path_factory.mktemp("out"), truth, delay)
    for tr, start_err, end_err in rows:
        assert not math.isnan(start_err), f"no subtitle for: {tr.text}"
        assert abs(start_err) <= TOLERANCE, f"start off by {start_err*1000:.0f} ms: {tr.text}"
        assert end_err >= -END_SLACK, f"ends {-end_err*1000:.0f} ms before speech: {tr.text}"
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start, "overlapping cues"
