"""`python -m baari collect`: run a recording session (turns, barge-in or noise-only).

Turns: card → bot asks (Timbre, cached) → participant answers → presses ENTER (Done).
Barge-in: card with an action → bot speaks a long explanation → participant acts during it.
Noise: records background noise alone for augmentation.

Keys during a session: ENTER = continue / Done, r = redo the trial, s = skip, q = quit.
Every key press and playback milestone is an event in events.jsonl (labels are made in M3).
"""

from __future__ import annotations

import time
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import sounddevice as sd

from baari.audio.playback import Player, Utterance
from baari.collect import keys
from baari.collect.cards import all_bot_texts, bargein_deck, load_cards, turn_deck
from baari.collect.consent import ensure_speaker, has_consent, record_consent, speaker_dir
from baari.collect.recorder import SessionRecorder
from baari.config import BaariConfig, get_api_key
from baari.tts.cache import cached_path, get_or_synth
from baari.usage import require_confirmation

CONDITIONS = ["quiet", "fan", "tv", "kitchen", "street", "earphone", "other"]

TURN_INSTRUCTIONS = """\
Instructions (read this to the participant):
  "Normal phone call ki tarah bolo. Sochne ke liye ruk sakte ho, 'matlab', 'toh' bol sakte ho -
   bilkul theek hai. Jab poori baat ho jaaye, tab Done (ENTER) dabana."
Don't rush them and don't coach them to pause. Use headphones.
"""

BARGEIN_INSTRUCTIONS = """\
Instructions: the bot will talk for 15-25 seconds. The card says what to do WHILE it talks.
Use HEADPHONES so the bot's voice does not reach the microphone.
"""


def prepare_tts(cfg: BaariConfig, *, confirmed: bool) -> int:
    """Synthesise every collection prompt that is not cached yet. Returns API calls made."""
    texts = all_bot_texts()
    missing = [t for t in texts if not cached_path(t, cfg.timbre).exists()]
    if not missing:
        return 0
    chars = sum(len(t) for t in missing)
    print(f"TTS cache: {len(texts) - len(missing)}/{len(texts)} prompts cached; "
          f"{len(missing)} Timbre calls needed ({chars} characters).")
    require_confirmation(len(missing), threshold=cfg.api_call_confirm_threshold, confirmed=confirmed,
                         what="TTS warm-up")
    key = get_api_key()
    for i, t in enumerate(missing, 1):
        get_or_synth(t, cfg.timbre, key)
        print(f"  [{i}/{len(missing)}] {t[:60]}")
    return len(missing)


def _utterance(cfg: BaariConfig, sentences: list[str]) -> Utterance:
    return Utterance.from_chunks([(s, get_or_synth(s, cfg.timbre, None)) for s in sentences])


def _session_meta(cfg: BaariConfig, speaker: str, kind: str, condition: str, device: int | None,
                  session_id: str) -> dict[str, Any]:
    dev = sd.query_devices(device if device is not None else sd.default.device[0])
    out = sd.query_devices(sd.default.device[1])
    return {
        "speaker_id": speaker, "session_id": session_id, "kind": kind, "condition": condition,
        "input_device": dev["name"], "output_device": out["name"], "sample_rate": 16000,
        "timbre": asdict(cfg.timbre) | {"rest_url": None, "sse_url": None, "ws_url": None},
        "pause_min_ms": cfg.pause_min_ms, "tool": "baari collect v1",
    }


def _play_logged(rec: SessionRecorder, player: Player, utt: Utterance, trial: int,
                 extra: dict[str, Any]) -> None:
    rec.event("bot_play_request", trial=trial)
    player.play(utt)
    player.wait()
    rec.event("bot_done", trial=trial, playback_start_ns=player.log.start_ns,
              playback_end_ns=player.log.end_ns, n_samples=len(utt.pcm),
              chunk_texts=utt.texts, chunk_starts=utt.starts,
              output_latency_s=player.output_latency, **extra)


def run_turns(cfg: BaariConfig, speaker: str, condition: str, n_cards: int, device: int | None,
              session_id: str) -> Path:
    deck = turn_deck(n_cards, seed=zlib.crc32(session_id.encode()))
    d = speaker_dir(speaker) / session_id
    meta = _session_meta(cfg, speaker, "turns", condition, device, session_id)
    meta["cards"] = [asdict(c) for c in deck]
    player = Player()
    try:
        with SessionRecorder(d, meta, device=device) as rec:
            i = 0
            while i < len(deck):
                card = deck[i]
                keys.clear()
                print(f"{speaker} | turns | {condition} | trial {i + 1}/{len(deck)}\n")
                print(TURN_INSTRUCTIONS if i == 0 else "")
                print("CARD:\n\n    " + card.card + "\n")
                print("ENTER = play the bot's question   s = skip   q = quit")
                rec.event("card_shown", trial=card.trial, card_type=card.card_type)
                keys.flush_keys()
                k = keys.wait_key(keys.ENTER + "sq")
                if k == "q":
                    rec.event("quit", trial=card.trial)
                    break
                if k == "s":
                    rec.event("trial_skipped", trial=card.trial)
                    i += 1
                    continue
                print(f"\nBOT: {card.bot}")
                _play_logged(rec, player, _utterance(cfg, [card.bot]), card.trial,
                             {"slot": card.slot, "bot_text": card.bot})
                print("\n>>> Answer now. Press ENTER (Done) only when you have FINISHED speaking. <<<")
                print("    (r = redo this trial)")
                keys.flush_keys()
                k = keys.wait_key(keys.ENTER + "r")
                if k == "r":
                    rec.event("trial_redo", trial=card.trial)
                    continue
                rec.event("done", trial=card.trial)
                if rec.peak >= 32700:
                    print("warning: the microphone is clipping; move it a little further away.")
                    time.sleep(1.5)
                time.sleep(0.4)
                i += 1
    finally:
        player.close()
    return d


def run_bargein(cfg: BaariConfig, speaker: str, condition: str, n_trials: int, device: int | None,
                session_id: str) -> Path:
    deck = bargein_deck(n_trials, seed=zlib.crc32(session_id.encode()))
    d = speaker_dir(speaker) / session_id
    meta = _session_meta(cfg, speaker, "bargein", condition, device, session_id)
    meta["cards"] = [asdict(c) for c in deck]
    player = Player()
    try:
        with SessionRecorder(d, meta, device=device) as rec:
            i = 0
            while i < len(deck):
                card = deck[i]
                keys.clear()
                print(f"{speaker} | barge-in | {condition} | trial {i + 1}/{len(deck)}\n")
                print(BARGEIN_INSTRUCTIONS if i == 0 else "")
                print("CARD:\n\n    " + card.instruction + "\n")
                print("ENTER = start the bot   s = skip   q = quit")
                rec.event("card_shown", trial=card.trial, action=card.action)
                keys.flush_keys()
                k = keys.wait_key(keys.ENTER + "sq")
                if k == "q":
                    rec.event("quit", trial=card.trial)
                    break
                if k == "s":
                    rec.event("trial_skipped", trial=card.trial)
                    i += 1
                    continue
                print("\n(bot is talking...)")
                _play_logged(rec, player, _utterance(cfg, card.sentences), card.trial,
                             {"action": card.action, "explanation": card.explanation})
                time.sleep(1.0)  # catch reactions right at the end
                print("\nDid the participant do what the card said?  ENTER = yes   r = redo")
                keys.flush_keys()
                if keys.wait_key(keys.ENTER + "r") == "r":
                    rec.event("trial_redo", trial=card.trial)
                    continue
                rec.event("trial_ok", trial=card.trial, action=card.action)
                i += 1
    finally:
        player.close()
    return d


def run_noise(cfg: BaariConfig, speaker: str, condition: str, seconds: float, device: int | None,
              session_id: str) -> Path:
    d = speaker_dir(speaker) / session_id
    meta = _session_meta(cfg, speaker, "noise", condition, device, session_id)
    keys.clear()
    print(f"Noise-only recording ({condition}), {seconds:.0f} s. Nobody should speak.")
    print("ENTER to start, q to cancel.")
    if keys.wait_key(keys.ENTER + "q") == "q":
        return d
    with SessionRecorder(d, meta, device=device) as rec:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if keys.key_pressed("q"):
                rec.event("quit")
                break
            print(f"\r  recording... {end - time.monotonic():5.0f} s left (q = stop)", end="")
            time.sleep(0.5)
    print()
    return d


def collect(cfg: BaariConfig, *, speaker: str, kind: str, condition: str, n: int | None,
            seconds: float, device: int | None, confirmed: bool) -> Path | None:
    """Entry point: speaker metadata, consent, TTS warm-up, then the session."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    ensure_speaker(speaker)
    prepare_tts(cfg, confirmed=confirmed)
    if not has_consent(speaker):
        cards = load_cards()
        player = Player()
        try:
            ok = record_consent(speaker, cards["consent"]["statement"], cards["consent"]["instruction"],
                                _utterance(cfg, [cards["consent"]["statement"]]), player, device)
        finally:
            player.close()
        if not ok:
            return None
    session_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    if kind == "turns":
        d = run_turns(cfg, speaker, condition, n or 20, device, session_id)
    elif kind == "bargein":
        d = run_bargein(cfg, speaker, condition, n or 20, device, session_id)
    elif kind == "noise":
        d = run_noise(cfg, speaker, condition, seconds, device, session_id)
    else:
        raise ValueError(kind)
    print(f"\nSaved to {d}\nCheck it with:  python -m baari check-session --session {d}")
    return d

