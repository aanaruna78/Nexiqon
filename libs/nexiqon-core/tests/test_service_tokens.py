"""Service tokens (ADR 0017): a service key can only speak as that service."""

from __future__ import annotations

import uuid

import pytest

from nexiqon_core.errors import ServiceUnavailable, Unauthorized
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.settings import ContextTokenSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import ContextTokenIssuer, ContextTokenVerifier, TenantContext
from nexiqon_core.testing import make_keypair


def setup() -> tuple[ContextTokenSettings, str, str]:
    idp_private, idp_public = make_keypair()
    svc_private, svc_public = make_keypair()
    settings = ContextTokenSettings(
        public_keys={"idp-1": idp_public, "svc-ingestion-1": svc_public},
        service_keys={"svc-ingestion-1": "ingestion"},
    )
    return settings, idp_private, svc_private


def test_service_token_round_trip_and_cache() -> None:
    settings, _, svc_private = setup()
    tokens = ServiceTokens(
        "ingestion",
        settings,
        ServiceIdentitySettings(key_id="svc-ingestion-1", private_key=svc_private),  # type: ignore[arg-type]
    )
    tenant = uuid.uuid4()
    token = tokens.for_tenant(tenant)
    assert tokens.for_tenant(tenant) == token  # cached
    ctx = ContextTokenVerifier(settings).verify(token)
    assert ctx.tenant_id == tenant
    assert ctx.actor_id == "service:ingestion"
    assert ctx.actor_type == "service"
    assert ctx.roles == frozenset({"service:ingestion"})


def test_service_key_cannot_mint_other_identities() -> None:
    settings, _, svc_private = setup()
    issuer = ContextTokenIssuer(svc_private, "svc-ingestion-1", settings)
    verifier = ContextTokenVerifier(settings)
    tenant = uuid.uuid4()
    forged = [
        TenantContext(tenant, "user-1", "user", frozenset({"owner"})),
        TenantContext(
            tenant, "service:ingestion", "service", frozenset({"service:ingestion", "owner"})
        ),
        TenantContext(tenant, "service:config", "service", frozenset({"service:config"})),
        TenantContext(tenant, "service:ingestion", "service", frozenset({"service"})),
    ]
    for ctx in forged:
        with pytest.raises(Unauthorized):
            verifier.verify(issuer.issue(ctx))


def test_identity_tokens_cannot_carry_per_service_roles() -> None:
    settings, idp_private, _ = setup()
    issuer = ContextTokenIssuer(idp_private, "idp-1", settings)
    ctx = TenantContext(uuid.uuid4(), "user-1", "user", frozenset({"service:ingestion"}))
    with pytest.raises(Unauthorized):
        ContextTokenVerifier(settings).verify(issuer.issue(ctx))


def test_unconfigured_identity_fails_closed() -> None:
    tokens = ServiceTokens("ingestion", ContextTokenSettings(), ServiceIdentitySettings())
    assert not tokens.configured
    with pytest.raises(ServiceUnavailable):
        tokens.for_tenant(uuid.uuid4())
