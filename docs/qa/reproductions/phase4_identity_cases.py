"""Licence limits must apply to every tenant provisioning route."""

from datetime import UTC, datetime, timedelta

from nexiqon_core.licence import Licence

pytest_plugins = ["services.identity.tests.conftest"]


def test_signed_clerk_org_webhook_must_respect_licence_limit(env):
    from nexiqon_identity.testing import slug

    env.signup("qa-license", "qa@license.example", slug())
    today = datetime.now(UTC).date()
    env.client.app.state.licence = Licence(
        id="qa-only",
        customer="QA",
        issued=today,
        expires=today + timedelta(days=90),
        max_tenants=1,
    )
    r = env.webhook(
        {
            "type": "organization.created",
            "data": {
                "id": "org_qa_license_second",
                "name": "Second QA organization",
                "slug": "qa-license-second",
            },
        }
    )
    from nexiqon_identity.models import Tenant
    from sqlalchemy import func, select

    async def tenant_count():
        async with env.client.app.state.db.scoped({"licence_count": "on"}) as session:
            return await session.scalar(select(func.count()).select_from(Tenant))

    count = env.client.portal.call(tenant_count)
    print(
        "Second organisation webhook at licence capacity:",
        r.status_code,
        r.text,
        "persisted tenants:",
        count,
    )
    assert count <= 1, "Signed webhook created an organisation beyond licence capacity"
    assert r.status_code != 200, (
        "A second organisation was provisioned despite max_tenants=1"
    )
