"""Player logic driven through its audio callback (no sound device needed)."""

import numpy as np

from baari.audio.playback import RAMP_SAMPLES, Player, Utterance


class _Status:
    output_underflow = False


def _pull(player, n=256):
    out = np.zeros((n, 1), dtype=np.float32)
    player._callback(out, n, None, _Status())
    return out[:, 0]


def _utt():
    a = np.full(1600, 16384, np.int16)  # 0.1 s at half scale
    b = np.full(1600, 8192, np.int16)
    return Utterance.from_chunks([("pehla vaakya.", a), ("doosra vaakya.", b)], gap_ms=50)


def test_utterance_chunk_offsets():
    u = _utt()
    assert u.starts == [0, 1600 + 800]
    assert len(u.pcm) == 1600 + 800 + 1600
    assert u.chunk_at(0) == 0 and u.chunk_at(2399) == 0 and u.chunk_at(2400) == 1


def test_play_heard_text_and_end():
    p = Player(open_stream=False)
    p.play(_utt())
    assert p.playing and p.heard_text() == "pehla vaakya."
    first = _pull(p)
    assert np.allclose(first, 0.5, atol=1e-3) and p.log.start_ns is not None
    while p.playing:
        _pull(p)
    assert p.heard_text() == "pehla vaakya. doosra vaakya."
    assert p.log.end_ns is not None and p.log.stopped_ns is None
    assert np.all(_pull(p) == 0)


def test_duck_ramps_then_restores():
    p = Player(open_stream=False)
    p.play(_utt())
    _pull(p)
    p.duck(0.25)
    out = _pull(p)
    assert out[0] > 0.45 and np.isclose(out[RAMP_SAMPLES + 5], 0.125, atol=1e-3)  # 0.5 * 0.25
    p.restore()
    out = _pull(p)
    assert np.isclose(out[-1], 0.5, atol=1e-3)
    assert len(p.log.duck_ns) == 1 and len(p.log.restore_ns) == 1


def test_stop_silences_and_logs():
    p = Player(open_stream=False)
    p.play(_utt())
    _pull(p)
    p.stop()
    assert not p.playing and p.log.stopped_ns is not None
    assert np.all(_pull(p) == 0)
    assert p.heard_text() == "pehla vaakya."
