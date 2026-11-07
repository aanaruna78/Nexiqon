"""Test kit shared by every service: signing keys and two-tenant fixtures.

Every service's tests can do::

    from nexiqon_core.testing import TwoTenants
    tenants = TwoTenants.create()
    client.get("/thing", headers=tenants.a.headers)   # tenant A
    client.get("/thing", headers=tenants.b.headers)   # must NOT see tenant A's data
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from nexiqon_core.settings import ContextTokenSettings
from nexiqon_core.tenancy import CONTEXT_HEADER, ContextTokenIssuer, TenantContext

TEST_KEY_ID = "test-key-1"


def make_keypair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for an ES256 key."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


@dataclass(frozen=True)
class Actor:
    context: TenantContext
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {CONTEXT_HEADER: self.token}


@dataclass(frozen=True)
class TwoTenants:
    settings: ContextTokenSettings
    issuer: ContextTokenIssuer
    a: Actor
    b: Actor

    @classmethod
    def create(cls, roles: frozenset[str] = frozenset({"admin"})) -> TwoTenants:
        private_pem, public_pem = make_keypair()
        settings = ContextTokenSettings(public_keys={TEST_KEY_ID: public_pem})
        issuer = ContextTokenIssuer(private_pem, TEST_KEY_ID, settings)

        def actor(name: str) -> Actor:
            ctx = TenantContext(
                tenant_id=uuid.uuid4(), actor_id=f"user-{name}", actor_type="user", roles=roles
            )
            return Actor(context=ctx, token=issuer.issue(ctx))

        return cls(settings=settings, issuer=issuer, a=actor("a"), b=actor("b"))
