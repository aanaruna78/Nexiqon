"""G-01/G-02: deleting and exporting an organization across real services, retention sweeps, and
who may do what."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from nexiqon_config.models import ConfigObject
from nexiqon_conversation.models import Conversation
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_evaluation.models import EvalSet
from nexiqon_identity.models import Tenant
from nexiqon_metering.models import UsageDaily

from .conftest import SERVICES, Stack

PROFILE = {"conversations_days": 30, "traces_days": 7, "tool_results_days": 7, "legal_hold": False}


async def seed(stack: Stack, tenant: str = "a") -> None:
    """Something in every service for one tenant."""
    t = stack.tenants.a if tenant == "a" else stack.tenants.b
    h = stack.headers(tenant=tenant)
    engine = create_engine(stack.db.app)
    try:
        async with TenantSessionFactory(engine).scoped(
            {"tenant_id": str(t.context.tenant_id)}
        ) as s:
            s.add(Tenant(id=t.context.tenant_id, slug=f"org-{uuid.uuid4().hex[:8]}", name="Org"))
    finally:
        await engine.dispose()
    r = await stack.clients["config"].post(
        "/v1/objects",
        json={"kind": "retention_profile", "name": "short", "spec": PROFILE},
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = await stack.clients["conversation"].post(
        "/v1/conversations", json={"agent": "helper"}, headers=h
    )
    assert r.status_code == 201, r.text
    r = await stack.clients["evaluation"].post(
        "/v1/test-sets",
        json={"name": "smoke", "cases": [{"question": "How do backups work?"}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    await stack.apps["metering"].state.recorder(
        {
            "id": str(uuid.uuid4()),
            "type": "nexiqon.model-gateway.usage.recorded",
            "time": datetime.now(UTC).isoformat(),
            "nexiqontenantid": str(t.context.tenant_id),
            "data": {"agent": "helper", "cost_usd": "0.10", "input_tokens": 5},
        }
    )


async def counts(stack: Stack, tenant: uuid.UUID) -> dict[str, int]:
    engine = create_engine(stack.db.app)
    out: dict[str, int] = {}
    try:
        async with TenantSessionFactory(engine).scoped({"tenant_id": str(tenant)}) as s:
            for model in (Tenant, ConfigObject, Conversation, EvalSet, UsageDaily):
                out[model.__tablename__] = int(
                    await s.scalar(select(func.count()).select_from(model)) or 0
                )
    finally:
        await engine.dispose()
    return out


async def test_deleting_an_organization_removes_it_from_every_service(stack: Stack) -> None:
    await seed(stack, "a")
    await seed(stack, "b")
    a, b = stack.tenants.a.context.tenant_id, stack.tenants.b.context.tenant_id
    assert set((await counts(stack, a)).values()) == {1}

    await stack.ok(
        "POST",
        "/v1/lifecycle/delete",
        403,
        json={"confirm": str(a)},
        headers=stack.headers("member"),
    )
    await stack.ok("POST", "/v1/lifecycle/delete", 400, json={"confirm": str(b)})
    req = await stack.ok("POST", "/v1/lifecycle/delete", 202, json={"confirm": str(a)})
    assert req["status"] == "scheduled"
    assert datetime.fromisoformat(req["run_after"]) > datetime.now(UTC) + timedelta(minutes=50)
    await stack.ok("POST", "/v1/lifecycle/delete", 409, json={"confirm": str(a)})  # one at a time

    done = await stack.wait("delete", req["id"])  # the grace period passes (time-skipping)
    assert done["status"] == "completed", done
    steps = {s["service"]: s for s in done["steps"]}
    assert set(steps) == {*SERVICES, "governance"}
    assert all(
        s["status"] == "done" and s["detail"]["residue_check_passed"] for s in steps.values()
    )
    order = [s["service"] for s in sorted(done["steps"], key=lambda s: s["position"])]
    assert order[-3:] == ["config", "identity", "governance"]  # the organization goes last
    assert steps["identity"]["detail"]["deleted"]["tenants"] == 1
    assert set((await counts(stack, a)).values()) == {0}
    assert set((await counts(stack, b)).values()) == {1}  # the other organization is untouched
    # The certificate remains: ids, services, counts and times.
    assert (await stack.ok("GET", "/v1/lifecycle/requests"))[0]["id"] == req["id"]


async def test_a_deletion_can_be_cancelled_during_its_grace_period(stack: Stack) -> None:
    await seed(stack, "a")
    a = stack.tenants.a.context.tenant_id
    req = await stack.ok("POST", "/v1/lifecycle/delete", 202, json={"confirm": str(a)})
    out = await stack.ok("POST", f"/v1/lifecycle/requests/{req['id']}/cancel")
    assert out["status"] == "cancelled"
    assert out["steps"] == []
    assert set((await counts(stack, a)).values()) == {1}
    await stack.ok("POST", f"/v1/lifecycle/requests/{req['id']}/cancel", 409)


async def test_an_export_bundles_every_services_data(stack: Stack) -> None:
    await seed(stack, "a")
    await stack.ok("POST", "/v1/lifecycle/export", 403, headers=stack.headers("member"))
    req = await stack.ok("POST", "/v1/lifecycle/export", 202)
    done = await stack.wait("export", req["id"])
    assert done["status"] == "completed"
    assert done["downloadable"]
    r = await stack.api.get(f"/v1/lifecycle/requests/{req['id']}/download", headers=stack.headers())
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(archive.namelist()) == {f"{s}.json" for s in (*SERVICES, "governance")} | {
        "manifest.json"
    }
    config = json.loads(archive.read("config.json"))
    objects = next(a for a in config["artifacts"] if a["kind"] == "config_objects")
    assert [o["name"] for o in objects["data"]] == ["short"]
    conversations = json.loads(archive.read("conversation.json"))
    assert next(a for a in conversations["artifacts"] if a["kind"] == "conversations")["rows"] == 1
    identity = json.loads(archive.read("identity.json"))
    assert "secret_hash" not in json.dumps(identity)  # secrets never leave
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["services"]["config"]
    # Parts were assembled and removed: only the archive is stored.
    assert [k for k in stack.blobs.objects if "/exports/" in k] == [
        f"t/{stack.tenants.a.context.tenant_id}/exports/{req['id']}.zip"
    ]


async def test_lifecycle_endpoints_answer_only_governance(stack: Stack) -> None:
    for name in ("config", "conversation", "identity"):
        r = await stack.clients[name].post("/v1/_lifecycle/delete", headers=stack.headers("owner"))
        assert r.status_code == 403, (name, r.text)
    r = await stack.clients["config"].get("/openapi.json")
    assert "/v1/_lifecycle/delete" not in r.json()["paths"]  # not part of the public contract


async def test_retention_purges_what_has_expired_and_records_it(stack: Stack) -> None:
    await seed(stack, "a")
    a = stack.tenants.a.context.tenant_id
    engine = create_engine(stack.db.app)
    try:
        async with TenantSessionFactory(engine).scoped({"tenant_id": str(a)}) as s:
            await s.execute(
                update(Conversation).values(retain_until=datetime.now(UTC) - timedelta(days=1))
            )
    finally:
        await engine.dispose()
    await stack.ok("POST", "/v1/retention/runs", 403, headers=stack.headers("member"))
    run = await stack.ok("POST", "/v1/retention/runs", 202, headers=stack.headers("admin"))
    await stack.env.client.get_workflow_handle(f"{a}:retention:{run['id']}").result()
    runs: list[dict[str, Any]] = await stack.ok("GET", "/v1/retention/runs")
    done = runs[0]
    assert done["status"] == "completed", done
    assert done["purged"]["conversation"] == {"conversations": 1}
    assert done["policy"]["conversations_days"] == 365  # the tenant's "standard" profile
    assert (await counts(stack, a))["conversations"] == 0
