from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for config. Add service-specific fields here."""

    service_name: str = "config"
