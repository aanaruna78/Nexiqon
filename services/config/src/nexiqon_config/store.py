"""Config registry operations: versions, publishing, deployments, resolution and snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib import resources
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexiqon_config import kinds
from nexiqon_config.models import (
    ENVIRONMENTS,
    ConfigDeployment,
    ConfigObject,
    ConfigVersion,
    DeploymentHistory,
    Outbox,
)
from nexiqon_config.resolution import FloorRule, Layer, check_floors, merge_layers, rules_from
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.errors import BadRequest, Conflict, NexiqonError, NotFound
from nexiqon_core.events import add_event
from nexiqon_core.signing import canonical_digest
from nexiqon_core.tenancy import TenantContext

__all__ = ["Store", "canonical_digest"]

SOURCE = "config"
TENANT_SETTINGS = "default"  # name of the single tenant_settings / security_floors object
PROFILE_KINDS = {
    "model_profile": "model",
    "retrieval_profile": "retrieval",
    "retention_profile": "retention",
}


class ValidationFailed(NexiqonError):
    status, code, title = 422, "config_invalid", "Configuration is invalid"

    def __init__(
        self, problems: list[dict[str, str]], detail: str = "Configuration is invalid"
    ) -> None:
        super().__init__(detail)
        self.errors = [dict(p) for p in problems]


class FloorViolation(NexiqonError):
    status, code, title = 409, "security_floor_violation", "Security floor violated"

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.errors = [{"message": m} for m in messages]


@cache
def _defaults(name: str) -> dict[str, Any]:
    text = resources.files("nexiqon_config.defaults").joinpath(f"{name}.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(text) or {}
    return data


def platform_floors() -> list[FloorRule]:
    return rules_from(_defaults("floors"), "platform")


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _check(kind: str, spec: Any) -> None:
    problems = kinds.validate(kind, spec)
    if problems:
        raise ValidationFailed([{"path": p.path, "message": p.message} for p in problems])


@dataclass
class Store:
    s: AsyncSession
    ctx: TenantContext
    settings: ServiceSettings

    def _event(self, type_: str, subject: str, **data: Any) -> None:
        add_event(
            self.s,
            Outbox,
            self.ctx,
            source=SOURCE,
            type=f"nexiqon.config.{type_}",
            subject=subject,
            data=data,
        )

    # ------------------------------------------------------------------ objects & versions
    async def get_object(self, kind: str, name: str) -> ConfigObject:
        obj = await self.s.scalar(
            select(ConfigObject).where(ConfigObject.kind == kind, ConfigObject.name == name)
        )
        if obj is None or obj.archived_at is not None:
            raise NotFound(f"No {kind} named {name!r}")
        return obj

    async def create(
        self, kind: str, name: str, description: str, spec: dict[str, Any]
    ) -> ConfigVersion:
        _check(kind, spec)
        exists = await self.s.scalar(
            select(ConfigObject.id).where(ConfigObject.kind == kind, ConfigObject.name == name)
        )
        if exists is not None:
            raise Conflict(f"A {kind} named {name!r} already exists")
        obj = ConfigObject(
            tenant_id=self.ctx.tenant_id,
            kind=kind,
            name=name,
            description=description,
            created_by=self.ctx.actor_id,
        )
        self.s.add(obj)
        await self.s.flush()
        return await self._new_draft(obj, 1, spec, "")

    async def _new_draft(
        self, obj: ConfigObject, version: int, spec: dict[str, Any], notes: str
    ) -> ConfigVersion:
        v = ConfigVersion(
            tenant_id=self.ctx.tenant_id,
            object_id=obj.id,
            version=version,
            spec=spec,
            spec_hash=spec_hash(spec),
            status="draft",
            notes=notes,
            created_by=self.ctx.actor_id,
        )
        self.s.add(v)
        await self.s.flush()
        self._event("draft.saved", f"{obj.kind}/{obj.name}", version=version)
        return v

    async def versions(self, obj: ConfigObject) -> list[ConfigVersion]:
        rows = await self.s.scalars(
            select(ConfigVersion)
            .where(ConfigVersion.object_id == obj.id)
            .order_by(ConfigVersion.version)
        )
        return list(rows.all())

    async def version(self, obj: ConfigObject, number: int) -> ConfigVersion:
        v = await self.s.scalar(
            select(ConfigVersion).where(
                ConfigVersion.object_id == obj.id, ConfigVersion.version == number
            )
        )
        if v is None:
            raise NotFound(f"{obj.kind}/{obj.name} has no version {number}")
        return v

    async def save_draft(
        self, kind: str, name: str, spec: dict[str, Any], notes: str
    ) -> ConfigVersion:
        _check(kind, spec)
        obj = await self.get_object(kind, name)
        draft = await self.s.scalar(
            select(ConfigVersion).where(
                ConfigVersion.object_id == obj.id, ConfigVersion.status == "draft"
            )
        )
        if draft is not None:
            draft.spec, draft.spec_hash, draft.notes = spec, spec_hash(spec), notes
            await self.s.flush()
            self._event("draft.saved", f"{kind}/{name}", version=draft.version)
            return draft
        latest = await self.s.scalar(
            select(func.max(ConfigVersion.version)).where(ConfigVersion.object_id == obj.id)
        )
        return await self._new_draft(obj, int(latest or 0) + 1, spec, notes)

    async def publish(self, kind: str, name: str, number: int) -> ConfigVersion:
        obj = await self.get_object(kind, name)
        v = await self.version(obj, number)
        if v.status != "draft":
            raise Conflict(f"Version {number} is already published")
        _check(kind, v.spec)
        if kind == "agent":
            # Fail early: the draft must resolve within floors in dev with what is deployed there.
            await self.resolve_agent(name, "dev", agent_version=v)
        v.status, v.published_by, v.published_at = "published", self.ctx.actor_id, datetime.now(UTC)
        await self.s.flush()
        self._event("version.published", f"{kind}/{name}", version=number, spec_hash=v.spec_hash)
        return v

    async def archive(self, kind: str, name: str) -> None:
        obj = await self.get_object(kind, name)
        deployed = await self.s.scalar(
            select(func.count())
            .select_from(ConfigDeployment)
            .where(ConfigDeployment.object_id == obj.id)
        )
        if deployed:
            raise Conflict("Undeploy from all environments before archiving")
        obj.archived_at = datetime.now(UTC)
        self._event("object.archived", f"{kind}/{name}")

    # ------------------------------------------------------------------ deployments
    async def deployments(self, obj: ConfigObject) -> dict[str, int]:
        rows = await self.s.execute(
            select(ConfigDeployment.environment, ConfigDeployment.version).where(
                ConfigDeployment.object_id == obj.id
            )
        )
        return {env: ver for env, ver in rows.all()}

    async def history(self, obj: ConfigObject) -> list[DeploymentHistory]:
        rows = await self.s.scalars(
            select(DeploymentHistory)
            .where(DeploymentHistory.object_id == obj.id)
            .order_by(DeploymentHistory.created_at, DeploymentHistory.id)
        )
        return list(rows.all())

    async def _promotion_required(self) -> bool:
        spec = await self._deployed_spec("tenant_settings", TENANT_SETTINGS, "prod")
        return bool(((spec or {}).get("promotion") or {}).get("require_order", True))

    async def deploy(
        self, kind: str, name: str, environment: str, number: int, reason: str
    ) -> ConfigDeployment:
        if environment not in ENVIRONMENTS:
            raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
        obj = await self.get_object(kind, name)
        v = await self.version(obj, number)
        if v.status != "published":
            raise Conflict("Only published versions can be deployed")
        index = ENVIRONMENTS.index(environment)
        if index > 0 and await self._promotion_required():
            previous = ENVIRONMENTS[index - 1]
            seen = await self.s.scalar(
                select(func.count())
                .select_from(DeploymentHistory)
                .where(
                    DeploymentHistory.object_id == obj.id,
                    DeploymentHistory.environment == previous,
                    DeploymentHistory.to_version == number,
                )
            )
            if not seen:
                raise Conflict(
                    f"Promote through {previous} first: version {number} was never deployed there"
                )
        current = await self.s.scalar(
            select(ConfigDeployment).where(
                ConfigDeployment.object_id == obj.id, ConfigDeployment.environment == environment
            )
        )
        before = current.version if current else None
        if current is None:
            current = ConfigDeployment(
                tenant_id=self.ctx.tenant_id,
                object_id=obj.id,
                environment=environment,
                version_id=v.id,
                version=number,
                deployed_by=self.ctx.actor_id,
            )
            self.s.add(current)
        else:
            current.version_id, current.version, current.deployed_by = (
                v.id,
                number,
                self.ctx.actor_id,
            )
        self.s.add(
            DeploymentHistory(
                tenant_id=self.ctx.tenant_id,
                object_id=obj.id,
                environment=environment,
                from_version=before,
                to_version=number,
                actor=self.ctx.actor_id,
                reason=reason,
            )
        )
        await self.s.flush()
        # Safety gate: every agent live in this environment must still resolve within floors.
        await self._verify_environment(environment)
        self._event(
            "deployment.changed",
            f"{kind}/{name}",
            environment=environment,
            from_version=before,
            to_version=number,
        )
        return current

    async def undeploy(self, kind: str, name: str, environment: str) -> None:
        obj = await self.get_object(kind, name)
        current = await self.s.scalar(
            select(ConfigDeployment).where(
                ConfigDeployment.object_id == obj.id, ConfigDeployment.environment == environment
            )
        )
        if current is None:
            raise NotFound("Not deployed in that environment")
        await self.s.delete(current)
        await self.s.flush()
        await self._verify_environment(environment)
        self._event("deployment.removed", f"{kind}/{name}", environment=environment)

    async def _verify_environment(self, environment: str) -> None:
        for agent in await self._deployed_names("agent", environment):
            await self.resolve_agent(agent, environment)

    # ------------------------------------------------------------------ resolution
    async def _deployed_version(
        self, kind: str, name: str, environment: str
    ) -> ConfigVersion | None:
        row = await self.s.scalar(
            select(ConfigVersion)
            .join(ConfigDeployment, ConfigDeployment.version_id == ConfigVersion.id)
            .join(ConfigObject, ConfigObject.id == ConfigDeployment.object_id)
            .where(
                ConfigObject.kind == kind,
                ConfigObject.name == name,
                ConfigDeployment.environment == environment,
            )
        )
        return row

    async def _deployed_spec(self, kind: str, name: str, environment: str) -> dict[str, Any] | None:
        v = await self._deployed_version(kind, name, environment)
        return v.spec if v else None

    async def _deployed_names(self, kind: str, environment: str) -> list[str]:
        rows = await self.s.scalars(
            select(ConfigObject.name)
            .join(ConfigDeployment, ConfigDeployment.object_id == ConfigObject.id)
            .where(ConfigObject.kind == kind, ConfigDeployment.environment == environment)
            .order_by(ConfigObject.name)
        )
        return list(rows.all())

    async def deployed_specs(self, kind: str, environment: str) -> list[dict[str, Any]]:
        rows = await self.s.scalars(
            select(ConfigVersion.spec)
            .join(ConfigDeployment, ConfigDeployment.version_id == ConfigVersion.id)
            .join(ConfigObject, ConfigObject.id == ConfigDeployment.object_id)
            .where(ConfigObject.kind == kind, ConfigDeployment.environment == environment)
            .order_by(ConfigObject.name)
        )
        return list(rows.all())

    async def floors(self, environment: str) -> list[FloorRule]:
        tenant = await self._deployed_spec("security_floors", TENANT_SETTINGS, environment)
        deployment = {"rules": self.settings.deployment_floors}
        return (
            platform_floors() + rules_from(deployment, "deployment") + rules_from(tenant, "tenant")
        )

    async def resolve_agent(
        self,
        name: str,
        environment: str,
        *,
        channel: str | None = None,
        agent_version: ConfigVersion | None = None,
    ) -> dict[str, Any]:
        """Resolve an agent through every layer; raises FloorViolation (fail closed)."""
        if environment not in ENVIRONMENTS:
            raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
        agent_v = agent_version or await self._deployed_version("agent", name, environment)
        if agent_v is None:
            raise NotFound(f"Agent {name!r} is not deployed in {environment}")
        agent = agent_v.spec
        versions: dict[str, Any] = {"agent": agent_v.version}

        pack_ref = agent["pack"]
        pack_obj = await self.get_object("domain_pack", pack_ref["name"])
        if "version" in pack_ref:
            pack_v: ConfigVersion | None = await self.version(pack_obj, int(pack_ref["version"]))
            if pack_v is not None and pack_v.status != "published":
                raise Conflict("Agents can only pin published pack versions")
        else:
            pack_v = await self._deployed_version("domain_pack", pack_ref["name"], environment)
        if pack_v is None:
            raise Conflict(f"Pack {pack_ref['name']!r} is not deployed in {environment}")
        versions["pack"] = pack_v.version
        pack = pack_v.spec

        tenant_v = await self._deployed_version("tenant_settings", TENANT_SETTINGS, environment)
        tenant = tenant_v.spec if tenant_v else {}
        if tenant_v:
            versions["tenant_settings"] = tenant_v.version
        region = self.ctx.region or "default"
        defaults = _defaults("platform")
        layers = [
            Layer("platform", defaults.get("agent", {})),
            Layer("deployment", self.settings.deployment_layer.get("agent", {})),
            Layer(f"region:{region}", self.settings.region_layers.get(region, {}).get("agent", {})),
            Layer("tenant", tenant.get("agent_defaults", {})),
            Layer(
                f"pack:{pack_ref['name']}@{pack_v.version}",
                # Deep merge: agent_defaults.guardrails must not drop the pack's own guardrails.
                merge_layers(
                    [
                        Layer(
                            "pack", {k: pack[k] for k in ("guardrails", "escalation") if k in pack}
                        ),
                        Layer("pack", pack.get("agent_defaults", {})),
                    ]
                ).values,
            ),
            Layer(
                f"agent:{name}@{agent_v.version}",
                {k: v for k, v in agent.items() if k != "graph_override"},
            ),
        ]
        if channel:
            channel_v = await self._deployed_version("channel", channel, environment)
            if channel_v is None:
                raise NotFound(f"Channel {channel!r} is not deployed in {environment}")
            versions["channel"] = channel_v.version
            layers.append(
                Layer(
                    f"channel:{channel}@{channel_v.version}",
                    channel_v.spec.get("agent_overrides", {}),
                )
            )
        env_overrides = ((tenant.get("environments") or {}).get(environment) or {}).get(
            "agent_overrides", {}
        )
        layers.append(Layer(f"environment:{environment}", env_overrides))
        resolved = merge_layers(layers)

        # Inline referenced profiles (tenant object deployed here, else the built-in).
        builtin = _defaults("profiles")
        for kind, key in PROFILE_KINDS.items():
            ref = resolved.values.get(kind)
            if not ref:
                continue
            v = await self._deployed_version(kind, ref, environment)
            if v is not None:
                resolved.values[key], versions[kind] = v.spec, v.version
                origin = f"{kind}:{ref}@{v.version}"
            elif ref in builtin.get(kind, {}):
                resolved.values[key] = builtin[kind][ref]
                origin = f"builtin:{kind}:{ref}"
            else:
                raise Conflict(
                    f"{kind} {ref!r} is not deployed in {environment} and is not built in"
                )
            resolved.provenance[key] = origin

        violations = check_floors(resolved.values, await self.floors(environment))
        if violations:
            raise FloorViolation([v.message for v in violations])
        graph = agent.get("graph_override") or pack["graph"]
        return {
            "agent": name,
            "environment": environment,
            "versions": versions,
            "config": resolved.values,
            "provenance": resolved.provenance,
            "pack": {k: v for k, v in pack.items() if k not in ("agent_defaults", "graph")},
            "graph": graph,
        }

    async def resolve_profile(self, kind: str, name: str, environment: str) -> dict[str, Any]:
        """Effective profile: the tenant's deployed object, else the built-in. Model profiles are
        checked against the security floors that constrain ``model.*`` (fail closed)."""
        if kind not in PROFILE_KINDS:
            raise BadRequest(f"{kind} is not a profile kind")
        v = await self._deployed_version(kind, name, environment)
        builtin = _defaults("profiles").get(kind, {})
        if v is not None:
            spec, source = v.spec, f"{kind}:{name}@{v.version}"
        elif name in builtin:
            spec, source = builtin[name], f"builtin:{kind}:{name}"
        else:
            raise NotFound(f"{kind} {name!r} is not deployed in {environment} and is not built in")
        key = PROFILE_KINDS[kind]
        rules = [r for r in await self.floors(environment) if r.path.startswith(f"{key}.")]
        violations = check_floors({key: spec}, rules)
        if violations:
            raise FloorViolation([x.message for x in violations])
        return {
            "kind": kind,
            "name": name,
            "environment": environment,
            "source": source,
            "profile": spec,
        }

    async def list_profiles(self, kind: str, environment: str) -> list[dict[str, Any]]:
        """Profiles usable in ``environment``: deployed tenant objects and built-ins, each with
        whether the security floors allow it (pickers show blocked ones disabled, with the reason)."""
        if kind not in PROFILE_KINDS:
            raise BadRequest(f"{kind} is not a profile kind")
        names = set(_defaults("profiles").get(kind, {}))
        deployed = await self.s.scalars(
            select(ConfigObject.name)
            .join(ConfigDeployment, ConfigDeployment.object_id == ConfigObject.id)
            .where(ConfigObject.kind == kind, ConfigDeployment.environment == environment)
        )
        names.update(deployed.all())
        out: list[dict[str, Any]] = []
        for name in sorted(names):
            try:
                resolved = await self.resolve_profile(kind, name, environment)
                out.append(
                    {
                        "name": name,
                        "source": resolved["source"],
                        "allowed": True,
                        "reason": None,
                        "profile": resolved["profile"],
                    }
                )
            except FloorViolation as exc:
                out.append(
                    {
                        "name": name,
                        "source": None,
                        "allowed": False,
                        "reason": exc.detail,
                        "profile": None,
                    }
                )
        return out

    # ------------------------------------------------------------------ snapshots
    async def snapshot(self, environment: str) -> dict[str, Any]:
        rows = (
            await self.s.execute(
                select(
                    ConfigObject.kind,
                    ConfigObject.name,
                    ConfigVersion.version,
                    ConfigVersion.spec_hash,
                    ConfigVersion.spec,
                )
                .join(ConfigDeployment, ConfigDeployment.object_id == ConfigObject.id)
                .join(ConfigVersion, ConfigVersion.id == ConfigDeployment.version_id)
                .where(ConfigDeployment.environment == environment)
                .order_by(ConfigObject.kind, ConfigObject.name)
            )
        ).all()
        objects = [
            {"kind": k, "name": n, "version": ver, "spec_hash": h, "spec": spec}
            for k, n, ver, h, spec in rows
        ]
        agents = {
            name: await self.resolve_agent(name, environment)
            for name in await self._deployed_names("agent", environment)
        }
        body = {
            "tenant_id": str(self.ctx.tenant_id),
            "environment": environment,
            "objects": objects,
            "agents": agents,
        }
        return body


def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise BadRequest("Invalid id") from exc
