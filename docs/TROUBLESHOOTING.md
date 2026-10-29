# Troubleshooting

Start with:

```powershell
.\vt.cmd doctor
.\vt.cmd run video.mp4 -v --keep-work      # -v shows every ffmpeg command and per-segment alignment info
```

## Installation

**`setup.ps1 cannot be loaded because running scripts is disabled`**
Start it with `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. This doesn't change the system policy.

**Download errors during setup**
Run setup again. Finished steps are skipped and partial downloads restart. Behind a proxy, set `$env:HTTPS_PROXY = "http://proxy:port"` first.

**`.venv not found. Run setup.ps1 first.`**
The launcher can't find `.venv\Scripts\python.exe`. Run setup, and run the launcher from the project folder (or by its full path).

**`ffmpeg not found`**
`.runtime\ffmpeg\bin\ffmpeg.exe` is missing. Run setup again, or set `ffmpeg_path` in your config to a folder that contains `ffmpeg` and `ffprobe`.

## Subtitles look wrong

**Chinese characters show up as boxes (□□□)**
The font has no Chinese glyphs. Keep `font_name: Noto Sans SC`, or copy a CJK font into `fonts/` and use its family name. Run `doctor` to check that the fonts are present.

**My font is ignored**
`font_name` must be the font's *family name* (the name shown when you open the font file), not the file name. The font must be in `fonts/` or installed in Windows.

**Text is too big or too small**
Sizes are for 1080p and scale automatically. Change `style.font_size`. For Chinese only, change `style.overrides.zh.font_size`.

**Lines are too long or wrap strangely**
Lower `segmentation.max_chars.en` / `.zh`. Very long single words can't be split and are shown on their own line.

**Style changes don't appear**
Style only applies to `burn` mode and to the `.ass` file. Soft subtitles (`--mode soft`) are drawn by the video player with its own style. Re-burn an existing `.srt` with `vt burn video.mp4 -s output\video.en.srt -c my.yaml --overwrite`.

## Timing

See [TIMING.md](TIMING.md) for how timing works and how it was measured.

**All subtitles are early or late by the same amount**
This shouldn't happen with MP4/WEBM, because container offsets are corrected automatically. If the *source* audio itself is out of sync with the picture (lip-sync error in the original), shift with `--offset 0.3` (later) or `--offset -0.3` (earlier).

**One subtitle is badly placed**
Run with `-v` and look for `segment … kept whisper times: …` messages. That segment couldn't be force-aligned (heavy music or noise, or misrecognised text). Fixes:
- use a larger model (`-m medium`) so the text is right; alignment then usually succeeds
- lower `alignment.min_score` (e.g. `0.1`) to accept less confident alignments
- correct the text in the `.srt` and re-burn

**Subtitles disappear too quickly**
Increase `segmentation.end_padding` (e.g. `0.3`) and/or `min_duration` (e.g. `1.2`). Cues are only extended into silence, so they never cover the next line.

**Subtitles appear a little before the speech**
That's `segmentation.lead_in` (0.05 s by default, which most viewers find natural). Set it to `0` for no lead-in.

**Subtitles during music or silence ("Thank you for watching", etc.)**
That is a Whisper hallucination. Keep `transcription.vad: true`. If it still happens, raise `vad_min_silence_ms` or use a larger model.

## Recognition quality

**Wrong language detected**
Use `--lang en` or `--lang zh`. Detection only chooses between these two.

**Names or technical terms are misspelled**
Put them in `transcription.initial_prompt`, e.g. `initial_prompt: "MacCMS, Nginx, PHP"`.

**Chinese comes out as Traditional**
`chinese.script` must be `simplified` (the default). If you want Traditional, set it to `traditional`.

**Chinese has no punctuation**
Whisper sometimes leaves punctuation out of Chinese. Cues are still split at pauses (`pause_split`) and by length. A larger model (`medium`, `large-v3`) produces punctuation more consistently.

## Performance

**Too slow**
- Use a smaller model (`-m base`) or `--no-align` (alignment adds ~10–30 %).
- Burn-in re-encodes the whole video. Use `encoding.mp4.preset: veryfast` or `--mode soft` (no re-encode).
- For WEBM, raise `encoding.webm.cpu_used` (up to 8).
- Close other heavy programs. All CPU cores are used by default (`transcription.cpu_threads: 0`).

**Out of memory**
Use a smaller Whisper model. The Chinese alignment model needs about 2 GB of RAM while it runs.

## Offline

**`We couldn't connect to huggingface.co`**
The model isn't downloaded yet. Run `vt download-models -m <model>` once while online. After that, `$env:HF_HUB_OFFLINE = "1"` makes the tool skip network checks completely.
