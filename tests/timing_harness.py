"""Builds test videos with speech at KNOWN times and measures subtitle timing error.

Uses Windows' built-in SAPI voices (System.Speech) to synthesise phrases, measures
the real speech onset/offset of each phrase from the waveform, places phrases on a
timeline with silences in between, and muxes the result into MP4 / WEBM files
(including a WEBM whose audio stream starts 1 s late, to test offset handling).

Run standalone for a report:
    .venv\\Scripts\\python.exe tests\\timing_harness.py
"""

from __future__ import annotations

import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_transcribe import paths  # noqa: E402

SR = 16000

PHRASES = {
    "en": ("Microsoft Zira Desktop", [
        "The quick brown fox jumps over the lazy dog.",
        "Subtitles must appear exactly when the words are spoken.",
        "Timing accuracy is the most important feature of this tool.",
        "Please check the start and end of every line carefully.",
        "Thank you for watching this short test video.",
    ]),
    "zh": ("Microsoft Huihui Desktop", [
        "今天我们来测试字幕的时间轴是否准确。",
        "每一句话都应该在开始说话的时候出现。",
        "这个工具支持英文和中文两种语言。",
        "谢谢大家观看这个简短的测试视频。",
    ]),
}
GAPS = [1.3, 1.1, 2.0, 0.9, 1.6, 1.2]   # silence before each phrase (s)


@dataclass
class Truth:
    text: str
    onset: float
    offset: float


def tts_available(lang: str) -> bool:
    if sys.platform != "win32":
        return False
    voice = PHRASES[lang][0]
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices()|%{$_.VoiceInfo.Name}"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    return voice in out


def _synth(text: str, voice: str, out: Path) -> None:
    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$s.SetOutputToWaveFile('{out}',$f);"
        f"$s.Speak([IO.File]::ReadAllText('{txt}',[Text.Encoding]::UTF8));$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def _read(p: Path) -> np.ndarray:
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def _speech_bounds(x: np.ndarray) -> tuple[float, float]:
    """First/last 10 ms frame whose RMS is within 35 dB of the loudest frame."""
    hop = SR // 100
    frames = x[: len(x) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms / rms.max())
    idx = np.nonzero(db > -35)[0]
    return idx[0] * hop / SR, (idx[-1] + 1) * hop / SR


def build(lang: str, out_dir: Path) -> tuple[Path, list[Truth]]:
    """Return a WAV with phrases at known positions plus the ground truth."""
    out_dir.mkdir(parents=True, exist_ok=True)
    voice, phrases = PHRASES[lang]
    pieces, truth = [], []
    t = 0.0
    for i, text in enumerate(phrases):
        p = out_dir / f"{lang}_{i}.wav"
        if not p.exists():
            _synth(text, voice, p)
        x = _read(p)
        on, off = _speech_bounds(x)
        gap = np.zeros(int(GAPS[i % len(GAPS)] * SR), dtype=np.float32)
        pieces.append(gap)
        t += len(gap) / SR
        truth.append(Truth(text, round(t + on, 3), round(t + off, 3)))
        pieces.append(x)
        t += len(x) / SR
    pieces.append(np.zeros(int(1.5 * SR), dtype=np.float32))
    audio = np.concatenate(pieces)
    wav = out_dir / f"{lang}_timeline.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return wav, truth


def make_video(wav: Path, out: Path, audio_delay: float = 0.0) -> Path:
    ffmpeg = paths.find_tool("ffmpeg")
    dur = wave.open(str(wav)).getnframes() / SR + audio_delay
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=0x404060:s=640x360:r=25:d={dur:.3f}"]
    if audio_delay:
        cmd += ["-itsoffset", str(audio_delay)]
    cmd += ["-i", str(wav), "-map", "0:v", "-map", "1:a"]
    if out.suffix == ".webm":
        cmd += ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k", "-c:a", "libopus"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"]
    subprocess.run(cmd + [str(out)], check=True)
    return out


def match(cues, truth: list[Truth], lead_in: float) -> list[tuple[Truth, float, float]]:
    """For each phrase: (truth, start error, end error) of the cue(s) covering it.

    start error = (cue start + lead_in) - real onset    (0 = perfect)
    end error   = last covering cue end - real offset   (should be >= 0 and small)
    """
    rows = []
    for tr in truth:
        covering = [c for c in cues if c.end > tr.onset - 0.5 and c.start < tr.offset]
        if not covering:
            rows.append((tr, float("nan"), float("nan")))
            continue
        rows.append((tr, covering[0].start + lead_in - tr.onset, covering[-1].end - tr.offset))
    return rows


def run_case(lang: str, video: Path, out_dir: Path, truth: list[Truth], delay: float = 0.0, align: bool = True):
    from video_transcribe import pipeline
    from video_transcribe.config import load_config
    from video_transcribe.subtitles import read_cues

    cfg = load_config(None, {
        "language": lang,
        "alignment": {"enabled": align},
        "output": {"mode": "none", "formats": ["srt"], "overwrite": True, "dir": str(out_dir)},
    })
    res = pipeline.process(video, cfg, out_dir, run_case.models)
    cues = read_cues(res.subtitle_files[0])
    shifted = [Truth(t.text, t.onset + delay, t.offset + delay) for t in truth]
    return match(cues, shifted, cfg["segmentation"]["lead_in"]), cues


run_case.models = None  # set by caller to a pipeline.Models()


def main() -> None:
    import logging

    from video_transcribe import pipeline

    logging.basicConfig(level=logging.WARNING)
    work = paths.TMP_DIR / "timing-test"
    run_case.models = pipeline.Models()
    for lang in ("en", "zh"):
        if not tts_available(lang):
            print(f"[{lang}] no TTS voice, skipped")
            continue
        wav, truth = build(lang, work)
        cases = [
            (make_video(wav, work / f"{lang}.mp4"), 0.0),
            (make_video(wav, work / f"{lang}.webm"), 0.0),
            (make_video(wav, work / f"{lang}_delayed.webm", 1.0), 1.0),
        ]
        for align in (False, True):
            for video, delay in cases:
                rows, _ = run_case(lang, video, work / "out", truth, delay, align)
                errs = [abs(s) for _, s, _ in rows]
                print(f"[{lang}] {video.name:<18} align={'on ' if align else 'off'} "
                      f"start err: mean {np.nanmean(errs)*1000:5.0f} ms, max {np.nanmax(errs)*1000:5.0f} ms | "
                      f"end err: " + " ".join(f"{e*1000:+.0f}" for *_, e in rows))


if __name__ == "__main__":
    main()
