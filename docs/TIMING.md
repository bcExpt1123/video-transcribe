# Subtitle timing

Correct timing is the main goal of this tool. Five mechanisms work together. They are listed here in pipeline order.

## 1. Audio on the same timeline as the video

Audio is extracted with `aresample=async=1:first_pts=0`. If the audio stream starts later than the container (WEBM Opus pre-skip, recordings where audio begins late, MP4 edit lists), silence is inserted at the start, and timestamp gaps in the middle are filled. Sample *n* of the extracted WAV is therefore exactly at *n* / 16000 s on the timeline that the burn-in filter and soft-subtitle muxing use. **No constant offset can creep in.** This is tested with a WEBM whose audio starts 1.014 s late.

## 2. Voice activity detection

Silero VAD (built into faster-whisper) removes silence and music before recognition. Whisper then cannot invent text in silent parts, and its 30-second windows don't drift. `condition_on_previous_text` is off for the same reason.

## 3. Word timestamps from Whisper

Whisper provides a first estimate of every word's timing. These estimates are typically 50–200 ms off: usually early starts, and ends that are too short in English or too long in Chinese.

## 4. Forced alignment (wav2vec2 CTC)

For each Whisper segment, the recognised text is matched against the audio, frame by frame (every 20 ms), with a CTC Viterbi search ([ARCHITECTURE.md](ARCHITECTURE.md#forced-alignment-in-detail)). This replaces Whisper's estimates with times based on the actual sound.

- English uses `facebook/wav2vec2-base-960h` (letters). Chinese uses `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn` (characters).
- The window for each segment never reaches into neighbouring segments.
- Words the model can't spell (digits, symbols) are interpolated between their aligned neighbours.
- If a segment can't be aligned confidently (`alignment.min_score`), it keeps Whisper's times. Run with `-v` to see which segments.

## 5. Cue timing rules

These rules come from `segmentation` in the config:

| Rule | Default |
|---|---|
| show the cue before the first word | `lead_in` 0.05 s |
| keep the cue after the last word | `end_padding` EN 0.15 s, ZH 0.3 s |
| short cues are lengthened, **only into silence** | `min_duration` 0.8 s |
| gap between cues, so they never overlap | `min_gap` 0.08 s |
| a pause always starts a new cue | `pause_split` 0.6 s |
| no cue is shown longer than | `max_duration` 6 s |

Chinese gets more `end_padding` because the aligner marks where the last syllable *starts*, and a Mandarin syllable keeps sounding for another 0.1–0.3 s.

Times are rounded, not truncated, to each format's resolution: 1 ms for SRT/VTT, 10 ms for ASS. Overlaps are re-checked after rounding.

## Measured accuracy

`tests/timing_harness.py` synthesises speech with Windows TTS, places the phrases at known positions, and measures the real onset and offset of each phrase from the waveform. It then runs the full pipeline (Whisper `small`, CPU) and compares the results.

- **Start error** = when the first word was placed, minus the true speech onset.
- **End error** = when the cue disappears, minus the true end of speech. Positive means the cue stays until after the speech has ended, which is the goal.

| Clip | Alignment | Start error mean / max | End error (per phrase, ms) |
|---|---|---|---|
| EN MP4 | off | 76 / 170 ms | +30 −60 −5 −115 −50 |
| EN MP4 | **on** | **22 / 80 ms** | +50 +90 +35 +125 +150 |
| EN WEBM | **on** | **24 / 80 ms** | +50 +30 +45 +65 +150 |
| EN WEBM, audio starts 1 s late | **on** | **24 / 90 ms** | +60 +20 +35 +55 +140 |
| ZH MP4 | off | 86 / 170 ms | +290 +300 +225 +190 |
| ZH MP4 | **on** | **24 / 60 ms** | +90 +140 +25 +50 |
| ZH WEBM | **on** | **21 / 60 ms** | +90 +130 +25 +50 |
| ZH WEBM, audio starts 1 s late | **on** | **26 / 60 ms** | +100 +140 +25 +50 |

What the table shows:

- Alignment cuts the start error by about 3–4×, to roughly one video frame.
- With alignment, no cue disappears before its speech ends. Without it, English cues were cut off up to 115 ms early.
- MP4, WEBM and late-starting audio give the same results, so container offsets are handled.
- Burn-in was checked frame by frame: a cue at 2.000–3.000 s is invisible at 1.96 s, visible at 2.04 s and 2.96 s, and gone at 3.04 s, in both MP4 and WEBM.

The largest remaining start errors (80–90 ms) are on words that start with a soft fricative ("**S**ubtitles"). The waveform shows energy from the hiss before the model recognises the letter. `lead_in` partly covers this.

To check timing on your own machine:

```powershell
.\vt.cmd doctor
.venv\Scripts\python.exe -m pytest -m slow        # asserts |start error| <= 150 ms, no early ends
.venv\Scripts\python.exe tests\timing_harness.py  # prints the table above
```

## Tuning

| Symptom | Change |
|---|---|
| subtitles feel slightly late | raise `lead_in` (e.g. `0.15`) |
| subtitles vanish too fast | raise `end_padding` / `min_duration` |
| one long cue covers two sentences | lower `pause_split` (e.g. `0.4`) or `max_duration` |
| whole video consistently shifted (source has lip-sync error) | `--offset ±seconds` |
| a few cues badly placed | larger model (`-m medium`) so the text is right, or lower `alignment.min_score` |
