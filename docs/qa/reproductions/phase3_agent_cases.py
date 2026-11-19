"""Independent Phase 3 runtime response and streaming acceptance cases."""

import json
import uuid

pytest_plugins = ["services.agent-runtime.tests.conftest"]


def test_nonstaff_run_response_must_not_disclose_hidden_source_counts(stack):
    stack.fakes.hidden = 7
    r = stack.run(
        "qa-count-" + uuid.uuid4().hex[:8],
        "How do I invite a teammate?",
        headers=stack.headers({"end_user"}, actor="visitor-qa", actor_type="widget"),
    )
    steps = r["steps"]
    print(
        "nonstaff immediate run hidden fields:",
        [s.get("hidden_by_access") for s in steps if "hidden_by_access" in s],
    )
    assert all("hidden_by_access" not in s for s in steps)


def test_withheld_system_prompt_must_not_already_be_in_streamed_deltas(stack):
    question = "Hello QA system disclosure sentinel"
    stack.fakes.intents = {"Hello QA": "greeting"}
    stack.fakes.attacks = [("QA system disclosure sentinel", "{system}")]
    r = stack.client.post(
        "/v1/agents/support/runs/stream",
        json={"thread_id": "qa-stream-" + uuid.uuid4().hex[:8], "input": question},
        headers=stack.headers({"end_user"}, actor="visitor-qa", actor_type="widget"),
    )
    assert r.status_code == 200, r.text
    events = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    final = events[-1][1]
    assert final["answer"]["kind"] == "withheld", final
    streamed = "".join(d["text"] for k, d in events if k == "delta")
    system = stack.fakes.chats("smalltalk")[-1]["messages"][0]["content"]
    print(
        "final kind:",
        final["answer"]["kind"],
        "system prompt already streamed:",
        system in streamed,
        "streamed length:",
        len(streamed),
    )
    assert system not in streamed
