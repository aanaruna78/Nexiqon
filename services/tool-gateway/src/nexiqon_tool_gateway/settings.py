from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for tool-gateway. Add service-specific fields here."""

    service_name: str = "tool-gateway"
