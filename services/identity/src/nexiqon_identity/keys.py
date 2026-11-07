"""Tenant-context token signing (identity is the only issuer) and the public JWKS."""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import ECAlgorithm

from nexiqon_core.settings import ContextTokenSettings
from nexiqon_core.tenancy import ContextTokenIssuer
from nexiqon_identity.settings import SigningSettings


def build_issuer(
    signing: SigningSettings, token_settings: ContextTokenSettings, ttl_seconds: int
) -> ContextTokenIssuer | None:
    if not signing.active_kid or signing.active_kid not in signing.private_keys:
        return None
    pem = signing.private_keys[signing.active_kid].get_secret_value()
    return ContextTokenIssuer(pem, signing.active_kid, token_settings, ttl_seconds=ttl_seconds)


def jwks(signing: SigningSettings) -> dict[str, Any]:
    keys: list[dict[str, Any]] = []
    for kid, secret in sorted(signing.private_keys.items()):
        private = serialization.load_pem_private_key(secret.get_secret_value().encode(), None)
        jwk = json.loads(ECAlgorithm.to_jwk(private.public_key()))  # type: ignore[arg-type]
        jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
        keys.append(jwk)
    return {"keys": keys}
