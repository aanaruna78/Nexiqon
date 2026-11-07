"""Tenant-context token issuer (identity is the only issuer). JWKS helper lives in the chassis."""

from __future__ import annotations

from nexiqon_core.settings import ContextTokenSettings
from nexiqon_core.signing import SigningSettings, jwks
from nexiqon_core.tenancy import ContextTokenIssuer

__all__ = ["build_issuer", "jwks"]


def build_issuer(
    signing: SigningSettings, token_settings: ContextTokenSettings, ttl_seconds: int
) -> ContextTokenIssuer | None:
    if not signing.configured:
        return None
    return ContextTokenIssuer(
        signing.active_pem(), signing.active_kid, token_settings, ttl_seconds=ttl_seconds
    )
