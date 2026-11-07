"""Hash chain: hash_n = SHA-256(hash_{n-1} || canonical(record_n)). Editing or deleting any
record, or reordering, breaks every later hash, which /v1/verify detects."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from nexiqon_core.signing import canonical_digest


def record(
    *,
    seq: int,
    event_id: str,
    type_: str,
    source: str,
    subject: str | None,
    actor_id: str,
    occurred_at: datetime,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "seq": seq,
        "event_id": event_id,
        "type": type_,
        "source": source,
        "subject": subject,
        "actor_id": actor_id,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "data": data,
    }


def link(prev_hash: str, rec: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prev_hash}{canonical_digest(rec)}".encode()).hexdigest()
