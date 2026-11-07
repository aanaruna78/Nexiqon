"""Per-service Alembic migrations.

Each service ships ``<package>/migrations/`` with an ``env.py`` of two lines::

    from nexiqon_core.migrations import run_env
    from nexiqon_identity.models import Base
    run_env(Base.metadata)

and versions under ``migrations/versions``. Run with::

    nexiqon-migrate identity            # upgrade head using NEXIQON_DATABASE__MIGRATION_URL

The env creates the service schema, keeps Alembic's version table inside it, and grants the
application role DML on the schema (the role never owns tables, so FORCE RLS applies to it).
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from alembic import command, context
from alembic.config import Config
from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from nexiqon_core.db import _ident
from nexiqon_core.directory import module_for


def alembic_config(service: str, url: str, app_role: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", f"{module_for(service)}:migrations")
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["app_role"] = app_role
    return cfg


def upgrade(service: str, url: str, app_role: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(service, url, app_role), revision)


def downgrade(service: str, url: str, app_role: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(service, url, app_role), revision)


def _grant_sql(schema: str, role: str) -> list[str]:
    s, r = _ident(schema), _ident(role)
    return [
        f"GRANT USAGE ON SCHEMA {s} TO {r}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {s} TO {r}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}",
    ]


def run_env(target_metadata: MetaData) -> None:
    """Body of every service's migrations/env.py."""
    schema = target_metadata.schema
    if not schema:
        raise ValueError("service metadata must declare a schema")
    config = context.config
    url = config.get_main_option("sqlalchemy.url")
    app_role = str(config.attributes.get("app_role", "nexiqon_app"))
    opts: dict[str, Any] = {
        "target_metadata": target_metadata,
        "version_table_schema": schema,
        "include_schemas": True,
        "include_name": lambda name, type_, _parent: type_ != "schema" or name == schema,
    }

    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True, **opts)
        with context.begin_transaction():
            context.run_migrations()
        return

    def do_run(connection: Connection) -> None:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_ident(schema)}"))
        context.configure(connection=connection, **opts)
        with context.begin_transaction():
            context.run_migrations()
        role_exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": app_role}
        ).scalar()
        if role_exists:
            for stmt in _grant_sql(schema, app_role):
                connection.execute(text(stmt))
        connection.commit()

    async def run_async() -> None:
        assert url is not None
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.run_sync(do_run)
        await engine.dispose()

    asyncio.run(run_async())


def main() -> None:
    from nexiqon_core.settings import CoreSettings

    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("service", help="service name, or 'all' for every service with migrations")
    parser.add_argument("action", nargs="?", default="upgrade", choices=["upgrade", "downgrade"])
    parser.add_argument("--revision", default=None)
    args = parser.parse_args()
    settings = CoreSettings(service_name="migrate")
    if settings.database.migration_url is None:
        raise SystemExit("NEXIQON_DATABASE__MIGRATION_URL is not set")
    url = settings.database.migration_url.get_secret_value()
    services = services_with_migrations(settings) if args.service == "all" else [args.service]
    for service in services:
        print(f"migrating {service} ({args.action})", flush=True)
        if args.action == "upgrade":
            upgrade(service, url, settings.database.app_role, args.revision or "head")
        else:
            downgrade(service, url, settings.database.app_role, args.revision or "-1")


def services_with_migrations(settings: Any) -> list[str]:
    import importlib.util

    from nexiqon_core.directory import Topology

    topology = Topology.load(settings.groups_file)
    found: list[str] = []
    for group in topology.groups.values():
        for service in group.services:
            try:
                spec = importlib.util.find_spec(f"{module_for(service)}.migrations")
            except ModuleNotFoundError:
                spec = None
            if spec is not None:
                found.append(service)
    return found


if __name__ == "__main__":
    main()
