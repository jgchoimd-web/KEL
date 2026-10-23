"""Small shared helpers: errors, logging, version comparison, hashing."""

from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path


class KelError(Exception):
    """An error that should be reported to the user without a traceback."""


def log(msg: str) -> None:
    print(f"kel: {msg}", file=sys.stderr, flush=True)


def warn(msg: str) -> None:
    print(f"kel: warning: {msg}", file=sys.stderr, flush=True)


def sha256_file(path: Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bufsize):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_VERSION_PART = re.compile(r"(\d+|[A-Za-z]+)")


def version_key(version: str) -> tuple:
    """Split a dotted version into comparable parts ("2.13.1" < "2.47")."""
    parts: list[tuple[int, int | str]] = []
    for tok in _VERSION_PART.findall(version):
        parts.append((0, int(tok)) if tok.isdigit() else (1, tok))
    return tuple(parts)


def version_at_least(found: str, minimum: str) -> bool:
    return version_key(found) >= version_key(minimum)


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{seconds:02d}s"


class Timer:
    def __enter__(self) -> "Timer":
        self.start = time.monotonic()
        self.elapsed = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.monotonic() - self.start
