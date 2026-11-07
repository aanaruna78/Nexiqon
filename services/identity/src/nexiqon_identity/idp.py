"""Identity provider port. Adapters: adapters/oidc.py (Clerk, Keycloak, Auth0, generic OIDC)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IdentityClaims:
    """Provider-neutral view of a verified IdP token."""

    provider: str
    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    org_ref: str | None  # provider organisation id (e.g. Clerk org), if the token carries one
    mfa: bool
    expires_at: int


class IdentityProvider(Protocol):
    async def verify(self, token: str) -> IdentityClaims: ...
