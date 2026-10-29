"""Single-key input for the terminal collection UI (Windows console; line input elsewhere)."""

from __future__ import annotations

import os
import sys
import time

ENTER = "\r"


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def flush_keys() -> None:
    """Discard keys pressed earlier (e.g. while the bot was talking)."""
    if os.name == "nt":
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()


def wait_key(valid: str, timeout: float | None = None) -> str | None:
    """Block until one of `valid` is pressed (case-insensitive); Enter is '\\r'.

    Returns None on timeout.
    """
    valid = valid.lower()
    if os.name != "nt":  # fallback: line-based
        line = sys.stdin.readline().strip().lower()
        return ENTER if not line and ENTER in valid else (line[:1] if line[:1] in valid else None)
    import msvcrt

    end = None if timeout is None else time.monotonic() + timeout
    while end is None or time.monotonic() < end:
        if msvcrt.kbhit():
            ch = msvcrt.getwch().lower()
            if ch == "\n":
                ch = ENTER
            if ch in valid:
                return ch
        time.sleep(0.005)
    return None


def key_pressed(valid: str) -> str | None:
    """Non-blocking check for one of `valid`."""
    return wait_key(valid, timeout=0.0) if os.name == "nt" else None
