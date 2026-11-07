"""API key format: ``nxq_<kind>_<prefix>_<secret>``. Only SHA-256(secret) is stored."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

_KEY = re.compile(r"^nxq_(s|w)_([A-Za-z0-9]{12})_([A-Za-z0-9_-]{43})$")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


@dataclass(frozen=True)
class ParsedKey:
    kind: str  # server|widget
    prefix: str
    secret: str


def generate(kind: str) -> tuple[str, str, str]:
    """Return (full_key, prefix, secret_hash). The full key is shown to the user once."""
    if kind not in ("server", "widget"):
        raise ValueError(kind)
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    secret = secrets.token_urlsafe(32)
    full = f"nxq_{kind[0]}_{prefix}_{secret}"
    return full, prefix, hash_secret(secret)


def parse(value: str) -> ParsedKey | None:
    m = _KEY.match(value)
    if not m:
        return None
    return ParsedKey(
        kind="server" if m.group(1) == "s" else "widget", prefix=m.group(2), secret=m.group(3)
    )


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
