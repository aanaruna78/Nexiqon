"""Data-plane snapshot client against the real config service: verify, cache, fall back, reject tampering."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nexiqon_config.main import create_app
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.config_client import SnapshotClient
from nexiqon_core.errors import Unauthorized
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import DatabaseSettings
from nexiqon_core.signing import SigningSettings
from nexiqon_core.testing import TwoTenants, make_keypair

pytestmark = pytest.mark.integration
PACK = (
    Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml"
).read_text()


class Down(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("control plane down")


async def test_snapshot_pull_cache_and_fallback(config_db: PgUrls, tmp_path: Path) -> None:
    t = TwoTenants.create()
    private, public = make_keypair()
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=t.settings,
            database=DatabaseSettings(url=config_db.app),
            snapshot_signing=SigningSettings(active_kid="k1", private_keys={"k1": private}),
        ),
        authorizer=StaticAuthorizer({"admin": ["**"]}),
    )
    transport = httpx.ASGITransport(app=app)
    h = t.a.headers
    async with httpx.AsyncClient(transport=transport, base_url="http://config") as c:
        assert (
            await c.post(
                "/v1/packs/import", content=PACK, headers={**h, "content-type": "application/yaml"}
            )
        ).status_code == 201
        await c.post(
            "/v1/objects/domain_pack/saas-knowledge-assistant/versions/1/publish", headers=h
        )
        await c.put(
            "/v1/objects/domain_pack/saas-knowledge-assistant/deployments/dev",
            json={"version": 1},
            headers=h,
        )
        spec = {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "Help"}
        await c.post("/v1/objects", json={"kind": "agent", "name": "help", "spec": spec}, headers=h)
        await c.post("/v1/objects/agent/help/versions/1/publish", headers=h)
        assert (
            await c.put("/v1/objects/agent/help/deployments/dev", json={"version": 1}, headers=h)
        ).status_code == 200

    tenant = str(t.a.context.tenant_id)
    client = SnapshotClient("http://config", "dev", {"k1": public}, tmp_path, transport=transport)
    first = await client.get(t.a.token, tenant)
    assert first.source == "remote"
    assert first.agent("help")["config"]["display_name"] == "Help"
    second = await client.get(t.a.token, tenant)  # 304 -> cache
    assert (second.source, second.digest) == ("cache", first.digest)

    offline = SnapshotClient("http://config", "dev", {"k1": public}, tmp_path, transport=Down())
    assert (await offline.get(t.a.token, tenant)).source == "cache"

    # Tampering with the cached snapshot is detected.
    path = tmp_path / f"{tenant}.dev.json"
    payload = json.loads(path.read_text())
    payload["snapshot"]["agents"]["help"]["config"]["guardrails"]["pii_redaction"] = False
    path.write_text(json.dumps(payload))
    with pytest.raises(Unauthorized):
        await offline.get(t.a.token, tenant)

    # A snapshot signed by another key is rejected.
    _, other_public = make_keypair()
    path.unlink()
    with pytest.raises(Unauthorized):
        await SnapshotClient(
            "http://config", "dev", {"k1": other_public}, tmp_path, transport=transport
        ).get(t.a.token, tenant)
    await app.state.db.engine.dispose()
