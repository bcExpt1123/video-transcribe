# Architecture

## Data flow

```
 input.mp4 / input.webm
        │
        ▼
 ┌──────────────┐  ffprobe: container, size, duration, stream start times
 │ media.probe  │
 └──────┬───────┘
        ▼
 ┌──────────────────────┐  ffmpeg → 16 kHz mono WAV, aligned to the VIDEO timeline
 │ media.extract_audio  │  (aresample=async=1:first_pts=0)
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  faster-whisper + Silero VAD
 │ transcribe           │  → segments with word timestamps
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  zh only: OpenCC Traditional → Simplified (per word)
 │ chinese              │
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  wav2vec2 CTC + Viterbi forced alignment
 │ align                │  → refined word start/end (20 ms resolution)
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  words → cues (grouping, line breaks, timing rules)
 │ segment              │
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  .srt / .ass (+ YAML style) / .vtt
 │ subtitles            │
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐  burn: ffmpeg ass filter + re-encode (x264 / VP9)
 │ render               │  soft: stream copy + mov_text / webvtt track
 └──────────────────────┘
        │
        ▼
 output/input_subtitled.mp4, input.en.srt, input.en.ass
```

## Modules (`src/video_transcribe/`)

| Module | Responsibility |
|---|---|
| `__main__.py` | entry point for `python -m video_transcribe`. Imports `paths` first. |
| `paths.py` | project folder locations. On import it points `HF_HOME`, `TORCH_HOME`, `TMP` and the other cache variables at the project. Also finds ffmpeg/ffprobe. |
| `cli.py` | argparse commands (`run`, `transcribe`, `burn`, `init-config`, `download-models`, `doctor`), logging, exit codes |
| `config.py` | loads `config/default.yaml`, deep-merges the user YAML and CLI overrides, validates keys and values, resolves per-language styles |
| `media.py` | ffprobe parsing (`MediaInfo`), audio extraction, WAV loading |
| `transcribe.py` | faster-whisper model loading, EN/ZH language detection, transcription with word timestamps |
| `chinese.py` | OpenCC conversion, CJK character tests, display width (full-width = 1, half-width = ½) |
| `align.py` | wav2vec2 model wrapper, CTC Viterbi aligner (`ctc_viterbi`), per-segment alignment with fallback |
| `segment.py` | grouping words into cues, balanced line wrapping, cue timing rules |
| `subtitles.py` | SRT/VTT/ASS writers, YAML style → ASS `Style:` line, colour conversion, SRT/VTT parser |
| `render.py` | ffmpeg burn-in and soft-subtitle muxing, with a progress bar |
| `pipeline.py` | runs the steps for one file, reuses models across a batch, manages the work folder and overwrite checks |
| `data.py` | dataclasses: `Word`, `Segment`, `Transcript`, `Cue` |

## Intermediate files

With `--keep-work`, `output/<name>_work/` contains:

| File | Content |
|---|---|
| `audio.wav` | 16 kHz mono PCM. Sample *n* is at time *n*/16000 on the video timeline. |
| `transcript.json` | the transcript after alignment (format below) |
| `subs.ass` | the exact file given to the burn-in filter |
| `subs.srt` / `subs.vtt` | the file used for soft muxing |

`transcript.json`:

```json
{
 "language": "en",
 "duration": 26.52,
 "model": "small",
 "aligned": true,
 "segments": [
  {
   "text": "The quick brown fox jumps over the lazy dog.",
   "start": 1.42, "end": 3.84,
   "words": [
    {"text": " The",   "start": 1.42, "end": 1.54, "score": 0.91, "aligned": true},
    {"text": " quick", "start": 1.58, "end": 1.86, "score": 0.88, "aligned": true}
   ]
  }
 ]
}
```

- `score` is the alignment confidence (0–1) when `aligned` is true, otherwise Whisper's word probability.
- `aligned: false` on a word means it kept Whisper's time: either the whole segment fell back, or the word has no characters the alignment model knows (digits, symbols), in which case its time was interpolated.

When `keep_work_files` is false, the work folder is created under `.runtime/tmp/` and deleted after each video.

## Forced alignment in detail

`align.ctc_viterbi(log_probs, tokens, blank)` is a standard CTC forced aligner:

1. It builds the blank-interleaved state sequence `∅ t1 ∅ t2 ∅ … tJ ∅` (2J+1 states).
2. Dynamic programming over T frames. Each state may *stay*, *advance by one*, or *skip a blank* (only between two different tokens, so a doubled letter like the "LL" in "HELLO" needs a blank between its two Ls, as the CTC rules require).
3. The best path ends in the last token or the final blank. Backtracking assigns each frame to a state.
4. Each token's span is its first..last frame. A word's time is the span of all its tokens.

Frames are 20 ms (320 samples). Every chunk of audio fed to the model is padded by 80 samples, so N×320 samples give exactly N frames. That keeps frame indices exact even across 20-second chunk boundaries.

The window for each segment is the Whisper segment ±0.4 s, but never reaches into the previous or next segment. This stops the aligner from matching words to a neighbouring sentence.

## Timeline / offset handling

ffmpeg treats the container's `start_time` as zero for every output: the burn-in filter's frame timestamps, and the timestamps in a soft-subtitled output. Audio streams don't always start there: WEBM Opus has pre-skip, some recordings start audio late, MP4 has edit lists. The extraction filter `aresample=async=1:first_pts=0` inserts silence (or trims) so the WAV begins exactly at timeline zero, and fills timestamp gaps in the middle. All later times are therefore already on the video timeline, so no manual offset is needed. The test suite checks this with a WEBM whose audio starts 1 s late.

## Extending

- **Another language:** add the code to `config.LANGUAGES`, an alignment model under `alignment.models`, a `max_chars` entry and a style override, and widen the language detection in `transcribe.detect_language`.
- **Another container (e.g. MKV):** add the extension to `media.SUPPORTED_EXTENSIONS`, add an `encoding` section, and choose the soft-subtitle codec in `render.soft` (MKV can carry styled ASS directly).
