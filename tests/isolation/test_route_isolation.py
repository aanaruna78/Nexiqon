"""Cross-service isolation harness (PL-03).

For every route of every service in deploy/groups.yaml:
* a route reachable without a tenant context must be on the reviewed PUBLIC allowlist below;
* every other route must reject a request with no context token, and one signed by an unknown key.

Data-level cross-tenant checks (tenant A cannot read or change tenant B's records) live in each
service's own tests and run against real Postgres + RLS.
"""

from __future__ import annotations

import importlib
import re
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from nexiqon_core.directory import Topology, module_for
from nexiqon_core.settings import ContextTokenSettings
from nexiqon_core.tenancy import CONTEXT_HEADER, ContextTokenIssuer, TenantContext
from nexiqon_core.testing import TEST_KEY_ID, TwoTenants, make_keypair

ROOT = Path(__file__).resolve().parents[2]
SERVICES = [
    s for g in Topology.load(ROOT / "deploy" / "groups.yaml").groups.values() for s in g.services
]
OPS = {"/healthz", "/readyz", "/meta"}

# Reviewed routes that are reachable without a tenant context. Adding one needs a security review.
PUBLIC: dict[str, set[str]] = {
    "identity": {
        "/.well-known/jwks.json",  # public keys only
        "/internal/ext-authz/{path:path}",  # gateway check; never routed by the gateway
        "/v1/session/memberships",  # authenticates the IdP token itself
        "/v1/session/tenants",  # authenticates the IdP token itself
        "/v1/webhooks/clerk",  # Svix signature verified
    },
}


def build_app(service: str, tenants: TwoTenants) -> FastAPI:
    module = module_for(service)
    settings_cls = importlib.import_module(f"{module}.settings").ServiceSettings
    create_app = importlib.import_module(f"{module}.main").create_app
    app: FastAPI = create_app(settings_cls(context_token=tenants.settings, log_json=False))
    return app


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda m: "x" if ":path" in m.group(0) else str(uuid.uuid4()), path)


def forged_token(tenants: TwoTenants) -> str:
    private_pem, _ = make_keypair()  # not the key the service trusts
    issuer = ContextTokenIssuer(private_pem, TEST_KEY_ID, ContextTokenSettings())
    return issuer.issue(
        TenantContext(
            tenant_id=tenants.a.context.tenant_id,
            actor_id="mallory",
            actor_type="user",
            roles=frozenset({"owner"}),
        )
    )


@pytest.mark.parametrize("service", SERVICES)
def test_public_routes_are_reviewed(service: str) -> None:
    app = build_app(service, TwoTenants.create())
    unexpected = set(app.state.public_paths) - OPS - PUBLIC.get(service, set())
    assert not unexpected, (
        f"{service}: unreviewed routes without tenant context: {sorted(unexpected)}"
    )


@pytest.mark.parametrize("service", SERVICES)
def test_tenant_routes_reject_missing_and_forged_context(service: str) -> None:
    tenants = TwoTenants.create()
    app = build_app(service, tenants)
    forged = forged_token(tenants)
    failures: list[str] = []
    with TestClient(app) as client:
        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path in app.state.public_paths:
                continue
            url = concrete(route.path)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                for label, headers in (("missing", {}), ("forged", {CONTEXT_HEADER: forged})):
                    status = client.request(method, url, headers=headers, json={}).status_code
                    if status != 401:
                        failures.append(f"{method} {route.path} with {label} context -> {status}")
    assert not failures, f"{service}:\n" + "\n".join(failures)
