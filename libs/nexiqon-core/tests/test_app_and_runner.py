from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexiqon_core.app import create_service_app
from nexiqon_core.directory import Topology, module_for
from nexiqon_core.runner import build_group_app
from nexiqon_core.settings import CoreSettings


def _svc(name: str, events: list[str], ready: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        events.append(f"start:{name}")
        yield
        events.append(f"stop:{name}")

    async def check() -> bool:
        return ready

    return create_service_app(
        name=name,
        version="0",
        plane="control",
        settings=CoreSettings(service_name=name, log_json=False),
        readiness_checks={"dep": check},
        lifespan=lifespan,
    )


def test_service_app_ops_endpoints_and_request_id() -> None:
    client = TestClient(_svc("alpha", []))
    assert client.get("/healthz").json() == {"status": "ok", "service": "alpha"}
    assert client.get("/readyz").status_code == 200
    r = client.get("/meta", headers={"X-Request-ID": "abc"})
    assert r.json()["plane"] == "control"
    assert r.headers["X-Request-ID"] == "abc"


def test_unknown_route_uses_problem_envelope() -> None:
    r = TestClient(_svc("alpha", [])).get("/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "http_404"


def test_group_mounts_services_and_runs_lifespans() -> None:
    events: list[str] = []
    group = build_group_app(
        "g",
        ["alpha", "beta"],
        factories={"alpha": lambda: _svc("alpha", events), "beta": lambda: _svc("beta", events)},
    )
    with TestClient(group) as client:
        assert events == ["start:alpha", "start:beta"]
        assert client.get("/alpha/meta").json()["service"] == "alpha"
        assert client.get("/beta/healthz").json()["service"] == "beta"
        assert client.get("/healthz").json()["services"] == ["alpha", "beta"]
        assert client.get("/readyz").status_code == 200
    assert events[-2:] == ["stop:beta", "stop:alpha"]


def test_group_not_ready_when_any_service_is_not() -> None:
    group = build_group_app(
        "g",
        ["alpha", "beta"],
        factories={"alpha": lambda: _svc("alpha", []), "beta": lambda: _svc("beta", [], False)},
    )
    with TestClient(group) as client:
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["services"] == {"alpha": True, "beta": False}


GROUPS = """
mode: grouped
port: 8000
groups:
  control-core: {plane: control, services: [identity, config]}
  agent: {plane: data, services: [agent-runtime]}
"""


def test_topology_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "groups.yaml"
    f.write_text(GROUPS)
    topo = Topology.load(f)
    assert topo.url_for("config") == "http://control-core:8000/config"
    monkeypatch.setenv("NEXIQON_TOPOLOGY_MODE", "split")
    assert Topology.load(f).url_for("config") == "http://config:8000/config"
    monkeypatch.setenv("NEXIQON_SERVICE_URL_AGENT_RUNTIME", "https://agent.example/agent-runtime/")
    assert Topology.load(f).url_for("agent-runtime") == "https://agent.example/agent-runtime"
    assert module_for("agent-runtime") == "nexiqon_agent_runtime"


def test_service_in_two_groups_is_rejected(tmp_path: Path) -> None:
    f = tmp_path / "groups.yaml"
    f.write_text(
        "groups:\n  a: {plane: control, services: [x]}\n  b: {plane: data, services: [x]}\n"
    )
    with pytest.raises(ValueError, match="in groups"):
        Topology.load(f)


def test_repo_groups_file_is_valid() -> None:
    root = Path(__file__).resolve().parents[3]
    topo = Topology.load(root / "deploy" / "groups.yaml")
    services = [s for g in topo.groups.values() for s in g.services]
    assert len(services) == len(set(services)) == 15  # + gateway (edge, infrastructure) = 16
