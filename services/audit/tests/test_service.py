import uuid

import pytest
from fastapi.testclient import TestClient

from nexiqon_audit.main import create_app
from nexiqon_audit.settings import ServiceSettings
from nexiqon_core.testing import TwoTenants


@pytest.fixture
def tenants() -> TwoTenants:
    return TwoTenants.create()


@pytest.fixture
def client(tenants: TwoTenants) -> TestClient:
    return TestClient(create_app(ServiceSettings(context_token=tenants.settings, log_json=False)))


def test_ops_endpoints(client: TestClient) -> None:
    assert client.get("/healthz").json()["service"] == "audit"
    assert client.get("/readyz").status_code == 200
    assert client.get("/meta").json()["plane"] == "control"


def test_tenant_routes_reject_missing_context(client: TestClient) -> None:
    assert client.get("/v1/context").status_code == 401


def test_each_tenant_sees_only_itself(client: TestClient, tenants: TwoTenants) -> None:
    for actor in (tenants.a, tenants.b):
        r = client.get("/v1/context", headers=actor.headers)
        assert r.status_code == 200
        assert r.json()["tenant_id"] == str(actor.context.tenant_id)


async def test_lifecycle_stub(client: TestClient) -> None:
    tenant = uuid.uuid4()
    report = await client.app.state.lifecycle.delete_tenant(tenant)  # type: ignore[attr-defined]
    assert report.residue_check_passed
    assert (await client.app.state.lifecycle.export_tenant(tenant)).artifacts == []  # type: ignore[attr-defined]
