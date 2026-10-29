"""Telephone-channel simulation for robustness tests.

Pipeline: 16 kHz → 8 kHz → 300–3400 Hz band-pass → optional additive noise at a target SNR →
back to 16 kHz (so every downstream component sees one sample rate). Noise clips come from
the human's recorded noise sessions (data/raw/noise/) or a licence-compatible set recorded in
docs/DECISIONS.md; white noise is the fallback for tests.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from baari.audio.wavio import resample, to_int16
from baari.config import SAMPLE_RATE

TEL_RATE = 8_000
BAND_HZ = (300.0, 3400.0)


def bandpass(x: np.ndarray, sr: int, lo: float = BAND_HZ[0], hi: float = BAND_HZ[1],
             order: int = 4) -> np.ndarray:
    sos = butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return sosfilt(sos, x)


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float,
               rng: np.random.Generator) -> np.ndarray:
    """Add `noise` (looped / randomly cropped to length) so that speech/noise power = snr_db.

    Power is measured over the whole clip including silences, so the SNR is a lower bound on
    the SNR during speech.
    """
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / len(noise))) + 1)
    start = rng.integers(0, len(noise) - len(speech) + 1)
    n = noise[start:start + len(speech)].astype(np.float64)
    p_s = np.mean(speech.astype(np.float64) ** 2)
    p_n = np.mean(n ** 2) + 1e-12
    gain = np.sqrt(p_s / (p_n * 10 ** (snr_db / 10)))
    return speech + gain * n


def simulate_phone(pcm: np.ndarray, *, noise: np.ndarray | None = None, snr_db: float | None = None,
                   seed: int = 0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Telephone-quality version of int16 `pcm` at `sr`, returned as int16 at `sr`."""
    rng = np.random.default_rng(seed)
    x = pcm.astype(np.float64) / 32768.0
    y = bandpass(resample(x, sr, TEL_RATE), TEL_RATE)
    if snr_db is not None:
        if noise is None:
            noise_8k = rng.standard_normal(len(y))
        else:
            noise_8k = resample(noise.astype(np.float64) / 32768.0, sr, TEL_RATE)
        y = mix_at_snr(y, bandpass(noise_8k, TEL_RATE), snr_db, rng)
    out = resample(y, TEL_RATE, sr)[: len(pcm)]
    return to_int16(np.clip(out, -1.0, 1.0))
