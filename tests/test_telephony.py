"""Telephone simulation: band limiting and SNR."""

import numpy as np

from baari.audio.telephony import mix_at_snr, simulate_phone
from conftest import SR, tone


def _band_power(x, lo, hi):
    spec = np.abs(np.fft.rfft(x.astype(np.float64))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return spec[(f >= lo) & (f < hi)].sum()


def test_out_of_band_tones_removed():
    x = (tone(1000, 100) // 2 + tone(1000, 1000) // 2 + tone(1000, 6000) // 2)
    y = simulate_phone(x)
    assert y.dtype == np.int16 and len(y) == len(x)
    keep = _band_power(y, 900, 1100) / _band_power(x, 900, 1100)
    low = _band_power(y, 50, 150) / _band_power(x, 50, 150)
    high = _band_power(y, 5500, 6500) / _band_power(x, 5500, 6500)
    assert keep > 0.5 and low < 0.05 and high < 0.001


def test_mix_hits_target_snr():
    rng = np.random.default_rng(0)
    s = np.sin(np.linspace(0, 2000, 16000))
    n = rng.standard_normal(5000)  # shorter than speech: gets looped
    y = mix_at_snr(s, n, 10.0, rng)
    noise = y - s
    snr = 10 * np.log10(np.mean(s ** 2) / np.mean(noise ** 2))
    assert abs(snr - 10.0) < 0.01


def test_noisy_phone_is_deterministic_per_seed():
    x = tone(500)
    assert np.array_equal(simulate_phone(x, snr_db=5, seed=1), simulate_phone(x, snr_db=5, seed=1))
    assert not np.array_equal(simulate_phone(x, snr_db=5, seed=1), simulate_phone(x, snr_db=5, seed=2))
