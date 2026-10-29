"""Energy VAD on synthetic tone bursts."""

from baari.vad.energy import energy_segments
from conftest import gap, tone
import numpy as np


def test_three_segments_with_correct_pause_onsets(speech_like):
    segs = energy_segments(speech_like, pause_min_ms=150)
    assert len(segs) == 3
    # true offsets: 700, 1800, 3300 ms; frame resolution is 32 ms
    for seg, true_end in zip(segs, [700, 1800, 3300]):
        assert abs(seg.end_ms - true_end) <= 32


def test_short_gap_does_not_split():
    x = np.concatenate([gap(200), tone(300), gap(100), tone(300), gap(500)])
    assert len(energy_segments(x, pause_min_ms=150)) == 1


def test_click_shorter_than_min_speech_ignored():
    x = np.concatenate([gap(300), tone(20), gap(500)])
    assert energy_segments(x, min_speech_ms=64) == []
