"""Disk cache for Prisma results, keyed by hash(audio bytes + session config + commit plan).

Offline experiments read from here and never call the API again. Entries store every server
message with its arrival time in ms of audio time, so replays keep the real word-lane delay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from baari.config import CACHE_DIR
from baari.usage import stable_hash

STT_CACHE = CACHE_DIR / "stt"


def stt_key(audio: bytes, headers_wo_key: dict[str, str], plan: dict[str, Any]) -> str:
    """Cache key; `headers_wo_key` must not contain the API key."""
    assert "x-api-key-id" not in {k.lower() for k in headers_wo_key}
    return stable_hash(audio, headers_wo_key, plan)


def load(key: str, root: Path = STT_CACHE) -> dict[str, Any] | None:
    path = root / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save(key: str, entry: dict[str, Any], root: Path = STT_CACHE) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{key}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
