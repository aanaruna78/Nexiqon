"""A release gate must bind approval to the bytes actually published."""

import importlib

pytest_plugins = ["services.evaluation.tests.conftest"]


async def test_concurrent_edit_after_gate_check_must_not_publish_unevaluated_content(
    stack, monkeypatch
):
    helper = importlib.import_module("services.evaluation.tests.test_evaluation")
    fixture = importlib.import_module("services.evaluation.tests.conftest")
    test_set = await helper.make_set(stack)
    version = await stack.draft(fixture.spec(**helper.GATE))
    helper.answer_well(stack, version)
    await stack.run(version, test_set["id"])
    config_app = stack.config._transport.app
    original = config_app.state.gate.check

    async def edit_between_check_and_publish(*args, **kwargs):
        checked = await original(*args, **kwargs)
        assert checked["passed"], checked
        await stack.draft(
            fixture.spec(**helper.GATE, display_name="Unreviewed QA change")
        )
        return checked

    monkeypatch.setattr(config_app.state.gate, "check", edit_between_check_and_publish)
    r = await stack.config.post(
        f"/v1/objects/agent/helper/versions/{version}/publish",
        headers=stack.headers("editor"),
    )
    detail = await stack.cfg("GET", f"/v1/objects/agent/helper/versions/{version}")
    print(
        "Publish after concurrent edit:",
        r.status_code,
        "gate:",
        r.json().get("gate", {}).get("passed"),
        "actual published display name:",
        detail["spec"]["display_name"],
    )
    assert r.status_code == 409, (
        "The gate approved one hash but published a different draft"
    )
