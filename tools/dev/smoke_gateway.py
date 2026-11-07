"""End-to-end smoke test of the local stack through the gateway (make dev-up PROFILES=platform,apps).

    uv run python tools/dev/smoke_gateway.py

Logs in to the dev Keycloak realm, creates a tenant, mints an API key and exercises the
gateway's security behaviour. Exits non-zero on the first failure.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import httpx
import jwt

GATEWAY = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[2]
KEYCLOAK_TOKEN_URL = "http://localhost:8080/realms/nexiqon/protocol/openid-connect/token"  # noqa: S105 - a URL, not a secret


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if not ok else ""))
    if not ok:
        sys.exit(1)


def keycloak_token() -> str:
    for _ in range(60):
        try:
            r = httpx.post(
                KEYCLOAK_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "client_id": "nexiqon-studio",
                    "username": "dev",
                    "password": "dev-password",
                    "scope": "openid email profile",
                },
                timeout=5,
            )
            if r.status_code == 200:
                return str(r.json()["access_token"])
        except httpx.HTTPError:
            pass
        time.sleep(2)
    sys.exit("Keycloak did not issue a token")


def main() -> int:
    with httpx.Client(base_url=GATEWAY, timeout=10) as gw:
        for _ in range(90):  # wait until identity answers through the gateway
            try:
                if gw.get("/identity/.well-known/jwks.json").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        token = keycloak_token()
        auth = {"Authorization": f"Bearer {token}"}
        slug = f"smoke-{uuid.uuid4().hex[:8]}"

        r = gw.post(
            "/identity/v1/session/tenants", json={"name": "Smoke Test", "slug": slug}, headers=auth
        )
        check("self-serve tenant creation", r.status_code == 201, r.text)

        r = gw.get("/identity/v1/tenant", headers={**auth, "X-Nexiqon-Tenant": slug})
        check(
            "tenant API through gateway with IdP token",
            r.status_code == 200 and r.json()["slug"] == slug,
            r.text,
        )

        r = gw.get("/identity/v1/members", headers={**auth, "X-Nexiqon-Tenant": slug})
        check(
            "owner listed as member",
            r.status_code == 200 and r.json()[0]["role"] == "owner",
            r.text,
        )

        r = gw.post(
            "/identity/v1/api-keys",
            json={"name": "smoke", "kind": "server", "roles": ["member"]},
            headers={**auth, "X-Nexiqon-Tenant": slug},
        )
        check("API key created", r.status_code == 201, r.text)
        key = r.json()["secret"]
        r = gw.get("/identity/v1/members", headers={"Authorization": f"Bearer {key}"})
        check("API key (member role) can read members", r.status_code == 200, r.text)
        r = gw.post(
            "/identity/v1/members",
            json={"email": "x@example.com"},
            headers={"Authorization": f"Bearer {key}"},
        )
        check("API key (member role) cannot invite", r.status_code == 403, r.text)

        r = gw.get("/identity/v1/tenant", headers={"X-Nexiqon-Context": "forged.token.value"})
        check(
            "forged context header without credentials is rejected",
            r.status_code == 401,
            r.status_code,
        )

        r = gw.get("/identity/v1/tenant", headers={**auth, "X-Nexiqon-Tenant": "does-not-exist"})
        check("unknown tenant is forbidden", r.status_code == 403, r.status_code)

        # ---- config: Domain Pack -> agent -> resolve -> signed snapshot
        tenant = {**auth, "X-Nexiqon-Tenant": slug}
        base = "/config/v1/objects"
        pack = (ROOT / "packs/saas-knowledge-assistant/pack.yaml").read_text()
        r = gw.post(
            "/config/v1/packs/import",
            content=pack,
            headers={**tenant, "content-type": "application/yaml"},
        )
        check("domain pack imported", r.status_code == 201, r.text)
        r = gw.post(
            f"{base}/domain_pack/saas-knowledge-assistant/versions/1/publish", headers=tenant
        )
        check("pack published", r.status_code == 200, r.text)
        r = gw.put(
            f"{base}/domain_pack/saas-knowledge-assistant/deployments/dev",
            json={"version": 1},
            headers=tenant,
        )
        check("pack deployed to dev", r.status_code == 200, r.text)
        agent = {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "Smoke Help"}
        r = gw.post(base, json={"kind": "agent", "name": "help", "spec": agent}, headers=tenant)
        check("agent created", r.status_code == 201, r.text)
        gw.post(f"{base}/agent/help/versions/1/publish", headers=tenant).raise_for_status()
        r = gw.put(f"{base}/agent/help/deployments/dev", json={"version": 1}, headers=tenant)
        check("agent deployed to dev", r.status_code == 200, r.text)
        r = gw.get("/config/v1/resolve/agents/help?environment=dev", headers=tenant)
        resolved = (
            r.status_code == 200 and r.json()["config"]["guardrails"]["pii_redaction"] is True
        )
        check("agent resolves through all layers within floors", resolved, r.text)
        r = gw.get("/config/v1/snapshots/dev", headers=tenant)
        keys = gw.get("/config/.well-known/jwks.json").json()["keys"]
        claims = jwt.decode(r.json()["signature"], jwt.PyJWK(keys[0]).key, algorithms=["ES256"])
        check(
            "signed snapshot verifies with the published key",
            claims["digest"] == r.json()["digest"],
            claims,
        )
        r = gw.put(
            f"{base}/agent/help/draft",
            json={"spec": agent},
            headers={"Authorization": f"Bearer {key}"},
        )
        check("member API key cannot change config", r.status_code == 403, r.status_code)

        # ---- events: identity + config outboxes -> NATS -> audit hash chain
        types: set[str] = set()
        for _ in range(30):
            r = gw.get("/audit/v1/events?limit=100", headers=tenant)
            types = (
                {e["type"] for e in r.json().get("items", [])} if r.status_code == 200 else set()
            )
            if {"nexiqon.identity.tenant.created", "nexiqon.config.deployment.changed"} <= types:
                break
            time.sleep(1)
        check(
            "identity and config events reached the audit log",
            "nexiqon.config.deployment.changed" in types,
            types,
        )
        r = gw.get("/audit/v1/verify", headers=tenant)
        check("audit hash chain verifies", r.status_code == 200 and r.json()["ok"] is True, r.text)
        r = gw.get("/audit/v1/events", headers={"Authorization": f"Bearer {key}"})
        check("member API key cannot read the audit log", r.status_code == 403, r.status_code)
        r = gw.get("/config/v1/flags", headers=tenant)
        flags = {f["key"]: f["enabled"] for f in r.json()} if r.status_code == 200 else {}
        check(
            "feature flags evaluated by flagd", flags.get("studio-answer-inspector") is True, r.text
        )

        for path in (
            "/identity/internal/ext-authz/x",
            "/authz/v1/decisions",
            "/model-gateway/meta",
        ):
            r = gw.post(path, headers=auth)
            check(f"internal path not routed: {path}", r.status_code == 404, r.status_code)
    print("gateway smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
