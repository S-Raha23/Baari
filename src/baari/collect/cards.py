"""Prompt-card decks for recording sessions, with generated FAKE values.

Decks are shuffled per session from a seed, rotating card types so each session covers all of
them. Fake mobile numbers start with 5, which no Indian mobile number does, so a card can never
contain a real person's number.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

CARDS_PATH = Path(__file__).with_name("cards.yaml")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def load_cards(path: Path = CARDS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fake_values(rng: random.Random) -> dict[str, str]:
    """Generated values for card placeholders. Never real identifiers."""
    mobile = "5" + "".join(rng.choice("0123456789") for _ in range(9))
    day = rng.randint(1, 28)
    suffix = "th" if 10 <= day <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return {
        "mobile": f"{mobile[:5]} {mobile[5:]}",
        "last4": "".join(rng.choice("0123456789") for _ in range(4)),
        "code6": "".join(rng.choice("0123456789") for _ in range(6)),
        "amount": f"{rng.choice([1, 2, 3, 4, 5, 7, 8, 12, 15, 25]) * rng.choice([100, 250, 1000]) + rng.choice([0, 50, 99]):,}",
        "date": f"{day}{suffix} {rng.choice(MONTHS)}",
    }


@dataclass
class TurnCard:
    """One turn trial: the bot asks `bot`, the participant follows `card`."""

    trial: int
    card_type: str
    slot: str
    expected_digits: int | None
    bot: str
    card: str
    values: dict[str, str]


@dataclass
class BargeinCard:
    """One barge-in trial: the bot speaks `sentences`, the participant does `action`."""

    trial: int
    action: str
    instruction: str
    explanation: str
    sentences: list[str]


def turn_deck(n: int, seed: int, cards: dict[str, Any] | None = None) -> list[TurnCard]:
    """`n` turn trials cycling through all card types in shuffled rounds."""
    cards = cards or load_cards()
    rng = random.Random(seed)
    types = list(cards["turns"])
    deck: list[TurnCard] = []
    while len(deck) < n:
        rng.shuffle(types)
        for t in types:
            if len(deck) >= n:
                break
            spec = cards["turns"][t]
            vals = fake_values(rng)
            deck.append(TurnCard(len(deck) + 1, t, spec["slot"], spec.get("expected_digits"),
                                 rng.choice(spec["bot"]), rng.choice(spec["cards"]).format(**vals), vals))
    return deck


def bargein_deck(n: int, seed: int, cards: dict[str, Any] | None = None) -> list[BargeinCard]:
    """`n` barge-in trials with actions balanced (round-robin over a shuffled order)."""
    cards = cards or load_cards()
    rng = random.Random(seed)
    actions = list(cards["bargein"]["actions"])
    expl = list(cards["bargein"]["explanations"])
    deck: list[BargeinCard] = []
    while len(deck) < n:
        rng.shuffle(actions)
        for a in actions:
            if len(deck) >= n:
                break
            e = rng.choice(expl)
            deck.append(BargeinCard(len(deck) + 1, a, cards["bargein"]["actions"][a], e,
                                    list(cards["bargein"]["explanations"][e])))
    return deck


def all_bot_texts(cards: dict[str, Any] | None = None) -> list[str]:
    """Every text Timbre must synthesise for collection (for cache warm-up and cost estimate)."""
    cards = cards or load_cards()
    texts = [cards["consent"]["statement"]]
    for spec in cards["turns"].values():
        texts += spec["bot"]
    for sentences in cards["bargein"]["explanations"].values():
        texts += sentences
    return list(dict.fromkeys(texts))


def card_dict(card: TurnCard | BargeinCard) -> dict[str, Any]:
    return asdict(card)
