import pytest

from nexiqon_core.testing import TwoTenants


@pytest.fixture
def tenants() -> TwoTenants:
    return TwoTenants.create()
