"""Secrets port (T-02). Adapters: adapters/openbao.py (KV v2), MemorySecrets (tests).

A credential is addressed by ``(tenant, name)`` only; the adapter maps it to a tenant-prefixed
path, so one workspace can never name another's secret. Values are resolved inside tool-gateway at
call time and never returned by any API, logged, put in events or stored with call results.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Protocol

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class SecretNotFound(Exception):
    pass


class SecretsUnavailable(Exception):
    pass


def check_name(name: str) -> str:
    if not NAME.match(name):
        raise ValueError("credential names are lowercase letters, digits and dashes")
    return name


class Secrets(Protocol):
    async def get(self, tenant: uuid.UUID, name: str) -> str: ...

    async def put(self, tenant: uuid.UUID, name: str, value: str) -> None: ...

    async def delete(self, tenant: uuid.UUID, name: str) -> None: ...

    async def names(self, tenant: uuid.UUID) -> dict[str, datetime | None]: ...


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[tuple[uuid.UUID, str], tuple[str, datetime]] = {}

    async def get(self, tenant: uuid.UUID, name: str) -> str:
        try:
            return self.values[(tenant, check_name(name))][0]
        except KeyError:
            raise SecretNotFound(name) from None

    async def put(self, tenant: uuid.UUID, name: str, value: str) -> None:
        self.values[(tenant, check_name(name))] = (value, datetime.now(UTC))

    async def delete(self, tenant: uuid.UUID, name: str) -> None:
        self.values.pop((tenant, check_name(name)), None)

    async def names(self, tenant: uuid.UUID) -> dict[str, datetime | None]:
        return {n: at for (t, n), (_, at) in self.values.items() if t == tenant}


class UnconfiguredSecrets:
    """No secrets store configured: the service still starts; credential use reports why it fails."""

    async def get(self, tenant: uuid.UUID, name: str) -> str:
        raise SecretsUnavailable("no secrets store is configured")

    async def put(self, tenant: uuid.UUID, name: str, value: str) -> None:
        raise SecretsUnavailable("no secrets store is configured")

    async def delete(self, tenant: uuid.UUID, name: str) -> None:
        raise SecretsUnavailable("no secrets store is configured")

    async def names(self, tenant: uuid.UUID) -> dict[str, datetime | None]:
        return {}
