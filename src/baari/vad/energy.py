"""Simple causal energy VAD with hysteresis.

Used by the M0 spike to find local pause onsets before Silero VAD exists (M1). It also stays
useful as a dependency-free fallback and for tests on synthetic tones. Decisions at frame k use
only frames <= k, so it can run live.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from baari.config import FRAME_MS, FRAME_SAMPLES


@dataclass
class Segment:
    """A speech segment in audio time (ms from the start of the clip)."""

    start_ms: float
    end_ms: float  # speech offset = pause onset


def frame_db(pcm: np.ndarray) -> np.ndarray:
    """Per-frame RMS level in dBFS (512-sample frames)."""
    x = pcm.astype(np.float32) / 32768.0
    n = len(x) // FRAME_SAMPLES
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(x[: n * FRAME_SAMPLES].reshape(n, FRAME_SAMPLES) ** 2, axis=1))
    return 20.0 * np.log10(rms + 1e-9)


def energy_segments(pcm: np.ndarray, *, threshold_db: float = -40.0,
                    pause_min_ms: float = 150.0, min_speech_ms: float = 64.0) -> list[Segment]:
    """Speech segments separated by silences of at least `pause_min_ms`.

    A frame is speech if its level exceeds `threshold_db`. Speech must last `min_speech_ms`
    to open a segment; a segment closes once silence has lasted `pause_min_ms`, and its end is
    back-dated to the first silent frame (the true pause onset).
    """
    db = frame_db(pcm)
    speech = db > threshold_db
    need_on = max(1, int(np.ceil(min_speech_ms / FRAME_MS)))
    need_off = max(1, int(np.ceil(pause_min_ms / FRAME_MS)))
    segs: list[Segment] = []
    in_speech = False
    run_on = run_off = 0
    start = 0
    for k, s in enumerate(speech):
        if not in_speech:
            run_on = run_on + 1 if s else 0
            if run_on >= need_on:
                in_speech, start, run_off = True, k - need_on + 1, 0
        else:
            run_off = 0 if s else run_off + 1
            if run_off >= need_off:
                end = k - need_off + 1
                segs.append(Segment(start * FRAME_MS, end * FRAME_MS))
                in_speech, run_on = False, 0
    if in_speech:
        end = len(speech) - run_off
        segs.append(Segment(start * FRAME_MS, end * FRAME_MS))
    return segs
