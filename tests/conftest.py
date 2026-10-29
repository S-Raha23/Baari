"""Shared fixtures: synthetic audio only (sine tones + silence), never personal recordings."""

import numpy as np
import pytest

SR = 16_000


def tone(ms: float, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * ms / 1000)) / SR
    return (amp * 32767 * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def gap(ms: float) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000), dtype=np.int16)


@pytest.fixture
def speech_like() -> np.ndarray:
    """'haan… matlab… theek hai' shaped clip: 3 tone bursts with 600 ms and 800 ms pauses."""
    return np.concatenate([gap(300), tone(400), gap(600), tone(500, 180), gap(800), tone(700, 200), gap(1000)])
