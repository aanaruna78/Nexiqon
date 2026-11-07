"""Deployment groups and service discovery.

``deploy/groups.yaml`` maps the 17 logical services onto deployable groups. Every service is always
served under ``/<service>`` so a URL only changes host when a group is split:

* grouped: ``http://<group>:<port>/<service>``
* split:   ``http://<service>:<port>/<service>``

``NEXIQON_SERVICE_URL_<SERVICE>`` (upper case, dashes as underscores) overrides any URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Mode = Literal["grouped", "split"]


@dataclass(frozen=True)
class Group:
    name: str
    plane: str
    services: tuple[str, ...]


@dataclass(frozen=True)
class Topology:
    mode: Mode
    port: int
    groups: dict[str, Group]

    @classmethod
    def load(cls, path: Path) -> Topology:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        groups = {
            name: Group(name=name, plane=g["plane"], services=tuple(g["services"]))
            for name, g in raw["groups"].items()
        }
        seen: dict[str, str] = {}
        for g in groups.values():
            for svc in g.services:
                if svc in seen:
                    raise ValueError(f"service {svc!r} is in groups {seen[svc]!r} and {g.name!r}")
                seen[svc] = g.name
        mode = os.environ.get("NEXIQON_TOPOLOGY_MODE", raw.get("mode", "grouped"))
        if mode not in ("grouped", "split"):
            raise ValueError(f"unknown topology mode {mode!r}")
        return cls(mode=mode, port=int(raw.get("port", 8000)), groups=groups)

    def group_of(self, service: str) -> Group:
        for g in self.groups.values():
            if service in g.services:
                return g
        raise KeyError(f"service {service!r} is not in any group")

    def url_for(self, service: str) -> str:
        override = os.environ.get(f"NEXIQON_SERVICE_URL_{service.upper().replace('-', '_')}")
        if override:
            return override.rstrip("/")
        host = self.group_of(service).name if self.mode == "grouped" else service
        return f"http://{host}:{self.port}/{service}"


def module_for(service: str) -> str:
    """Python package implementing ``service`` (e.g. agent-runtime -> nexiqon_agent_runtime)."""
    return "nexiqon_" + service.replace("-", "_")
