"""PauseTracker hysteresis (pure logic) and Silero VAD smoke tests on synthetic audio."""

import numpy as np

from baari.vad.silero import PauseTracker, SileroVAD, run_vad
from conftest import gap, tone


def _run(probs, **kw):
    tr = PauseTracker(**kw)
    out = []
    for p in probs:
        out += tr.update(p)
    return out


def test_tracker_segments_and_backdated_onsets():
    # 10 silent, 20 speech, 10 silent, 15 speech, 10 silent frames (32 ms each)
    probs = [0.0] * 10 + [0.9] * 20 + [0.0] * 10 + [0.9] * 15 + [0.0] * 10
    ev = _run(probs, pause_min_ms=150)
    kinds = [e.kind for e in ev]
    assert kinds == ["speech_start", "silence_start", "pause_start",
                     "speech_start", "silence_start", "pause_start"]
    starts = [e for e in ev if e.kind == "speech_start"]
    pauses = [e for e in ev if e.kind == "pause_start"]
    assert [s.onset_ms for s in starts] == [10 * 32, 40 * 32]
    assert [p.onset_ms for p in pauses] == [30 * 32, 55 * 32]
    sil = [e for e in ev if e.kind == "silence_start"]
    assert all(e.detected_ms - e.onset_ms <= 100 for e in sil)  # SPEC §9: onset known <= 100 ms
    assert all(e.detected_ms - e.onset_ms <= 192 for e in pauses)


def test_short_dip_is_cancelled_not_a_pause():
    probs = [0.9] * 10 + [0.0] * 3 + [0.9] * 10 + [0.0] * 10
    ev = _run(probs, pause_min_ms=150)
    assert [e.kind for e in ev] == ["speech_start", "silence_start", "silence_cancel",
                                    "silence_start", "pause_start"]


def test_hysteresis_band_keeps_state():
    # probabilities between off (0.35) and on (0.5) neither open nor close speech
    probs = [0.9] * 5 + [0.4] * 20 + [0.0] * 6
    ev = _run(probs, pause_min_ms=150)
    pauses = [e for e in ev if e.kind == "pause_start"]
    assert len(pauses) == 1 and pauses[0].onset_ms == 25 * 32
    assert _run([0.45] * 50) == []


def test_single_spike_does_not_open_speech():
    assert _run([0.0, 0.9, 0.0, 0.0] * 5, min_speech_ms=64) == []


def test_silero_low_on_silence_and_tones():
    x = np.concatenate([gap(500), tone(500), gap(500)])
    probs, events = run_vad(x, SileroVAD())
    assert probs.min() >= 0 and probs.max() <= 1
    assert probs[:10].max() < 0.2  # digital silence is not speech
    assert events == []  # a pure tone is not speech either
