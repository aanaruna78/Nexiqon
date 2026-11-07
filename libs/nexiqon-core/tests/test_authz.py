import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Resource, StaticAuthorizer, _match, require_permission
from nexiqon_core.settings import CoreSettings
from nexiqon_core.testing import TwoTenants


@pytest.mark.parametrize(
    ("pattern", "action", "ok"),
    [
        ("**", "identity.members.write", True),
        ("identity.**", "identity.members.write", True),
        ("identity.*", "identity.members.write", False),
        ("identity.*.read", "identity.members.read", True),
        ("**.read", "config.agent.read", True),
        ("**.read", "config.agent.write", False),
        ("identity.members.write", "identity.members.writex", False),
    ],
)
def test_glob_semantics_match_opa(pattern: str, action: str, ok: bool) -> None:
    assert _match(pattern, action) is ok


async def test_static_authorizer_denies_cross_tenant() -> None:
    t = TwoTenants.create()
    authz = StaticAuthorizer({"admin": ["**"]})
    same = await authz.decide(t.a.context, t.a.token, "x.y.z", Resource(type="x"))
    other = await authz.decide(
        t.a.context, t.a.token, "x.y.z", Resource(type="x", tenant_id=str(t.b.context.tenant_id))
    )
    assert same.allow
    assert not other.allow


def test_require_permission_enforces_role() -> None:
    admins = TwoTenants.create(roles=frozenset({"admin"}))
    members = TwoTenants.create(roles=frozenset({"member"}))
    router = APIRouter()

    @router.post("/things", dependencies=[require_permission("demo.things.write", "thing")])
    async def create() -> dict[str, bool]:
        return {"ok": True}

    def client(t: TwoTenants) -> TestClient:
        settings = CoreSettings(service_name="demo", context_token=t.settings, log_json=False)
        app = create_service_app(
            name="demo",
            version="0",
            plane="data",
            settings=settings,
            tenant_routers=[router],
            authorizer=StaticAuthorizer({"admin": ["demo.**"], "member": ["**.read"]}),
        )
        return TestClient(app)

    assert client(admins).post("/things", headers=admins.a.headers).status_code == 200
    r = client(members).post("/things", headers=members.a.headers)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
