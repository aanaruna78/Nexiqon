from __future__ import annotations

import pytest

from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls


@pytest.fixture(scope="session")
def mail_db(postgres: PgUrls) -> PgUrls:
    upgrade("notification", postgres.owner, postgres.app_role)
    return postgres
