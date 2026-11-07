"""ES256 signing keys with rotation, and the public JWKS that verifiers use.

Used by identity (tenant-context tokens) and config (signed configuration snapshots).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from jwt.algorithms import ECAlgorithm
from pydantic import BaseModel, Field, SecretStr

from nexiqon_core.errors import Unauthorized


class SigningSettings(BaseModel):
    """Private keys by key id. Old keys stay listed (published in JWKS) during rotation."""

    active_kid: str = ""
    private_keys: dict[str, SecretStr] = Field(default_factory=dict)  # kid -> PEM

    @property
    def configured(self) -> bool:
        return bool(self.active_kid) and self.active_kid in self.private_keys

    def active_pem(self) -> str:
        return self.private_keys[self.active_kid].get_secret_value()


def jwks(signing: SigningSettings) -> dict[str, Any]:
    keys: list[dict[str, Any]] = []
    for kid, secret in sorted(signing.private_keys.items()):
        private = serialization.load_pem_private_key(secret.get_secret_value().encode(), None)
        jwk = json.loads(ECAlgorithm.to_jwk(private.public_key()))  # type: ignore[arg-type]
        jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
        keys.append(jwk)
    return {"keys": keys}


def sign(signing: SigningSettings, claims: dict[str, Any]) -> str:
    return jwt.encode(
        claims, signing.active_pem(), algorithm="ES256", headers={"kid": signing.active_kid}
    )


def verify(token: str, public_keys: dict[str, str]) -> dict[str, Any]:
    """Verify an ES256 JWS against PEM public keys by kid (raises Unauthorized)."""
    try:
        kid = str(jwt.get_unverified_header(token).get("kid", ""))
        key = public_keys[kid]
        claims: dict[str, Any] = jwt.decode(
            token, key, algorithms=["ES256"], options={"verify_aud": False}
        )
        return claims
    except (jwt.PyJWTError, KeyError) as exc:
        raise Unauthorized("Invalid signature") from exc


def canonical_digest(body: Any) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace): stable across producers/consumers."""
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
