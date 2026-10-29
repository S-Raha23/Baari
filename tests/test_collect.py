"""Card decks, fake values, clock fitting and check-session on a synthetic session."""

import json
import random

import numpy as np

from baari.audio.wavio import save_wav
from baari.collect.cards import all_bot_texts, bargein_deck, fake_values, load_cards, turn_deck
from baari.collect.check import check_session
from baari.collect.recorder import fit_clock, t_to_sample
from conftest import gap, tone


def test_fake_values_never_real_mobiles():
    rng = random.Random(0)
    for _ in range(200):
        v = fake_values(rng)
        digits = v["mobile"].replace(" ", "")
        assert len(digits) == 10 and digits[0] == "5"  # Indian mobiles start with 6-9
        assert len(v["last4"]) == 4 and len(v["code6"]) == 6


def test_turn_deck_covers_all_types_and_is_seeded():
    cards = load_cards()
    deck = turn_deck(20, seed=1, cards=cards)
    assert len(deck) == 20
    assert {c.card_type for c in deck} == set(cards["turns"])
    assert all("{" not in c.card for c in deck)  # placeholders filled
    assert [c.card for c in deck] == [c.card for c in turn_deck(20, seed=1, cards=cards)]
    nums = [c for c in deck if c.slot == "number"]
    assert all(c.expected_digits in (4, 6, 10) for c in nums)


def test_bargein_deck_balanced():
    deck = bargein_deck(20, seed=3)
    counts = {}
    for c in deck:
        counts[c.action] = counts.get(c.action, 0) + 1
    assert set(counts.values()) == {4} and len(counts) == 5
    assert all(len(c.sentences) >= 4 for c in deck)


def test_all_bot_texts_unique_and_include_consent():
    texts = all_bot_texts()
    assert len(texts) == len(set(texts)) and texts[0].startswith("Yeh recording")


def test_fit_clock_recovers_rate_despite_jitter():
    rng = np.random.default_rng(0)
    k = np.arange(1000)
    t = 5_000_000_000 + (k + 1) * 32_000_000 + rng.integers(-4_000_000, 8_000_000, size=1000)
    a, b = fit_clock(np.stack([k, t], axis=1))
    assert abs(a * 1e9 - 16000) < 5
    assert abs(t_to_sample(5_000_000_000 + 32_000_000 * 500, (a, b)) - 500 * 512) < 64


def _fake_session(d, answer_bursts):
    """Synthetic turns session: bot prompt then a tone 'answer' and Done, per trial."""
    sr, t0 = 16000, 10_000_000_000
    parts, events, pos = [], [], 0
    ms_to_ns = lambda ms: t0 + int(ms * 1e6)  # noqa: E731  (1 sample = 62.5 us)
    for trial, burst in enumerate(answer_bursts, 1):
        parts.append(gap(1000))  # bot speaking (headphones: silence at the mic)
        bot_end = pos + 1000
        events.append({"t_ns": ms_to_ns(bot_end), "type": "bot_done", "trial": trial,
                       "playback_start_ns": ms_to_ns(pos), "playback_end_ns": ms_to_ns(bot_end), "slot": "free_text"})
        parts.append(gap(300))
        parts.append(burst)
        parts.append(gap(800))
        pos = bot_end + 300 + len(burst) / sr * 1000 + 800
        events.append({"t_ns": ms_to_ns(pos), "type": "done", "trial": trial})
    pcm = np.concatenate(parts)
    save_wav(d / "mic.wav", pcm)
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    blocks = np.stack([np.arange(len(pcm) // 512), t0 + (np.arange(len(pcm) // 512) + 1) * 32_000_000], axis=1)
    a, b = fit_clock(blocks)
    (d / "session.json").write_text(json.dumps({
        "session_id": "turns-test", "speaker_id": "S99", "kind": "turns", "condition": "quiet",
        "complete": True, "input_overflows": 0, "peak_level": 9000,
        "clock_fit": {"a_samples_per_ns": a, "b_samples": b, "rate_hz_measured": a * 1e9}}))


def test_check_session_flags_empty_answer(tmp_path, capsys):
    # tones are not speech for Silero, so every answer window is "empty": check must say so
    _fake_session(tmp_path, [tone(600), tone(400)])
    problems = check_session(tmp_path)
    assert any("no speech found" in p for p in problems)
    assert "trials completed 2" in capsys.readouterr().out
