"""Test helpers for identity: fake OIDC provider, fake Clerk webhooks, test environment.

Used by services/identity/tests and the cross-service isolation suite. Not used at runtime.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm

from nexiqon_core.tenancy import CONTEXT_HEADER, ContextTokenVerifier, TenantContext

OIDC_ISSUER = "https://idp.test/realms/nexiqon"
CLERK_ISSUER = "https://clerk.test"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"webhook-test-secret-0123456789ab").decode()

# Mirrors services/authz/policies (owner-only actions excluded from admin).
ROLE_TABLE = {
    "owner": ["**"],
    "admin": [
        "identity.tenant.*",
        "identity.members.*",
        "identity.groups.*",
        "identity.api_keys.*",
    ],
    "editor": ["**.read"],
    "member": ["**.read"],
}


@dataclass
class FakeIdp:
    issuer: str
    kid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(ECAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": self.kid, "alg": "ES256", "use": "sig"})
        return {"keys": [jwk]}

    def token(self, sub: str, *, ttl: int = 300, **claims: Any) -> str:
        now = int(time.time())
        payload = {"iss": self.issuer, "sub": sub, "iat": now, "exp": now + ttl, **claims}
        return jwt.encode(payload, self.key, algorithm="ES256", headers={"kid": self.kid})

    def user(
        self, sub: str, email: str | None = None, *, mfa: bool = True, verified: bool = True
    ) -> str:
        claims: dict[str, Any] = {"amr": ["pwd", "otp"] if mfa else ["pwd"]}
        if email:
            claims.update(email=email, email_verified=verified, name=email.split("@")[0])
        return self.token(sub, **claims)


@dataclass
class Env:
    client: TestClient
    oidc: FakeIdp
    clerk: FakeIdp
    verifier: ContextTokenVerifier

    def context(self, idp_token: str, tenant: str | None = None, origin: str | None = None) -> str:
        headers = {"Authorization": f"Bearer {idp_token}"}
        if tenant:
            headers["X-Nexiqon-Tenant"] = tenant
        if origin:
            headers["Origin"] = origin
        r = self.client.post("/internal/ext-authz/agent/v1/anything", headers=headers)
        assert r.status_code == 200, r.text
        return str(r.headers[CONTEXT_HEADER])

    def ctx(self, token: str) -> TenantContext:
        return self.verifier.verify(token)

    def signup(self, sub: str, email: str, slug: str) -> tuple[str, str]:
        """Create a tenant as a new user; return (idp_token, context_token)."""
        idp_token = self.oidc.user(sub, email)
        r = self.client.post(
            "/v1/session/tenants",
            json={"name": slug.title(), "slug": slug},
            headers={"Authorization": f"Bearer {idp_token}"},
        )
        assert r.status_code == 201, r.text
        return idp_token, self.context(idp_token, slug)

    def webhook(self, event: dict[str, Any], secret: str = WEBHOOK_SECRET) -> Any:
        body = json.dumps(event).encode()
        msg_id, ts = f"msg_{uuid.uuid4().hex}", str(int(time.time()))
        key = base64.b64decode(secret.removeprefix("whsec_"))
        sig = base64.b64encode(
            hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
        ).decode()
        headers = {
            "svix-id": msg_id,
            "svix-timestamp": ts,
            "svix-signature": f"v1,{sig}",
            "content-type": "application/json",
        }
        return self.client.post("/v1/webhooks/clerk", content=body, headers=headers)


def slug() -> str:
    return f"t-{uuid.uuid4().hex[:10]}"
