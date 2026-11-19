"""Signed download links for original files (RT-06).

A link names the tenant, document, version, the person it was issued to and an expiry, and is
signed with HMAC-SHA256. Following it still needs that person's own tenant context: a link used
from another tenant, by someone else, after expiry or for a since-replaced version is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from nexiqon_core.errors import Forbidden, NotFound


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Grant:
    tenant: uuid.UUID
    document: uuid.UUID
    version: int
    actor: str
    expires: int


class DownloadSigner:
    def __init__(self, key: bytes, ttl_seconds: int) -> None:
        if len(key) < 32:
            raise ValueError("download signing key must be at least 32 bytes")
        self._key = key
        self.ttl = ttl_seconds

    def _mac(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())

    def sign(
        self,
        tenant: uuid.UUID,
        document: uuid.UUID,
        version: int,
        actor: str,
        now: float | None = None,
    ) -> tuple[str, int]:
        expires = int(now if now is not None else time.time()) + self.ttl
        body = _b64(
            json.dumps(
                {"t": str(tenant), "d": str(document), "v": version, "a": actor, "e": expires},
                separators=(",", ":"),
            ).encode()
        )
        return f"{body}.{self._mac(body)}", expires

    def verify(self, token: str, tenant: uuid.UUID, actor: str, now: float | None = None) -> Grant:
        try:
            body, mac = token.split(".", 1)
            if not hmac.compare_digest(mac, self._mac(body)):
                raise ValueError("bad signature")
            raw = json.loads(_unb64(body))
            grant = Grant(
                uuid.UUID(raw["t"]),
                uuid.UUID(raw["d"]),
                int(raw["v"]),
                str(raw["a"]),
                int(raw["e"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise NotFound("Download link not found") from exc
        if grant.expires < (now if now is not None else time.time()):
            raise Forbidden("This download link has expired")
        if grant.tenant != tenant or grant.actor != actor:
            raise NotFound("Download link not found")  # never confirm it exists elsewhere
        return grant
