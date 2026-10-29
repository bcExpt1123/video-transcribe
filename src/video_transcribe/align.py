"""Forced alignment with wav2vec2 CTC models.

Whisper's word timestamps come from attention weights and are usually within a few
hundred milliseconds. Forced alignment matches the known transcript against the
audio frame-by-frame (20 ms resolution) with a CTC Viterbi search and gives much
tighter word start/end times.

Per Whisper segment:
  1. cut the audio window around the segment (bounded by neighbouring segments)
  2. compute CTC log-probabilities with wav2vec2
  3. map the words to model tokens (EN letters / ZH characters)
  4. find the single best CTC path (blank-interleaved Viterbi)
  5. word time = first..last frame of its tokens; tokens the model does not know
     (digits, symbols) are interpolated from neighbours
If anything fails or confidence is low, the segment keeps Whisper's own times.
"""

from __future__ import annotations

import logging

import numpy as np

from . import paths  # noqa: F401  (ensures local cache env vars are set)
from .data import Segment, Transcript, Word
from .media import SAMPLE_RATE

log = logging.getLogger(__name__)

FRAME_STRIDE = 320                       # samples per wav2vec2 frame (20 ms at 16 kHz)
FRAME_SEC = FRAME_STRIDE / SAMPLE_RATE
RECEPTIVE_EXTRA = 400 - FRAME_STRIDE     # extra samples so that N samples -> N/320 frames
CHUNK_SEC = 20.0                         # emission chunk length for long windows
WINDOW_PAD = 0.4                         # seconds of context around each segment


class AlignmentFailed(Exception):
    pass


# --------------------------------------------------------------------- CTC core


def ctc_viterbi(log_probs: np.ndarray, tokens: list[int], blank: int) -> list[tuple[int, int, float]]:
    """Best CTC alignment of ``tokens`` to ``log_probs`` (T x C, log-softmax).

    Returns, for every token, ``(first_frame, last_frame_exclusive, mean_prob)``.
    Uses the standard blank-interleaved state sequence so repeated characters
    (e.g. the 'LL' in HELLO) are handled correctly.
    """
    T = log_probs.shape[0]
    J = len(tokens)
    if J == 0:
        raise AlignmentFailed("no tokens")
    ext = np.full(2 * J + 1, blank, dtype=np.int64)
    ext[1::2] = tokens
    S = len(ext)
    # Minimum frames: every token once, plus a blank between equal neighbours.
    repeats = sum(1 for a, b in zip(tokens, tokens[1:]) if a == b)
    if T < J + repeats:
        raise AlignmentFailed(f"audio too short ({T} frames for {J} tokens)")

    emit = log_probs[:, ext]                       # T x S
    can_skip = np.zeros(S, dtype=bool)
    can_skip[3::2] = ext[3::2] != ext[1:-2:2]      # token -> next different token
    neg = -np.inf

    dp = np.full(S, neg)
    dp[0] = emit[0, 0]
    dp[1] = emit[0, 1]
    back = np.zeros((T, S), dtype=np.int8)         # 0 stay, 1 from s-1, 2 from s-2
    for t in range(1, T):
        stay = dp
        step = np.concatenate(([neg], dp[:-1]))
        skip = np.concatenate(([neg, neg], dp[:-2]))
        skip = np.where(can_skip, skip, neg)
        cand = np.stack((stay, step, skip))
        choice = np.argmax(cand, axis=0)
        dp = cand[choice, np.arange(S)] + emit[t]
        back[t] = choice

    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    if not np.isfinite(dp[s]):
        raise AlignmentFailed("no valid path")
    states = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        states[t] = s
        s -= int(back[t, s])

    spans: list[tuple[int, int, float]] = []
    probs = np.exp(emit[np.arange(T), states])
    for j in range(J):
        frames = np.nonzero(states == 2 * j + 1)[0]
        if len(frames) == 0:  # cannot happen for a valid path, but be safe
            raise AlignmentFailed("token without frames")
        spans.append((int(frames[0]), int(frames[-1]) + 1, float(probs[frames].mean())))
    return spans


# --------------------------------------------------------------------- model


class Aligner:
    def __init__(self, model_name: str, language: str, chunk_mb: int = 100):
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        from transformers.utils import logging as hf_logging

        from . import downloader

        model_path = downloader.resolve_wav2vec2(model_name, chunk_mb)
        # Silences "weights not initialized: masked_spec_embed" (training-only, harmless).
        hf_logging.set_verbosity_error()
        import warnings

        warnings.filterwarnings("ignore", message=".*gradient_checkpointing.*")
        self.torch = torch
        self.language = language
        log.info("loading alignment model '%s'", model_name)
        self.processor = Wav2Vec2Processor.from_pretrained(model_path)
        self.model = Wav2Vec2ForCTC.from_pretrained(model_path).eval()
        vocab = self.processor.tokenizer.get_vocab()
        self.vocab = {k: v for k, v in vocab.items()}
        pad = self.processor.tokenizer.pad_token
        self.blank = self.vocab.get(pad, 0) if pad is not None else 0
        self.word_sep = self.vocab.get("|")
        letters = [k for k in self.vocab if len(k) == 1 and k.isalpha() and k.isascii()]
        self.upper = bool(letters) and all(k.isupper() for k in letters)

    # -- text -> tokens ------------------------------------------------------

    def word_tokens(self, text: str) -> list[int]:
        text = text.strip()
        if self.language == "en":
            text = text.upper() if self.upper else text.lower()
            text = text.replace("’", "'")
        out = []
        for ch in text:
            tid = self.vocab.get(ch)
            if tid is None and self.language == "zh" and ch.isascii() and ch.isalpha():
                tid = self.vocab.get(ch.upper() if self.upper else ch.lower())
            if tid is not None and tid != self.blank and ch != "|":
                out.append(tid)
        return out

    # -- audio -> log-probs ----------------------------------------------------

    def emissions(self, audio: np.ndarray) -> np.ndarray:
        torch = self.torch
        chunk = int(CHUNK_SEC * SAMPLE_RATE)
        outs = []
        for a in range(0, len(audio), chunk):
            n = min(chunk, len(audio) - a)
            n_frames = max(1, n // FRAME_STRIDE)
            piece = audio[a : a + n_frames * FRAME_STRIDE + RECEPTIVE_EXTRA]
            if len(piece) < n_frames * FRAME_STRIDE + RECEPTIVE_EXTRA:
                piece = np.pad(piece, (0, n_frames * FRAME_STRIDE + RECEPTIVE_EXTRA - len(piece)))
            inputs = self.processor(piece, sampling_rate=SAMPLE_RATE, return_tensors="pt")
            with torch.inference_mode():
                logits = self.model(inputs.input_values).logits[0]
            lp = torch.log_softmax(logits.float(), dim=-1).numpy()
            outs.append(lp[:n_frames])
        return np.concatenate(outs, axis=0)

    # -- one segment -----------------------------------------------------------

    def align_segment(
        self, audio: np.ndarray, seg: Segment, lo: float, hi: float, min_score: float
    ) -> bool:
        """Refine ``seg.words`` in place. Returns True if alignment was applied."""
        w_start = max(lo, seg.start - WINDOW_PAD)
        w_end = min(hi, seg.end + WINDOW_PAD)
        a, b = int(w_start * SAMPLE_RATE), int(w_end * SAMPLE_RATE)
        if b - a < FRAME_STRIDE * 2:
            raise AlignmentFailed("window too short")
        w_start = a / SAMPLE_RATE

        per_word = [self.word_tokens(w.text) for w in seg.words]
        tokens: list[int] = []
        owner: list[int] = []  # word index of each token (-1 = separator)
        for i, toks in enumerate(per_word):
            if not toks:
                continue
            if tokens and self.word_sep is not None and self.language == "en":
                tokens.append(self.word_sep)
                owner.append(-1)
            tokens.extend(toks)
            owner.extend([i] * len(toks))
        if not tokens:
            raise AlignmentFailed("no alignable characters")

        lp = self.emissions(audio[a:b])
        spans = ctc_viterbi(lp, tokens, self.blank)

        real = [sp for sp, o in zip(spans, owner) if o >= 0]
        score = float(np.mean([p for _, _, p in real]))
        if score < min_score:
            raise AlignmentFailed(f"low confidence {score:.2f}")

        times: dict[int, list[float]] = {}
        for (f0, f1, p), o in zip(spans, owner):
            if o < 0:
                continue
            t = times.setdefault(o, [f0, f1, 0.0, 0])
            t[0] = min(t[0], f0)
            t[1] = max(t[1], f1)
            t[2] += p
            t[3] += 1

        for i, w in enumerate(seg.words):
            if i in times:
                f0, f1, psum, n = times[i]
                w.start = round(w_start + f0 * FRAME_SEC, 3)
                w.end = round(w_start + f1 * FRAME_SEC, 3)
                w.score = round(psum / n, 3)
                w.aligned = True
        _interpolate(seg.words, w_start, w_start + len(lp) * FRAME_SEC)
        seg.start, seg.end = seg.words[0].start, seg.words[-1].end
        return True


def _interpolate(words: list[Word], lo: float, hi: float) -> None:
    """Give words without alignable characters a time between their neighbours."""
    n = len(words)
    i = 0
    while i < n:
        if words[i].aligned:
            i += 1
            continue
        j = i
        while j < n and not words[j].aligned:
            j += 1
        # Inside the segment: squeeze between aligned neighbours. At the edges keep
        # Whisper's own times, clipped to the window.
        right = words[j].start if j < n else None
        left = words[i - 1].end if i > 0 else max(lo, min(words[i].start, right if right is not None else hi))
        if right is None:
            right = min(hi, max(words[j - 1].end, left))
        right = max(right, left)
        k = j - i
        step = (right - left) / k
        for m in range(k):
            words[i + m].start = round(left + m * step, 3)
            words[i + m].end = round(left + (m + 1) * step, 3)
        i = j


def _monotonic(words: list[Word]) -> None:
    """Enforce start <= end and non-decreasing word order."""
    prev_end = 0.0
    for w in words:
        if w.start < prev_end:
            w.start = prev_end
        if w.end < w.start:
            w.end = w.start
        prev_end = w.end


def align_transcript(
    tr: Transcript, audio: np.ndarray, model_name: str, min_score: float, aligner: Aligner | None = None,
    chunk_mb: int = 100,
) -> Aligner:
    aligner = aligner or Aligner(model_name, tr.language, chunk_mb)
    duration = len(audio) / SAMPLE_RATE
    ok = failed = 0
    segs = tr.segments
    for idx, seg in enumerate(segs):
        # Never let the window reach into the neighbouring segments' speech.
        lo = segs[idx - 1].end if idx > 0 else 0.0
        hi = segs[idx + 1].start if idx + 1 < len(segs) else duration
        lo = min(lo, seg.start)
        hi = max(hi, seg.end)
        backup = [(w.start, w.end, w.score) for w in seg.words]
        try:
            aligner.align_segment(audio, seg, lo, hi, min_score)
            ok += 1
        except AlignmentFailed as e:
            for w, (s, e_, p) in zip(seg.words, backup):
                w.start, w.end, w.score, w.aligned = s, e_, p, False
            failed += 1
            log.debug("segment %.2f-%.2f kept whisper times: %s", seg.start, seg.end, e)
    all_words = [w for s in segs for w in s.words]
    _monotonic(all_words)
    for s in segs:
        if s.words:
            s.start, s.end = s.words[0].start, s.words[-1].end
    tr.aligned = True
    log.info("alignment: %d segments refined, %d kept Whisper timing", ok, failed)
    return aligner


