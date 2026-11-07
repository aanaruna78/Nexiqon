from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for notification. Add service-specific fields here."""

    service_name: str = "notification"
