import uuid

import pytest
from fastapi.testclient import TestClient

from nexiqon_core.testing import TwoTenants
from nexiqon_identity.main import create_app
from nexiqon_identity.settings import ServiceSettings


@pytest.fixture
def client() -> TestClient:
    t = TwoTenants.create()
    return TestClient(create_app(ServiceSettings(context_token=t.settings, log_json=False)))


def test_ops_endpoints_without_database(client: TestClient) -> None:
    assert client.get("/healthz").json()["service"] == "identity"
    assert client.get("/meta").json()["plane"] == "control"
    assert client.get("/readyz").status_code == 503  # no database configured


def test_gateway_check_fails_closed_when_unconfigured(client: TestClient) -> None:
    assert (
        client.post("/internal/ext-authz/x", headers={"Authorization": "Bearer x"}).status_code
        == 401
    )


async def test_lifecycle_stub(client: TestClient) -> None:
    report = await client.app.state.lifecycle.delete_tenant(uuid.uuid4())  # type: ignore[attr-defined]
    assert report.residue_check_passed
