import uuid

import jwt
import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from nexiqon_core.app import create_service_app
from nexiqon_core.errors import Unauthorized
from nexiqon_core.settings import ContextTokenSettings, CoreSettings
from nexiqon_core.tenancy import (
    CONTEXT_HEADER,
    ContextTokenIssuer,
    ContextTokenVerifier,
    TenantContext,
    require_current_context,
)
from nexiqon_core.testing import TEST_KEY_ID, TwoTenants, make_keypair


def test_round_trip(tenants: TwoTenants) -> None:
    ctx = ContextTokenVerifier(tenants.settings).verify(tenants.a.token)
    assert ctx.tenant_id == tenants.a.context.tenant_id
    assert ctx.roles == frozenset({"admin"})


def test_expired_token_rejected(tenants: TwoTenants) -> None:
    old = tenants.issuer.issue(tenants.a.context, now=0)
    with pytest.raises(Unauthorized):
        ContextTokenVerifier(tenants.settings).verify(old)


def test_wrong_audience_rejected(tenants: TwoTenants) -> None:
    private_pem, public_pem = make_keypair()
    other = ContextTokenSettings(audience="someone-else", public_keys={TEST_KEY_ID: public_pem})
    token = ContextTokenIssuer(private_pem, TEST_KEY_ID, other).issue(tenants.a.context)
    verifier_settings = ContextTokenSettings(public_keys={TEST_KEY_ID: public_pem})
    with pytest.raises(Unauthorized):
        ContextTokenVerifier(verifier_settings).verify(token)


def test_token_signed_by_unknown_key_rejected(tenants: TwoTenants) -> None:
    forged_private, _ = make_keypair()
    forged = ContextTokenIssuer(forged_private, TEST_KEY_ID, tenants.settings).issue(
        TenantContext(tenant_id=uuid.uuid4(), actor_id="mallory", actor_type="user")
    )
    with pytest.raises(Unauthorized):
        ContextTokenVerifier(tenants.settings).verify(forged)


def test_unsigned_token_rejected(tenants: TwoTenants) -> None:
    claims = jwt.decode(tenants.a.token, options={"verify_signature": False})
    unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": TEST_KEY_ID})
    with pytest.raises(Unauthorized):
        ContextTokenVerifier(tenants.settings).verify(unsigned)


def _app(tenants: TwoTenants) -> TestClient:
    router = APIRouter()

    @router.get("/whoami")
    async def whoami(ctx: TenantContext = Depends(require_current_context)) -> dict[str, str]:
        return {"tenant_id": str(ctx.tenant_id)}

    settings = CoreSettings(service_name="t", context_token=tenants.settings, log_json=False)
    app = create_service_app(
        name="t", version="0", plane="data", settings=settings, tenant_routers=[router]
    )
    return TestClient(app)


def test_tenant_routes_require_context(tenants: TwoTenants) -> None:
    client = _app(tenants)
    r = client.get("/whoami")
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "unauthorized"


def test_tenant_comes_from_token_not_from_caller(tenants: TwoTenants) -> None:
    client = _app(tenants)
    r = client.get(
        "/whoami",
        headers={**tenants.a.headers, "X-Tenant-Id": str(tenants.b.context.tenant_id)},
        params={"tenant_id": str(tenants.b.context.tenant_id)},
    )
    assert r.status_code == 200
    assert r.json()["tenant_id"] == str(tenants.a.context.tenant_id)


def test_garbage_header_is_401(tenants: TwoTenants) -> None:
    r = _app(tenants).get("/whoami", headers={CONTEXT_HEADER: "not-a-jwt"})
    assert r.status_code == 401
