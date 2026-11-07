"""Integration: authz service against a real OPA loaded with the repo's policies."""

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_authz.main import create_app
from nexiqon_authz.settings import ServiceSettings
from nexiqon_core.testing import TwoTenants

POLICIES = Path(__file__).resolve().parents[1] / "policies"
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker not available")
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer("openpolicyagent/opa:0.70.0")
        .with_volume_mapping(str(POLICIES), "/policies", "ro")
        .with_command("run --server --addr=0.0.0.0:8181 /policies")
        .with_exposed_ports(8181)
    )
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8181)}"
        for _ in range(50):
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        yield url


def client(t: TwoTenants, opa_url: str) -> TestClient:
    return TestClient(
        create_app(ServiceSettings(opa_url=opa_url, context_token=t.settings, log_json=False))
    )


def test_admin_allowed_member_denied(opa_url: str) -> None:
    admin = TwoTenants.create(roles=frozenset({"admin"}))
    member = TwoTenants.create(roles=frozenset({"member"}))
    body = {"action": "identity.members.write", "resource": {"type": "membership"}}
    with client(admin, opa_url) as c:
        assert c.post("/v1/decisions", json=body, headers=admin.a.headers).json()["allow"] is True
        assert c.get("/readyz").status_code == 200
    with client(member, opa_url) as c:
        r = c.post("/v1/decisions", json=body, headers=member.a.headers).json()
        assert r["allow"] is False
        assert "no role grants this action" in r["reasons"]


def test_actor_cannot_be_spoofed_through_body(opa_url: str) -> None:
    member = TwoTenants.create(roles=frozenset({"member"}))
    body = {
        "action": "identity.members.write",
        "resource": {"type": "membership"},
        "actor": {"roles": ["owner"], "tenant_id": str(member.b.context.tenant_id)},
    }
    with client(member, opa_url) as c:
        assert c.post("/v1/decisions", json=body, headers=member.a.headers).json()["allow"] is False


def test_cross_tenant_resource_denied(opa_url: str) -> None:
    owner = TwoTenants.create(roles=frozenset({"owner"}))
    body = {
        "action": "identity.members.read",
        "resource": {"type": "membership", "tenant_id": str(owner.b.context.tenant_id)},
    }
    with client(owner, opa_url) as c:
        assert c.post("/v1/decisions", json=body, headers=owner.a.headers).json()["allow"] is False


def test_engine_down_fails_closed() -> None:
    t = TwoTenants.create()
    with client(t, "http://127.0.0.1:9") as c:
        r = c.post(
            "/v1/decisions",
            json={"action": "a.b.c", "resource": {"type": "x"}},
            headers=t.a.headers,
        )
        assert r.json() == {"allow": False, "reasons": ["policy engine unavailable"]}
        assert c.get("/readyz").status_code == 503


def test_requires_context(opa_url: str) -> None:
    t = TwoTenants.create()
    with client(t, opa_url) as c:
        assert (
            c.post("/v1/decisions", json={"action": "a.b.c", "resource": {"type": "x"}}).status_code
            == 401
        )
