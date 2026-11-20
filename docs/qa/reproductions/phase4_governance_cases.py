"""Additional local governance acceptance cases, disposable Postgres/Temporal only."""

import importlib

pytest_plugins = ["services.governance.tests.conftest"]


async def test_deletion_removes_prior_export_archives_without_touching_other_tenant(
    stack,
):
    helper = importlib.import_module("services.governance.tests.test_lifecycle")
    await helper.seed(stack, "a")
    await helper.seed(stack, "b")
    exported = await stack.ok("POST", "/v1/lifecycle/export", 202)
    await stack.wait("export", exported["id"])
    key = f"t/{stack.tenants.a.context.tenant_id}/exports/{exported['id']}.zip"
    assert key in stack.blobs.objects
    other = f"t/{stack.tenants.b.context.tenant_id}/exports/keep.zip"
    await stack.blobs.put(other, b"OTHER-TENANT-MARKER", "application/zip")
    deletion = await stack.ok(
        "POST",
        "/v1/lifecycle/delete",
        202,
        json={"confirm": str(stack.tenants.a.context.tenant_id)},
    )
    done = await stack.wait("delete", deletion["id"])
    assert done["status"] == "completed", done
    assert (await stack.blobs.get(other)) == b"OTHER-TENANT-MARKER"
    print(
        "Deletion completed; old tenant export archive remains:",
        key in stack.blobs.objects,
        "other tenant preserved:",
        other in stack.blobs.objects,
    )
    assert key not in stack.blobs.objects, (
        "Deletion certificate succeeded while a complete export remains"
    )
