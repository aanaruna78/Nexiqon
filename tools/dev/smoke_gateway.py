"""End-to-end smoke test of the local stack through the gateway (make dev-up PROFILES=platform,apps).

    uv run python tools/dev/smoke_gateway.py

Logs in to the dev Keycloak realm, creates a tenant, mints an API key and exercises the
gateway's security behaviour. Exits non-zero on the first failure.
"""

from __future__ import annotations

import sys
import time
import uuid

import httpx

GATEWAY = "http://localhost:8000"
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
