"""Identity test fixtures: migrated Postgres and an app wired to fake identity providers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings
from nexiqon_core.signing import SigningSettings
from nexiqon_core.tenancy import ContextTokenVerifier
from nexiqon_core.testing import make_keypair
from nexiqon_identity.main import create_app
from nexiqon_identity.settings import IdpProviderSettings, ServiceSettings
from nexiqon_identity.testing import (
    CLERK_ISSUER,
    OIDC_ISSUER,
    ROLE_TABLE,
    WEBHOOK_SECRET,
    Env,
    FakeIdp,
)


@pytest.fixture(scope="session")
def identity_db(postgres: PgUrls) -> PgUrls:
    upgrade("identity", postgres.owner, postgres.app_role)
    return postgres


@pytest.fixture
def env(identity_db: PgUrls) -> Iterator[Env]:
    oidc, clerk = FakeIdp(OIDC_ISSUER), FakeIdp(CLERK_ISSUER)
    private_pem, public_pem = make_keypair()
    token_settings = ContextTokenSettings(public_keys={"ctx-1": public_pem})
    settings = ServiceSettings(
        log_json=False,
        database=DatabaseSettings(url=identity_db.app, pool_size=0),
        context_token=token_settings,
        signing=SigningSettings(active_kid="ctx-1", private_keys={"ctx-1": private_pem}),
        idp_providers=[
            IdpProviderSettings(
                name="keycloak", kind="keycloak", issuer=OIDC_ISSUER, jwks_url="mem://oidc"
            ),
            IdpProviderSettings(
                name="clerk",
                kind="clerk",
                issuer=CLERK_ISSUER,
                jwks_url="mem://clerk",
                authorized_parties=["https://studio.test"],
                claim_org="org_id",
            ),
        ],
        clerk_webhook_secret=WEBHOOK_SECRET,
        context_cache_seconds=0,
    )
    jwks = {"mem://oidc": oidc.jwks(), "mem://clerk": clerk.jwks()}

    async def fetch(url: str) -> dict[str, Any]:
        return jwks[url]

    app = create_app(settings, authorizer=StaticAuthorizer(ROLE_TABLE), jwks_fetcher=fetch)
    with TestClient(app) as client:
        yield Env(
            client=client, oidc=oidc, clerk=clerk, verifier=ContextTokenVerifier(token_settings)
        )
