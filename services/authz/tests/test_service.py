import uuid

import pytest
from fastapi.testclient import TestClient

from nexiqon_authz.main import create_app
from nexiqon_authz.settings import ServiceSettings
from nexiqon_core.testing import TwoTenants


@pytest.fixture
def client() -> TestClient:
    t = TwoTenants.create()
    return TestClient(create_app(ServiceSettings(context_token=t.settings, log_json=False)))


def test_ops_endpoints(client: TestClient) -> None:
    assert client.get("/healthz").json()["service"] == "authz"
    assert client.get("/meta").json()["plane"] == "control"


async def test_lifecycle_stub(client: TestClient) -> None:
    report = await client.app.state.lifecycle.delete_tenant(uuid.uuid4())  # type: ignore[attr-defined]
    assert report.residue_check_passed
