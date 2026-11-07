"""Time-ordered UUIDv7 identifiers (RFC 9562) for index-friendly primary keys."""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7. Monotonic within a process (12-bit counter per millisecond)."""
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms <= _last_ms:
            _counter += 1
            if _counter > 0xFFF:  # counter overflow: move to the next millisecond
                _last_ms += 1
                _counter = 0
            now_ms = _last_ms
        else:
            _last_ms = now_ms
            _counter = 0
        counter = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= counter << 64  # rand_a used as counter
    value |= 0b10 << 62  # variant
    value |= rand_b
    return uuid.UUID(int=value)
