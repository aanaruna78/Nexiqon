"""Per-process circuit breaker and rate limiter, keyed by (tenant, tool).

Both are in-memory: with several replicas each enforces its own share. A shared limiter (Valkey)
is a later refinement; the circuit breaker is intentionally local (it protects this process).
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Circuit:
    failures: int = 0
    open_until: float = 0.0


@dataclass
class Guards:
    failures: int = 5
    cooldown: float = 30.0
    _circuits: dict[tuple[uuid.UUID, str], _Circuit] = field(default_factory=dict)
    _calls: dict[tuple[uuid.UUID, str], deque[float]] = field(default_factory=dict)

    def circuit_open(self, tenant: uuid.UUID, tool: str) -> bool:
        c = self._circuits.get((tenant, tool))
        return bool(c and c.open_until > time.monotonic())

    def record(self, tenant: uuid.UUID, tool: str, *, failed: bool) -> None:
        c = self._circuits.setdefault((tenant, tool), _Circuit())
        if not failed:
            c.failures, c.open_until = 0, 0.0
            return
        c.failures += 1
        if c.failures >= self.failures:
            c.open_until = time.monotonic() + self.cooldown
            c.failures = 0

    def allow(self, tenant: uuid.UUID, tool: str, per_minute: int | None) -> bool:
        if not per_minute:
            return True
        now = time.monotonic()
        window = self._calls.setdefault((tenant, tool), deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= per_minute:
            return False
        window.append(now)
        return True
