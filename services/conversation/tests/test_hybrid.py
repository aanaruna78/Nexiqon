"""DV-04 acceptance: in hybrid mode the data plane answers from its own copy of the configuration
and no customer content reaches the control plane (an egress test).

Control plane: the real config service, behind a recorder that keeps every request it receives.
Data plane: the real conversation, agent-runtime and config mirror (model and retrieval faked).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_agent_runtime.main import create_app as create_runtime_app
from nexiqon_agent_runtime.settings import ServiceSettings as RuntimeSettings
from nexiqon_agent_runtime.testing import FakeServices, HostRouter
from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_config_mirror.main import create_app as create_mirror_app
from nexiqon_config_mirror.settings import ServiceSettings as MirrorSettings
from nexiqon_conversation.main import create_app
from nexiqon_conversation.settings import ServiceSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.signing import SigningSettings
from nexiqon_core.testing import TwoTenants, make_keypair

from .conftest import PACK, ROLES, ok

SECRET = "ZEBRA-7731"  # a phrase that must never leave the data plane
RT_PRIVATE, RT_PUBLIC = make_keypair()
MIRROR_PRIVATE, MIRROR_PUBLIC = make_keypair()
SNAP_PRIVATE, SNAP_PUBLIC = make_keypair()
HYBRID_ROLES = {**ROLES, "service:config-mirror": ["config.snapshots.read"]}


@dataclass
class ControlPlane(httpx.AsyncBaseTransport):
    """The control plane's config service, recording what the data plane sends it."""

    inner: httpx.AsyncBaseTransport
    seen: list[httpx.Request] = field(default_factory=list)
    down: bool = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.seen.append(request)
        if self.down:
            raise httpx.ConnectError("control plane unreachable")
        return await self.inner.handle_async_request(request)


@dataclass
class Hybrid:
    client: TestClient
    tenants: TwoTenants
    control: ControlPlane
    fakes: FakeServices


@pytest.fixture
def hybrid(conv_db: PgUrls, tmp_path: Path) -> Iterator[Hybrid]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={
            **tenants.settings.public_keys,
            "svc-ar": RT_PUBLIC,
            "svc-mirror": MIRROR_PUBLIC,
        },
        service_keys={"svc-ar": "agent-runtime", "svc-mirror": "config-mirror"},
    )
    authorizer = StaticAuthorizer(HYBRID_ROLES)
    db = DatabaseSettings(url=conv_db.app, pool_size=0)
    config_settings = ConfigSettings(
        log_json=False,
        context_token=tokens,
        database=db,
        snapshot_signing=SigningSettings(
            active_kid="snap-1", private_keys={"snap-1": SNAP_PRIVATE}
        ),  # type: ignore[arg-type]
    )
    setup = TestClient(create_config_app(config_settings, authorizer=authorizer))
    control = ControlPlane(
        httpx.ASGITransport(app=create_config_app(config_settings, authorizer=authorizer))
    )
    mirror = create_mirror_app(
        MirrorSettings(
            log_json=False,
            context_token=tokens,
            control_config_url="http://control-config",
            config_environment="dev",
            snapshot_public_keys={"snap-1": SNAP_PUBLIC},
            cache_dir=tmp_path / "mirror",
            refresh_seconds=0,
            mirror_identity=ServiceIdentitySettings(
                key_id="svc-mirror", private_key=MIRROR_PRIVATE
            ),  # type: ignore[arg-type]
        ),
        authorizer=authorizer,
        control_transport=control,
    )
    fakes = FakeServices()
    fakes.intents = {"invite a teammate": "product_question"}
    data_config = {
        "config": httpx.ASGITransport(app=mirror)
    }  # the data plane's "config" is the mirror
    runtime = create_runtime_app(
        RuntimeSettings(
            log_json=False,
            context_token=tokens,
            database=db,
            service_identity=ServiceIdentitySettings(key_id="svc-ar", private_key=RT_PRIVATE),  # type: ignore[arg-type]
            config_url="http://config",
            ingestion_url="http://ingestion",
            retrieval_url="http://retrieval",
            model_gateway_url="http://model-gateway",
            agent_cache_seconds=0,
        ),
        authorizer=authorizer,
        service_transport=HostRouter(data_config, httpx.MockTransport(fakes)),
    )
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            database=db,
            agent_runtime_url="http://agent-runtime",
            config_url="http://config",
            retention_sweep_seconds=0,
        ),
        authorizer=authorizer,
        service_transport=HostRouter(
            {"agent-runtime": httpx.ASGITransport(app=runtime), **data_config},
            httpx.MockTransport(fakes),
        ),
    )
    h = tenants.a.headers
    with setup, TestClient(app) as client:
        ok(
            setup.post(
                "/v1/packs/import", content=PACK, headers={**h, "content-type": "application/yaml"}
            ),
            201,
        )
        ok(
            setup.post(
                "/v1/objects/domain_pack/saas-knowledge-assistant/versions/1/publish", headers=h
            )
        )
        ok(
            setup.put(
                "/v1/objects/domain_pack/saas-knowledge-assistant/deployments/dev",
                json={"version": 1},
                headers=h,
            )
        )
        spec = {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Help",
            "knowledge": {"collections": ["product-docs"]},
        }
        ok(
            setup.post(
                "/v1/objects", json={"kind": "agent", "name": "support", "spec": spec}, headers=h
            ),
            201,
        )
        ok(setup.post("/v1/objects/agent/support/versions/1/publish", headers=h))
        ok(setup.put("/v1/objects/agent/support/deployments/dev", json={"version": 1}, headers=h))
        yield Hybrid(client, tenants, control, fakes)


def ask(h: Hybrid, text: str) -> dict[str, Any]:
    headers = h.tenants.a.headers
    c = ok(
        h.client.post(
            "/v1/conversations", json={"agent": "support", "channel": "widget"}, headers=headers
        ),
        201,
    )
    turn: dict[str, Any] = ok(
        h.client.post(
            f"/v1/conversations/{c['id']}/messages", json={"content": text}, headers=headers
        )
    )
    return turn


def test_the_data_plane_answers_without_sending_content_to_the_control_plane(
    hybrid: Hybrid,
) -> None:
    turn = ask(hybrid, f"How do I invite a teammate to the {SECRET} workspace?")
    assert turn["reply"]["content"] == "Open Settings, then Members, and choose Invite [1]."
    # The question did reach the data plane's own services (model and retrieval).
    assert any(SECRET in str(body) for _, body in hybrid.fakes.calls)
    # The control plane saw configuration pulls only, and none of the content.
    assert hybrid.control.seen, "the mirror pulled the tenant's snapshot"
    assert {r.url.path for r in hybrid.control.seen} == {"/v1/snapshots/dev"}
    for r in hybrid.control.seen:
        assert r.method == "GET"
        assert SECRET not in str(r.url)
        assert SECRET not in r.content.decode(errors="ignore")
        assert all(SECRET not in v for v in r.headers.values())


def test_answers_keep_working_from_the_cached_snapshot_when_the_control_plane_is_down(
    hybrid: Hybrid,
) -> None:
    ask(hybrid, "How do I invite a teammate?")  # pulls and caches the snapshot
    hybrid.control.down = True
    turn = ask(hybrid, "How do I invite a teammate?")
    assert turn["reply"]["content"].startswith("Open Settings")
    assert turn["reply"]["contract"]["status"] == "completed"
