"""DV-06: the offline licence limits organizations, and after its grace period staff can no longer
sign in while widgets and API keys keep working."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nexiqon_core.licence import Licence, LicenceInvalid, LicenceSettings
from nexiqon_core.tenancy import CONTEXT_HEADER
from nexiqon_identity.main import create_app
from nexiqon_identity.settings import ServiceSettings
from nexiqon_identity.testing import Env, slug

pytestmark = pytest.mark.integration


def lic(days_left: int, max_tenants: int | None = None) -> Licence:
    today = datetime.now(UTC).date()
    return Licence(
        id="lic-test",
        customer="Example Co",
        issued=today - timedelta(days=400),
        expires=today + timedelta(days=days_left),
        grace_days=30,
        max_tenants=max_tenants,
    )


def test_an_installation_without_a_required_licence_does_not_start() -> None:
    with pytest.raises(LicenceInvalid):
        create_app(ServiceSettings(log_json=False, licence=LicenceSettings(required=True)))


def test_organizations_beyond_the_licence_are_refused(env: Env) -> None:
    env.signup("lic-a", "a@lic.example.com", slug())
    env.client.app.state.licence = lic(200, max_tenants=1)  # type: ignore[attr-defined]
    r = env.client.post(
        "/v1/session/tenants",
        json={"name": "Second", "slug": slug()},
        headers={"Authorization": f"Bearer {env.oidc.user('lic-b', 'b@lic.example.com')}"},
    )
    assert r.status_code == 403
    assert "licensed for 1 organizations" in r.text
    env.client.app.state.licence = lic(200, max_tenants=10**6)  # type: ignore[attr-defined]
    env.signup("lic-c", "c@lic.example.com", slug())


def test_after_the_grace_period_staff_cannot_sign_in_but_api_keys_still_work(env: Env) -> None:
    idp, token = env.signup("lic-owner", "owner@lic.example.com", s := slug())
    key = env.client.post(
        "/v1/api-keys",
        json={"name": "server", "kind": "server", "roles": ["member"]},
        headers={CONTEXT_HEADER: token},
    )
    assert key.status_code == 201, key.text
    secret = key.json()["secret"]

    env.client.app.state.licence = lic(-10)  # type: ignore[attr-defined]  # in its grace period
    assert (
        env.client.get("/v1/licence", headers={CONTEXT_HEADER: token}).json()["status"] == "grace"
    )
    env.context(idp, s)  # still signs in

    env.client.app.state.licence = lic(-31)  # type: ignore[attr-defined]
    staff = env.client.post(
        "/internal/ext-authz/agent/v1/x",
        headers={"Authorization": f"Bearer {idp}", "X-Nexiqon-Tenant": s},
    )
    assert staff.status_code == 403
    assert "licence has expired" in staff.text
    api = env.client.post(
        "/internal/ext-authz/agent/v1/x", headers={"Authorization": f"Bearer {secret}"}
    )
    assert api.status_code == 200


def test_admins_see_the_licence_status_and_limits(env: Env) -> None:
    _, token = env.signup("lic-admin", "admin@lic.example.com", slug())
    env.client.app.state.licence = lic(20, max_tenants=5)  # type: ignore[attr-defined]
    body = env.client.get("/v1/licence", headers={CONTEXT_HEADER: token}).json()
    assert body["status"] == "expiring"
    assert body["customer"] == "Example Co"
    assert body["max_tenants"] == 5
    env.client.app.state.licence = None  # type: ignore[attr-defined]
    assert (
        env.client.get("/v1/licence", headers={CONTEXT_HEADER: token}).json()["status"]
        == "unlicensed"
    )
