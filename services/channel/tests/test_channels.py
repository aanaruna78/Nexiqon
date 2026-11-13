"""Channel settings (CH-01, W-00): read from the agent's pack with channel's own identity."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_channel.main import create_app
from nexiqon_channel.settings import ServiceSettings
from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair

pytestmark = pytest.mark.integration
PACK = (
    Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml"
).read_text()
ROLES = {
    "owner": ["**"],
    "end_user": ["channel.settings.read", "agent.query.run"],
    "service:channel": ["config.agent.read"],
}
PRIVATE, PUBLIC = make_keypair()


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture
def stack(postgres: PgUrls) -> Iterator[tuple[TestClient, TwoTenants]]:
    upgrade("config", postgres.owner, postgres.app_role)
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-ch": PUBLIC},
        service_keys={"svc-ch": "channel"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=postgres.app, pool_size=0)
    setup = TestClient(
        create_config_app(
            ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
        )
    )
    config = create_config_app(
        ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            config_url="http://config",
            settings_cache_seconds=0,
            channel_identity=ServiceIdentitySettings(key_id="svc-ch", private_key=PRIVATE),  # type: ignore[arg-type]
        ),
        authorizer=authorizer,
        service_transport=httpx.ASGITransport(app=config),
    )
    h = tenants.a.headers
    with setup, TestClient(app) as client:
        ok(
            setup.post(
                "/v1/packs/import", content=PACK, headers={**h, "content-type": "application/yaml"}
            ),
            201,
        )
        agent = {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "Acme Help"}
        ok(
            setup.post(
                "/v1/objects", json={"kind": "agent", "name": "support", "spec": agent}, headers=h
            ),
            201,
        )
        for kind, name in (("domain_pack", "saas-knowledge-assistant"), ("agent", "support")):
            ok(setup.post(f"/v1/objects/{kind}/{name}/versions/1/publish", headers=h))
            ok(
                setup.put(
                    f"/v1/objects/{kind}/{name}/deployments/dev", json={"version": 1}, headers=h
                )
            )
        yield client, tenants


def widget(tenants: TwoTenants, tenant: str = "a") -> dict[str, str]:
    t = (tenants.a if tenant == "a" else tenants.b).context.tenant_id
    ctx = TenantContext(
        t, "widget:k1:visitor-abcdefghijklmnopqrstuv", "widget", frozenset({"end_user"})
    )
    return {CONTEXT_HEADER: tenants.issuer.issue(ctx)}


def test_widget_settings_come_from_the_pack(stack: tuple[TestClient, TwoTenants]) -> None:
    client, tenants = stack
    s = ok(client.get("/v1/channels/widget/agents/support", headers=widget(tenants)))
    assert s["title"] == "Help"
    assert s["assistant_name"] == "Acme Help"
    assert s["greeting"].startswith("Hi! Ask me anything")
    assert s["starter_questions"][0] == "How do I get started?"
    assert s["accent_color"] == "#0E8A7E"
    assert s["handoff"] is True
    assert s["endpoints"]["stream"].endswith("/messages/stream")
    assert "config" not in s  # the agent's configuration itself never leaves the platform
    assert "guardrails" not in str(s)


def test_channel_rules(stack: tuple[TestClient, TwoTenants]) -> None:
    client, tenants = stack
    assert client.get("/v1/channels/api/agents/support", headers=widget(tenants)).status_code == 403
    assert (
        client.get("/v1/channels/fax/agents/support", headers=tenants.a.headers).status_code == 404
    )
    assert (
        ok(client.get("/v1/channels/api/agents/support", headers=tenants.a.headers))["channel"]
        == "api"
    )
    assert {c["name"] for c in ok(client.get("/v1/channels", headers=tenants.a.headers))} == {
        "widget",
        "api",
    }
    # Tenant B has no such agent: its own service token sees only its own configuration.
    assert (
        client.get("/v1/channels/widget/agents/support", headers=widget(tenants, "b")).status_code
        == 404
    )
