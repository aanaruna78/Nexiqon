"""Pytest plugin shared by all services (enabled from the repo-root conftest.py).

Fixtures:
    postgres  (session) -> PgUrls: one pgvector Postgres container per test run, with the
                           non-owner application role and extensions created. Skips when Docker
                           is unavailable.

Services migrate their schema once per session::

    @pytest.fixture(scope="session")
    def db(postgres: PgUrls) -> PgUrls:
        upgrade("identity", postgres.owner, postgres.app_role)
        return postgres
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

APP_ROLE = "nexiqon_app"
APP_PASSWORD = "app-password"  # noqa: S105 - throwaway test container credential
PG_IMAGE = "pgvector/pgvector:0.8.0-pg16"


@dataclass(frozen=True)
class PgUrls:
    owner: str
    app: str
    app_role: str = APP_ROLE


async def _bootstrap(owner_url: str) -> None:
    engine = create_async_engine(owner_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS ltree"))
        await conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
    await engine.dispose()


@pytest.fixture(scope="session")
def postgres() -> Iterator[PgUrls]:
    if shutil.which("docker") is None:
        pytest.skip("Docker not available")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(PG_IMAGE, driver="asyncpg") as pg:
        owner = pg.get_connection_url()
        asyncio.run(_bootstrap(owner))
        user_part = owner.split("://", 1)[1].split("@", 1)[0]
        app = owner.replace(user_part, f"{APP_ROLE}:{APP_PASSWORD}", 1)
        yield PgUrls(owner=owner, app=app)
