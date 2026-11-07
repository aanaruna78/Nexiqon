from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for conversation. Add service-specific fields here."""

    service_name: str = "conversation"
