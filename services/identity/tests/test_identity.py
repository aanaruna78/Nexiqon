"""End-to-end identity behaviour on real Postgres + migrations + RLS."""

from __future__ import annotations

import uuid

import pytest

from nexiqon_core.tenancy import CONTEXT_HEADER
from nexiqon_identity.testing import Env, FakeIdp, slug

pytestmark = pytest.mark.integration


def h(token: str) -> dict[str, str]:
    return {CONTEXT_HEADER: token}


# ------------------------------------------------------------------ sign-up and context tokens


def test_signup_makes_owner_and_context_token_carries_tenant(env: Env) -> None:
    s = slug()
    _, token = env.signup("alice", "alice@a.example.com", s)
    ctx = env.ctx(token)
    assert ctx.roles == frozenset({"owner"})
    assert ctx.actor_type == "user"
    tenant = env.client.get("/v1/tenant", headers=h(token)).json()
    assert tenant["slug"] == s
    assert str(ctx.tenant_id) == tenant["id"]


def test_duplicate_slug_is_conflict(env: Env) -> None:
    s = slug()
    env.signup("u1", "u1@a.example.com", s)
    r = env.client.post(
        "/v1/session/tenants",
        json={"name": "Xx", "slug": s},
        headers={"Authorization": f"Bearer {env.oidc.user('u2', 'u2@a.test')}"},
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("case", "status"),
    [("no-credentials", 401), ("untrusted-issuer", 401), ("expired", 401), ("garbage", 401)],
)
def test_bad_credentials_rejected(env: Env, case: str, status: int) -> None:
    headers = {
        "no-credentials": {},
        "untrusted-issuer": {
            "Authorization": f"Bearer {FakeIdp('https://evil.test').user('x', 'x@e.test')}"
        },
        "expired": {"Authorization": f"Bearer {env.oidc.token('x', ttl=-60)}"},
        "garbage": {"Authorization": "Bearer not.a.jwt"},
    }[case]
    assert env.client.post("/internal/ext-authz/x", headers=headers).status_code == status


def test_non_member_is_forbidden_without_revealing_tenant(env: Env) -> None:
    s = slug()
    env.signup("owner-x", "ox@a.example.com", s)
    stranger = env.oidc.user("stranger", "s@b.example.com")
    for selector in (s, str(uuid.uuid4())):
        r = env.client.post(
            "/internal/ext-authz/x",
            headers={"Authorization": f"Bearer {stranger}", "X-Nexiqon-Tenant": selector},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Not a member of this tenant"


def test_admins_need_mfa(env: Env) -> None:
    s = slug()
    env.signup("mfa-owner", "mo@a.example.com", s)
    no_mfa = env.oidc.user("mfa-owner", "mo@a.example.com", mfa=False)
    r = env.client.post(
        "/internal/ext-authz/x",
        headers={"Authorization": f"Bearer {no_mfa}", "X-Nexiqon-Tenant": s},
    )
    assert r.status_code == 403
    assert "Multi-factor" in r.json()["detail"]


def test_several_tenants_require_selection(env: Env) -> None:
    idp_token, _ = env.signup("multi", "multi@a.example.com", slug())
    env.client.post(
        "/v1/session/tenants",
        json={"name": "Second", "slug": slug()},
        headers={"Authorization": f"Bearer {idp_token}"},
    )
    r = env.client.post("/internal/ext-authz/x", headers={"Authorization": f"Bearer {idp_token}"})
    assert r.status_code == 400
    memberships = env.client.get(
        "/v1/session/memberships", headers={"Authorization": f"Bearer {idp_token}"}
    ).json()
    assert len(memberships) == 2


def test_jwks_verifies_issued_tokens(env: Env) -> None:
    import jwt

    _, token = env.signup("jwks", "jwks@a.example.com", slug())
    key = jwt.PyJWKSet.from_dict(env.client.get("/.well-known/jwks.json").json()).keys[0]
    claims = jwt.decode(token, key.key, algorithms=["ES256"], audience="nexiqon-services")
    assert claims["rol"] == ["owner"]


# ------------------------------------------------------------------ invitations and roles


def test_invite_accept_with_verified_email_only(env: Env) -> None:
    s = slug()
    _, owner = env.signup("inv-owner", "io@a.example.com", s)
    r = env.client.post(
        "/v1/members", json={"email": "Bob@B.example.com", "role": "editor"}, headers=h(owner)
    )
    assert r.status_code == 201
    assert r.json()["status"] == "invited"

    unverified = env.oidc.user("bob", "bob@b.example.com", verified=False)
    r = env.client.post(
        "/internal/ext-authz/x",
        headers={"Authorization": f"Bearer {unverified}", "X-Nexiqon-Tenant": s},
    )
    assert r.status_code == 403

    bob = env.context(env.oidc.user("bob", "bob@b.example.com"), s)
    assert env.ctx(bob).roles == frozenset({"editor"})
    members = env.client.get("/v1/members", headers=h(owner)).json()
    assert {m["email"]: m["status"] for m in members}["bob@b.example.com"] == "active"


def test_member_cannot_manage_members(env: Env) -> None:
    s = slug()
    _, owner = env.signup("rm-owner", "rmo@a.example.com", s)
    env.client.post(
        "/v1/members", json={"email": "m@m.example.com", "role": "member"}, headers=h(owner)
    )
    member = env.context(env.oidc.user("m", "m@m.example.com"), s)
    assert env.client.get("/v1/members", headers=h(member)).status_code == 200
    r = env.client.post("/v1/members", json={"email": "z@z.example.com"}, headers=h(member))
    assert r.status_code == 403


def test_owner_rules(env: Env) -> None:
    s = slug()
    _, owner = env.signup("own", "own@a.example.com", s)
    env.client.post(
        "/v1/members", json={"email": "adm@a.example.com", "role": "admin"}, headers=h(owner)
    )
    admin = env.context(env.oidc.user("adm", "adm@a.example.com"), s)
    members = {m["email"]: m for m in env.client.get("/v1/members", headers=h(owner)).json()}

    # Admins cannot create owners or touch the owner.
    assert (
        env.client.post(
            "/v1/members", json={"email": "o2@a.example.com", "role": "owner"}, headers=h(admin)
        ).status_code
        == 403
    )
    owner_id = members["own@a.example.com"]["id"]
    assert (
        env.client.patch(
            f"/v1/members/{owner_id}", json={"role": "member"}, headers=h(admin)
        ).status_code
        == 403
    )
    # The last owner cannot demote or remove themself.
    assert (
        env.client.patch(
            f"/v1/members/{owner_id}", json={"role": "admin"}, headers=h(owner)
        ).status_code
        == 409
    )
    assert env.client.delete(f"/v1/members/{owner_id}", headers=h(owner)).status_code == 409
    # Owner can promote the admin; then the original owner may step down.
    admin_id = members["adm@a.example.com"]["id"]
    assert (
        env.client.patch(
            f"/v1/members/{admin_id}", json={"role": "owner"}, headers=h(owner)
        ).status_code
        == 200
    )
    assert (
        env.client.patch(
            f"/v1/members/{owner_id}", json={"role": "admin"}, headers=h(owner)
        ).status_code
        == 200
    )


# ------------------------------------------------------------------ cross-tenant isolation


def test_tenants_cannot_see_or_change_each_other(env: Env) -> None:
    _, a = env.signup("iso-a", "a@iso.example.com", slug())
    _, b = env.signup("iso-b", "b@iso.example.com", slug())
    env.client.post("/v1/members", json={"email": "x@iso.example.com"}, headers=h(b))
    env.client.post("/v1/groups", json={"name": "support"}, headers=h(b))
    key_b = env.client.post(
        "/v1/api-keys", json={"name": "b", "kind": "server"}, headers=h(b)
    ).json()

    b_members = env.client.get("/v1/members", headers=h(b)).json()
    a_members = env.client.get("/v1/members", headers=h(a)).json()
    assert {m["email"] for m in a_members} == {"a@iso.example.com"}
    assert env.client.get("/v1/groups", headers=h(a)).json() == []
    assert env.client.get("/v1/api-keys", headers=h(a)).json() == []

    target = b_members[0]["id"]
    assert (
        env.client.patch(f"/v1/members/{target}", json={"role": "admin"}, headers=h(a)).status_code
        == 404
    )
    assert env.client.delete(f"/v1/members/{target}", headers=h(a)).status_code == 404
    assert env.client.delete(f"/v1/api-keys/{key_b['id']}", headers=h(a)).status_code == 404
    assert env.client.get("/v1/tenant", headers=h(a)).json()["id"] == str(env.ctx(a).tenant_id)


# ------------------------------------------------------------------ groups


def test_groups_flow_into_context_token(env: Env) -> None:
    s = slug()
    _, owner = env.signup("grp", "grp@a.example.com", s)
    me = env.client.get("/v1/members", headers=h(owner)).json()[0]["id"]
    group = env.client.post("/v1/groups", json={"name": "finance"}, headers=h(owner)).json()
    assert (
        env.client.put(f"/v1/groups/{group['id']}/members/{me}", headers=h(owner)).status_code
        == 204
    )
    fresh = env.context(env.oidc.user("grp", "grp@a.example.com"), s)
    assert env.ctx(fresh).groups == frozenset({"finance"})


# ------------------------------------------------------------------ API keys


def test_server_key_lifecycle(env: Env) -> None:
    _, owner = env.signup("keys", "keys@a.example.com", slug())
    created = env.client.post(
        "/v1/api-keys", json={"name": "ci", "kind": "server", "roles": ["editor"]}, headers=h(owner)
    )
    assert created.status_code == 201
    secret = created.json()["secret"]
    assert "secret" not in env.client.get("/v1/api-keys", headers=h(owner)).json()[0]

    ctx = env.ctx(env.context(secret))
    assert ctx.actor_type == "api_key"
    assert ctx.roles == frozenset({"editor"})
    assert ctx.tenant_id == env.ctx(owner).tenant_id

    assert (
        env.client.delete(f"/v1/api-keys/{created.json()['id']}", headers=h(owner)).status_code
        == 204
    )
    r = env.client.post("/internal/ext-authz/x", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 401


def test_key_role_and_origin_rules(env: Env) -> None:
    _, owner = env.signup("wkeys", "wk@a.example.com", slug())
    assert (
        env.client.post(
            "/v1/api-keys",
            json={"name": "x", "kind": "server", "roles": ["admin"]},
            headers=h(owner),
        ).status_code
        == 400
    )
    assert (
        env.client.post(
            "/v1/api-keys", json={"name": "w", "kind": "widget"}, headers=h(owner)
        ).status_code
        == 400
    )
    widget = env.client.post(
        "/v1/api-keys",
        json={"name": "w", "kind": "widget", "allowed_origins": ["https://docs.a.test"]},
        headers=h(owner),
    ).json()["secret"]
    visitor = "v" * 30
    ctx = env.ctx(env.context(widget, origin="https://docs.a.test", visitor=visitor))
    assert (ctx.actor_type, ctx.roles) == ("widget", frozenset({"end_user"}))
    # Each website visitor is a separate actor, so visitors never share conversations.
    other = env.ctx(env.context(widget, origin="https://docs.a.test", visitor="w" * 30))
    assert ctx.actor_id.endswith(visitor)
    assert other.actor_id != ctx.actor_id
    no_visitor = env.client.post(
        "/internal/ext-authz/x",
        headers={"Authorization": f"Bearer {widget}", "Origin": "https://docs.a.test"},
    )
    assert no_visitor.status_code == 401
    r = env.client.post(
        "/internal/ext-authz/x",
        headers={"Authorization": f"Bearer {widget}", "Origin": "https://evil.test"},
    )
    assert r.status_code == 403
    tampered = widget[:-4] + ("AAAA" if not widget.endswith("AAAA") else "BBBB")
    assert (
        env.client.post(
            "/internal/ext-authz/x",
            headers={"Authorization": f"Bearer {tampered}", "Origin": "https://docs.a.test"},
        ).status_code
        == 401
    )


# ------------------------------------------------------------------ Clerk


def test_clerk_org_sync_and_login(env: Env) -> None:
    org = f"org_{uuid.uuid4().hex[:12]}"
    assert (
        env.webhook(
            {"type": "organization.created", "data": {"id": org, "name": "Acme", "slug": "acme"}}
        ).status_code
        == 200
    )
    membership = {
        "type": "organizationMembership.created",
        "data": {
            "role": "org:admin",
            "organization": {"id": org, "name": "Acme"},
            "public_user_data": {"user_id": "user_clerk_1", "identifier": "ceo@acme.example.com"},
        },
    }
    assert env.webhook(membership).json() == {"status": "processed"}
    assert env.webhook(membership).status_code == 200  # idempotent

    clerk_token = env.clerk.token("user_clerk_1", org_id=org, fva=[3, 3], azp="https://studio.test")
    ctx = env.ctx(env.context(clerk_token))
    assert ctx.roles == frozenset({"owner"})  # first org admin becomes owner

    wrong_app = env.clerk.token("user_clerk_1", org_id=org, fva=[3, 3], azp="https://evil.test")
    assert (
        env.client.post(
            "/internal/ext-authz/x", headers={"Authorization": f"Bearer {wrong_app}"}
        ).status_code
        == 401
    )
    no_mfa = env.clerk.token("user_clerk_1", org_id=org, fva=[3, -1], azp="https://studio.test")
    assert (
        env.client.post(
            "/internal/ext-authz/x", headers={"Authorization": f"Bearer {no_mfa}"}
        ).status_code
        == 403
    )


def test_clerk_webhook_signature_required(env: Env) -> None:
    event = {"type": "organization.created", "data": {"id": "org_forged", "name": "Forged"}}
    other = "whsec_" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="
    assert env.webhook(event, secret=other).status_code == 401


# ------------------------------------------------------------------ QA regressions (2026-11-08)


def test_qa01_expired_key_is_refused_even_when_cached(env: Env) -> None:
    import time
    from datetime import UTC, datetime, timedelta

    _, owner = env.signup("qa01", "qa01@a.example.com", slug())
    env.client.app.state.access.policy.cache_seconds = 30  # type: ignore[attr-defined]
    expires = (datetime.now(UTC) + timedelta(seconds=2)).isoformat()
    created = env.client.post(
        "/v1/api-keys",
        json={"name": "short", "kind": "server", "expires_at": expires},
        headers=h(owner),
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    headers = {"Authorization": f"Bearer {secret}"}
    assert (
        env.client.post("/internal/ext-authz/x", headers=headers).status_code == 200
    )  # cached now
    time.sleep(2.5)
    assert env.client.post("/internal/ext-authz/x", headers=headers).status_code == 401


def test_qa01_unexpiring_key_is_still_cached(env: Env) -> None:
    _, owner = env.signup("qa01b", "qa01b@a.example.com", slug())
    access = env.client.app.state.access  # type: ignore[attr-defined]
    access.policy.cache_seconds = 30
    secret = env.client.post(
        "/v1/api-keys", json={"name": "k", "kind": "server"}, headers=h(owner)
    ).json()["secret"]
    headers = {"Authorization": f"Bearer {secret}"}
    first = env.client.post("/internal/ext-authz/x", headers=headers).headers[CONTEXT_HEADER]
    second = env.client.post("/internal/ext-authz/x", headers=headers).headers[CONTEXT_HEADER]
    assert first == second  # served from cache, not re-minted


def test_qa02_expiry_needs_a_timezone(env: Env) -> None:
    _, owner = env.signup("qa02", "qa02@a.example.com", slug())
    naive = env.client.post(
        "/v1/api-keys",
        json={"name": "n", "kind": "server", "expires_at": "2099-01-01T00:00:00"},
        headers=h(owner),
    )
    assert naive.status_code == 422
    assert naive.json()["code"] == "validation_failed"
    past = env.client.post(
        "/v1/api-keys",
        json={"name": "p", "kind": "server", "expires_at": "2000-01-01T00:00:00Z"},
        headers=h(owner),
    )
    assert past.status_code == 400
    aware = env.client.post(
        "/v1/api-keys",
        json={"name": "a", "kind": "server", "expires_at": "2099-01-01T00:00:00+05:30"},
        headers=h(owner),
    )
    assert aware.status_code == 201
