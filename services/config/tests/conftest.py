"""Config test fixtures: migrated Postgres and app clients per role."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexiqon_config.main import create_app
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import DatabaseSettings
from nexiqon_core.signing import SigningSettings
from nexiqon_core.testing import TwoTenants, make_keypair

ROOT = Path(__file__).resolve().parents[3]
PACK_YAML = (ROOT / "packs/saas-knowledge-assistant/pack.yaml").read_text()
SIGNING_PRIVATE, SIGNING_PUBLIC = make_keypair()

# Mirrors services/authz/policies: security floors are owner-only.
ROLES = {
    "owner": ["**"],
    "admin": [
        "config.kinds.*",
        "config.objects.*",
        "config.snapshots.*",
        "config.deployments.*",
        "config.flags.*",
        "config.vocabulary.*",
        "config.profiles.resolve",
    ]
    + [
        f"config.{k}.*"
        for k in (
            "domain_pack",
            "agent",
            "model_profile",
            "retrieval_profile",
            "tool",
            "channel",
            "tenant_settings",
            "retention_profile",
        )
    ]
    + ["config.security_floors.read"],
    "member": ["**.read", "config.profiles.resolve"],
}


@pytest.fixture(scope="session")
def config_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    return postgres


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def pack_yaml() -> str:
    return PACK_YAML


@pytest.fixture
def snapshot_public_key() -> str:
    return SIGNING_PUBLIC


@pytest.fixture
def make_client(config_db: PgUrls) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(tenants: TwoTenants, **overrides: object) -> TestClient:
        settings = ServiceSettings(
            log_json=False,
            context_token=tenants.settings,
            database=DatabaseSettings(url=config_db.app, pool_size=0),
            snapshot_signing=SigningSettings(
                active_kid="snap-1", private_keys={"snap-1": SIGNING_PRIVATE}
            ),
            **overrides,  # type: ignore[arg-type]
        )
        client = TestClient(create_app(settings, authorizer=StaticAuthorizer(ROLES)))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for c in clients:
        c.__exit__(None, None, None)
