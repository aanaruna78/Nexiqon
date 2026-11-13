"""Model-gateway fixtures: real config service + Postgres, fake provider network."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import DatabaseSettings
from nexiqon_core.testing import TwoTenants
from nexiqon_model_gateway.main import create_app
from nexiqon_model_gateway.settings import ProviderCredentials, ServiceSettings
from nexiqon_model_gateway.testing import FakeProviders

# Mirrors services/authz/policies for the actions used here.
ROLES = {
    "owner": ["**"],
    "end_user": ["model.inference.run", "config.profiles.resolve"],
    "viewer": ["**.read"],
}
CREDENTIALS = ProviderCredentials(
    openai_api_key="sk-test-openai",  # type: ignore[arg-type]
    anthropic_api_key="sk-test-anthropic",  # type: ignore[arg-type]
    gemini_api_key="test-gemini",  # type: ignore[arg-type]
)


@pytest.fixture(scope="session")
def gateway_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    upgrade("model-gateway", postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Stack:
    tenants: TwoTenants
    gateway: TestClient
    config: TestClient
    providers: FakeProviders
    db_url: str

    def deploy_profile(self, name: str, spec: dict[str, Any], headers: dict[str, str]) -> None:
        r = self.config.post(
            "/v1/objects",
            json={"kind": "model_profile", "name": name, "spec": spec},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        r = self.config.post(
            f"/v1/objects/model_profile/{name}/versions/1/publish", headers=headers
        )
        assert r.status_code == 200, r.text
        r = self.config.put(
            f"/v1/objects/model_profile/{name}/deployments/dev",
            json={"version": 1},
            headers=headers,
        )
        assert r.status_code == 200, r.text


StackFactory = Callable[..., Stack]


@pytest.fixture
def make_stack(gateway_db: PgUrls) -> Iterator[StackFactory]:
    clients: list[TestClient] = []

    def factory(deployment_floors: list[dict[str, Any]] | None = None, **overrides: Any) -> Stack:
        tenants = TwoTenants.create(roles=frozenset({"owner"}))
        config_settings = ConfigSettings(
            log_json=False,
            context_token=tenants.settings,
            database=DatabaseSettings(url=gateway_db.app, pool_size=0),
            deployment_floors=deployment_floors or [],
        )
        authorizer = StaticAuthorizer(ROLES)
        # One config app serves setup calls; another answers the gateway in-process.
        config = TestClient(create_config_app(config_settings, authorizer=authorizer))
        config_for_gateway = create_config_app(config_settings, authorizer=authorizer)
        providers = FakeProviders()
        settings = ServiceSettings(
            log_json=False,
            context_token=tenants.settings,
            database=DatabaseSettings(url=gateway_db.app, pool_size=0),
            config_url="http://config",
            providers=CREDENTIALS,
            profile_cache_seconds=0,
            **overrides,
        )
        gateway = TestClient(
            create_app(
                settings,
                authorizer=authorizer,
                provider_transport=providers.transport(),
                config_transport=httpx.ASGITransport(app=config_for_gateway),
            )
        )
        for c in (config, gateway):
            c.__enter__()
            clients.append(c)
        return Stack(tenants, gateway, config, providers, gateway_db.app)

    yield factory
    for c in clients:
        c.__exit__(None, None, None)
