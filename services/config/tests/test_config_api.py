"""Config registry end to end on real Postgres: lifecycle, promotion, floors, snapshots, isolation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from nexiqon_core.db import create_engine
from nexiqon_core.signing import verify
from nexiqon_core.testing import Actor, TwoTenants

ClientFactory = Callable[..., TestClient]
PACK_YAML = (
    Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml"
).read_text()


pytestmark = pytest.mark.integration

AGENT = {
    "pack": {"name": "saas-knowledge-assistant"},
    "display_name": "Acme Help",
    "knowledge": {"collections": ["product-docs"]},
    "guardrails": {"max_answer_tokens": 600},
}


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def bootstrap(c: TestClient, a: Actor, agent: dict[str, Any] | None = None) -> None:
    """Import + publish + deploy the pack to dev, then create, publish and deploy an agent to dev."""
    ok(
        c.post(
            "/v1/packs/import",
            content=PACK_YAML,
            headers={**a.headers, "content-type": "application/yaml"},
        ),
        201,
    )
    ok(
        c.post(
            "/v1/objects/domain_pack/saas-knowledge-assistant/versions/1/publish", headers=a.headers
        )
    )
    ok(
        c.put(
            "/v1/objects/domain_pack/saas-knowledge-assistant/deployments/dev",
            json={"version": 1},
            headers=a.headers,
        )
    )
    ok(
        c.post(
            "/v1/objects",
            json={"kind": "agent", "name": "support", "spec": agent or AGENT},
            headers=a.headers,
        ),
        201,
    )
    ok(c.post("/v1/objects/agent/support/versions/1/publish", headers=a.headers))
    ok(c.put("/v1/objects/agent/support/deployments/dev", json={"version": 1}, headers=a.headers))


def test_kinds_expose_schemas_for_generated_forms(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    kinds = ok(make_client(t).get("/v1/kinds", headers=t.a.headers))
    by_kind = {k["kind"]: k for k in kinds}
    assert by_kind["agent"]["schema"]["properties"]["display_name"]["type"] == "string"
    assert "x-ui" in str(by_kind["model_profile"]["schema"])


def test_resolution_layers_profiles_and_provenance(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    r = ok(c.get("/v1/resolve/agents/support?environment=dev", headers=t.a.headers))
    cfg, prov = r["config"], r["provenance"]
    assert (
        cfg["guardrails"]["max_answer_tokens"] == 600
    )  # agent beats pack (700) and platform (900)
    assert prov["guardrails.max_answer_tokens"] == "agent:support@1"
    assert cfg["behaviour"]["tone"] == "friendly"  # from pack agent_defaults
    assert prov["behaviour.tone"].startswith("pack:saas-knowledge-assistant@1")
    assert cfg["guardrails"]["pii_redaction"] is True
    assert cfg["model"]["data_policy"]["location"] == "cloud"  # built-in profile inlined
    assert prov["model"] == "builtin:model_profile:cloud-frontier"
    assert r["graph"]["entry"] == "route"
    assert r["versions"] == {"agent": 1, "pack": 1}


def test_published_versions_are_immutable_even_in_the_database(
    make_client: ClientFactory, config_db: Any
) -> None:
    import asyncio

    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    assert (
        c.post("/v1/objects/agent/support/versions/1/publish", headers=t.a.headers).status_code
        == 409
    )

    async def tamper() -> None:
        engine = create_engine(config_db.owner)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE config.config_versions SET notes = 'x' WHERE status = 'published'")
                )
        finally:
            await engine.dispose()

    with pytest.raises(Exception, match="immutable"):
        asyncio.run(tamper())


def test_drafts_versions_and_diff(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    v2 = {**AGENT, "display_name": "Acme Support", "guardrails": {"max_answer_tokens": 400}}
    assert (
        ok(c.put("/v1/objects/agent/support/draft", json={"spec": v2}, headers=t.a.headers))[
            "version"
        ]
        == 2
    )
    again = ok(
        c.put(
            "/v1/objects/agent/support/draft",
            json={"spec": v2, "notes": "tweak"},
            headers=t.a.headers,
        )
    )
    assert again["version"] == 2  # one draft at a time, edited in place
    changes = ok(c.get("/v1/objects/agent/support/diff?from=1&to=2", headers=t.a.headers))[
        "changes"
    ]
    assert {
        "op": "replace",
        "path": "display_name",
        "old": "Acme Help",
        "new": "Acme Support",
    } in changes
    bad = c.put(
        "/v1/objects/agent/support/draft", json={"spec": {"display_name": "x"}}, headers=t.a.headers
    )
    assert bad.status_code == 422
    assert bad.json()["errors"]


def test_promotion_order_and_rollback(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    assert (
        c.put(
            "/v1/objects/agent/support/deployments/prod", json={"version": 1}, headers=t.a.headers
        ).status_code
        == 409
    )
    for env in ("staging", "prod"):
        ok(
            c.put(
                f"/v1/objects/domain_pack/saas-knowledge-assistant/deployments/{env}",
                json={"version": 1},
                headers=t.a.headers,
            )
        )
        ok(
            c.put(
                f"/v1/objects/agent/support/deployments/{env}",
                json={"version": 1},
                headers=t.a.headers,
            )
        )

    ok(
        c.put(
            "/v1/objects/agent/support/draft",
            json={"spec": {**AGENT, "display_name": "Acme v2"}},
            headers=t.a.headers,
        )
    )
    ok(c.post("/v1/objects/agent/support/versions/2/publish", headers=t.a.headers))
    ok(c.put("/v1/objects/agent/support/deployments/dev", json={"version": 2}, headers=t.a.headers))
    ok(
        c.put(
            "/v1/objects/agent/support/deployments/dev",
            json={"version": 1, "reason": "rollback"},
            headers=t.a.headers,
        )
    )
    history = ok(c.get("/v1/objects/agent/support/deployments/history", headers=t.a.headers))
    assert [(h["environment"], h["from_version"], h["to_version"]) for h in history][-2:] == [
        ("dev", 1, 2),
        ("dev", 2, 1),
    ]
    obj = ok(c.get("/v1/objects/agent/support", headers=t.a.headers))
    assert obj["deployments"] == {"dev": 1, "staging": 1, "prod": 1}
    unpublished = c.put(
        "/v1/objects/agent/support/deployments/dev", json={"version": 9}, headers=t.a.headers
    )
    assert unpublished.status_code == 404


def test_platform_floors_block_loosening(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    unsafe = {**AGENT, "guardrails": {"pii_redaction": False}}
    ok(c.put("/v1/objects/agent/support/draft", json={"spec": unsafe}, headers=t.a.headers))
    r = c.post("/v1/objects/agent/support/versions/2/publish", headers=t.a.headers)
    assert r.status_code == 409
    assert "guardrails.pii_redaction" in r.json()["detail"]


def test_tenant_floors_are_owner_only_and_enforced_on_deploy(make_client: ClientFactory) -> None:
    owner = TwoTenants.create(roles=frozenset({"owner"}))
    c = make_client(owner)
    bootstrap(c, owner.a)
    floors = {
        "rules": [
            {
                "path": "model.data_policy.location",
                "op": "equals",
                "value": "on_prem",
                "reason": "regulated",
            }
        ]
    }

    admin = TwoTenants(
        settings=owner.settings, issuer=owner.issuer, a=_as(owner, "admin"), b=owner.b
    )
    assert (
        make_client(admin)
        .post(
            "/v1/objects",
            json={"kind": "security_floors", "name": "default", "spec": floors},
            headers=admin.a.headers,
        )
        .status_code
        == 403
    )

    ok(
        c.post(
            "/v1/objects",
            json={"kind": "security_floors", "name": "default", "spec": floors},
            headers=owner.a.headers,
        ),
        201,
    )
    ok(c.post("/v1/objects/security_floors/default/versions/1/publish", headers=owner.a.headers))
    # Deploying the floor would break the live agent (cloud model): refused, nothing changes.
    r = c.put(
        "/v1/objects/security_floors/default/deployments/dev",
        json={"version": 1},
        headers=owner.a.headers,
    )
    assert r.status_code == 409
    assert "on_prem" in r.json()["detail"]
    assert (
        ok(c.get("/v1/objects/security_floors/default", headers=owner.a.headers))["deployments"]
        == {}
    )
    # Switch the agent to an on-prem profile first; then the floor deploys.
    ok(
        c.put(
            "/v1/objects/agent/support/draft",
            json={"spec": {**AGENT, "model_profile": "on-prem-standard"}},
            headers=owner.a.headers,
        )
    )
    ok(c.post("/v1/objects/agent/support/versions/2/publish", headers=owner.a.headers))
    ok(
        c.put(
            "/v1/objects/agent/support/deployments/dev",
            json={"version": 2},
            headers=owner.a.headers,
        )
    )
    ok(
        c.put(
            "/v1/objects/security_floors/default/deployments/dev",
            json={"version": 1},
            headers=owner.a.headers,
        )
    )
    # And now rolling the agent back to the cloud version is refused.
    back = c.put(
        "/v1/objects/agent/support/deployments/dev", json={"version": 1}, headers=owner.a.headers
    )
    assert back.status_code == 409


def _as(t: TwoTenants, role: str) -> Actor:
    from dataclasses import replace

    ctx = replace(t.a.context, roles=frozenset({role}), actor_id=f"{role}-user")
    return Actor(context=ctx, token=t.issuer.issue(ctx))


def test_member_can_read_but_not_write(make_client: ClientFactory) -> None:
    owner = TwoTenants.create()
    c = make_client(owner)
    bootstrap(c, owner.a)
    member = _as(owner, "member")
    assert c.get("/v1/objects/agent/support", headers=member.headers).status_code == 200
    assert (
        c.put(
            "/v1/objects/agent/support/draft", json={"spec": AGENT}, headers=member.headers
        ).status_code
        == 403
    )


def test_signed_snapshot_with_etag(make_client: ClientFactory, snapshot_public_key: str) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    r = c.get("/v1/snapshots/dev", headers=t.a.headers)
    body = ok(r)
    claims = verify(body["signature"], {"snap-1": snapshot_public_key})
    assert claims["digest"] == body["digest"] == r.headers["ETag"].strip('"')
    assert claims["tenant_id"] == str(t.a.context.tenant_id)
    assert set(body["snapshot"]["agents"]) == {"support"}
    assert {o["kind"] for o in body["snapshot"]["objects"]} == {"agent", "domain_pack"}
    assert (
        c.get(
            "/v1/snapshots/dev", headers={**t.a.headers, "If-None-Match": r.headers["ETag"]}
        ).status_code
        == 304
    )
    jwks = ok(c.get("/.well-known/jwks.json"))
    assert jwks["keys"][0]["kid"] == "snap-1"


def test_pack_export_round_trips(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    from nexiqon_config.packs import parse_pack

    exported = c.get("/v1/packs/saas-knowledge-assistant/export", headers=t.a.headers)
    assert exported.headers["content-type"].startswith("application/yaml")
    assert parse_pack(exported.text) == parse_pack(PACK_YAML)


def test_tenants_are_isolated(make_client: ClientFactory) -> None:
    t = TwoTenants.create()
    c = make_client(t)
    bootstrap(c, t.a)
    assert c.get("/v1/objects", headers=t.b.headers).json() == []
    assert c.get("/v1/objects/agent/support", headers=t.b.headers).status_code == 404
    assert c.get("/v1/resolve/agents/support", headers=t.b.headers).status_code == 404
    assert (
        c.put(
            "/v1/objects/agent/support/deployments/dev", json={"version": 1}, headers=t.b.headers
        ).status_code
        == 404
    )
    snap = ok(c.get("/v1/snapshots/dev", headers=t.b.headers))
    assert snap["snapshot"]["objects"] == []
    # Same names are independent per tenant.
    bootstrap(c, t.b)
    assert ok(c.get("/v1/objects/agent/support", headers=t.b.headers))["deployments"] == {"dev": 1}
