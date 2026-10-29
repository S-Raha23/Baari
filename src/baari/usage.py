"""Credit protection: usage logging and the large-job confirmation gate.

Every credit-consuming API call appends one line to `data/cache/usage.jsonl`. Jobs that
would make more than `api_call_confirm_threshold` calls must be confirmed by the human.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from baari import config as C


def log_usage(endpoint: str, *, audio_seconds: float | None = None,
              characters: int | None = None, path: Path | None = None,
              **extra: Any) -> None:
    """Append one credit-consuming call to the usage log."""
    path = path or C.USAGE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": endpoint,
    }
    if audio_seconds is not None:
        row["audio_seconds"] = round(audio_seconds, 3)
    if characters is not None:
        row["characters"] = characters
    row.update(extra)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def usage_summary(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Totals per endpoint: calls, audio seconds, characters."""
    path = path or C.USAGE_LOG
    out: dict[str, dict[str, float]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        agg = out.setdefault(row["endpoint"], {"calls": 0, "audio_seconds": 0.0, "characters": 0})
        agg["calls"] += 1
        agg["audio_seconds"] += row.get("audio_seconds", 0.0)
        agg["characters"] += row.get("characters", 0)
    return out


class BudgetExceeded(RuntimeError):
    """Raised when a job needs more API calls than allowed without confirmation."""


def require_confirmation(n_calls: int, *, threshold: int, confirmed: bool, what: str) -> None:
    """Refuse jobs above `threshold` API calls unless the human passed --yes."""
    if n_calls > threshold and not confirmed:
        raise BudgetExceeded(
            f"{what} would make {n_calls} API calls (> {threshold}). "
            "Re-run with --yes after checking the estimate."
        )


def stable_hash(*parts: bytes | str | dict[str, Any]) -> str:
    """SHA-256 over audio bytes / text / config dicts; used as cache keys."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, dict):
            part = json.dumps(part, sort_keys=True, ensure_ascii=False)
        if isinstance(part, str):
            part = part.encode("utf-8")
        h.update(len(part).to_bytes(8, "little"))
        h.update(part)
    return h.hexdigest()[:32]
