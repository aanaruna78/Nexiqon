from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for governance. Add service-specific fields here."""

    service_name: str = "governance"
