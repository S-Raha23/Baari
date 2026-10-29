"""Speaker metadata and recorded consent (docs/DATA_PROTOCOL.md).

Stored per speaker in data/raw/<speaker>/: `speaker.json` (ID, age band, gender (optional),
languages, device; no names) and `consent/` (the statement played, the recorded answer and the
operator's confirmation). Recording sessions refuse to start without confirmed consent.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from baari.audio.playback import Player, Utterance
from baari.collect import keys
from baari.collect.recorder import SessionRecorder
from baari.config import RAW_DIR

SPEAKER_RE = re.compile(r"^S\d{2,3}$")
AGE_BANDS = ["18-29", "30-49", "50-64", "65+"]


def speaker_dir(speaker: str) -> Path:
    if not SPEAKER_RE.match(speaker):
        raise ValueError(f"speaker id must look like S01, got {speaker!r}")
    return RAW_DIR / speaker


def _ask(prompt: str, choices: list[str] | None = None, optional: bool = False) -> str:
    while True:
        hint = f" [{'/'.join(choices)}]" if choices else ""
        ans = input(f"{prompt}{hint}{' (optional, Enter to skip)' if optional else ''}: ").strip()
        if not ans and optional:
            return ""
        if ans and (choices is None or ans in choices):
            return ans


def ensure_speaker(speaker: str) -> dict[str, Any]:
    """Load speaker.json, asking the operator for it on first use (no names stored)."""
    d = speaker_dir(speaker)
    path = d / "speaker.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"New speaker {speaker}. Do NOT enter names or contact details.")
    meta = {
        "speaker_id": speaker,
        "age_band": _ask("Age band", AGE_BANDS),
        "gender": _ask("Gender", ["female", "male", "other"], optional=True),
        "languages": _ask("Languages spoken (e.g. hindi,english,bengali)"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def has_consent(speaker: str) -> bool:
    path = speaker_dir(speaker) / "consent" / "consent.json"
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("agreed") is True


def record_consent(speaker: str, statement: str, instruction: str, statement_audio: Utterance,
                   player: Player, device: int | None = None) -> bool:
    """Play the statement, record the spoken answer, and get the operator's confirmation."""
    d = speaker_dir(speaker) / "consent"
    if d.exists():
        shutil.rmtree(d)
    keys.clear()
    print("CONSENT\n\n" + statement + "\n")
    with SessionRecorder(d, {"speaker_id": speaker, "kind": "consent", "statement": statement},
                         device=device) as rec:
        rec.event("statement_start")
        player.play(statement_audio)
        player.wait()
        rec.event("statement_end", playback_start_ns=player.log.start_ns, playback_end_ns=player.log.end_ns)
        print(instruction)
        print("\nPress ENTER after the participant has answered.")
        keys.flush_keys()
        keys.wait_key(keys.ENTER)
        rec.event("answer_done")
    print("\nOperator: did the participant clearly agree, aloud? [y/n]")
    agreed = keys.wait_key("yn") == "y"
    if not agreed:
        shutil.rmtree(d)
        print("No consent: the consent recording was deleted. Nothing else is recorded.")
        return False
    (d / "consent.json").write_text(json.dumps({
        "speaker_id": speaker, "agreed": True, "statement": statement,
        "confirmed_by_operator_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def delete_speaker(speaker: str) -> list[Path]:
    """Remove all raw and derived data for a speaker. Returns the paths removed."""
    from baari.config import DATA_DIR

    removed = []
    for root in (DATA_DIR / "raw", DATA_DIR / "processed"):
        p = root / speaker
        if p.exists():
            shutil.rmtree(p)
            removed.append(p)
    # Derived caches (transcripts) are indexed per session from M3 on: data/cache/index/<speaker>.json
    idx = DATA_DIR / "cache" / "index" / f"{speaker}.json"
    if idx.exists():
        for f in json.loads(idx.read_text(encoding="utf-8")).get("files", []):
            fp = Path(f)
            if fp.exists():
                fp.unlink()
                removed.append(fp)
        idx.unlink()
        removed.append(idx)
    return removed
