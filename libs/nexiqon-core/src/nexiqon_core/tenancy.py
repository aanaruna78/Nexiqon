"""Tenant context: the only source of tenant identity inside services.

The identity service mints a short-lived, audience-scoped, signed *tenant-context token* after the
gateway has validated the end user's IdP token. Every service verifies that token itself and never
accepts a tenant id from request bodies, query strings or plain headers.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

import jwt
from fastapi import Request

from nexiqon_core.errors import Unauthorized
from nexiqon_core.settings import ContextTokenSettings

CONTEXT_HEADER = "X-Nexiqon-Context"
ActorType = Literal["user", "service", "api_key", "widget"]

_current: ContextVar[TenantContext | None] = ContextVar("nexiqon_tenant_context", default=None)


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: uuid.UUID
    actor_id: str
    actor_type: ActorType
    roles: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)
    token_id: str = ""
    region: str | None = None

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def current_context() -> TenantContext | None:
    return _current.get()


def require_current_context(request: Request) -> TenantContext:
    """FastAPI dependency: the context verified for *this* request (never a stale one)."""
    ctx = getattr(request.state, "tenant_context", None)
    if not isinstance(ctx, TenantContext):
        raise Unauthorized("No tenant context")
    return ctx


class ContextTokenIssuer:
    """Signs tenant-context tokens. Used only by the identity service (and tests)."""

    def __init__(
        self,
        private_key_pem: str,
        key_id: str,
        settings: ContextTokenSettings,
        ttl_seconds: int = 300,
    ) -> None:
        self._key = private_key_pem
        self._kid = key_id
        self._settings = settings
        self._ttl = ttl_seconds

    def issue(self, ctx: TenantContext, *, now: float | None = None) -> str:
        issued = int(now if now is not None else time.time())
        claims: dict[str, Any] = {
            "iss": self._settings.issuer,
            "aud": self._settings.audience,
            "iat": issued,
            "nbf": issued,
            "exp": issued + self._ttl,
            "jti": ctx.token_id or uuid.uuid4().hex,
            "sub": ctx.actor_id,
            "tid": str(ctx.tenant_id),
            "aty": ctx.actor_type,
            "rol": sorted(ctx.roles),
            "grp": sorted(ctx.groups),
        }
        if ctx.region:
            claims["reg"] = ctx.region
        return jwt.encode(
            claims, self._key, algorithm=self._settings.algorithm, headers={"kid": self._kid}
        )


class ContextTokenVerifier:
    """Verifies tenant-context tokens in every service."""

    def __init__(self, settings: ContextTokenSettings) -> None:
        self._settings = settings

    def verify(self, token: str) -> TenantContext:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthorized("Malformed context token") from exc
        key = self._settings.public_keys.get(str(header.get("kid", "")))
        if key is None:
            raise Unauthorized("Unknown context token key")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[self._settings.algorithm],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "tid", "jti"]},
            )
            return TenantContext(
                tenant_id=uuid.UUID(claims["tid"]),
                actor_id=str(claims["sub"]),
                actor_type=claims.get("aty", "user"),
                roles=frozenset(claims.get("rol", [])),
                groups=frozenset(claims.get("grp", [])),
                token_id=str(claims["jti"]),
                region=claims.get("reg"),
            )
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise Unauthorized("Invalid context token") from exc


def tenant_context_dependency(verifier: ContextTokenVerifier) -> Any:
    """Build a FastAPI dependency that verifies the context header and binds the context."""

    async def dependency(request: Request) -> TenantContext:
        token = request.headers.get(CONTEXT_HEADER)
        if not token:
            raise Unauthorized("Missing tenant context")
        ctx = verifier.verify(token)
        _current.set(ctx)
        request.state.tenant_context = ctx
        request.state.context_token = token  # forwarded on service-to-service calls
        return ctx

    return dependency
