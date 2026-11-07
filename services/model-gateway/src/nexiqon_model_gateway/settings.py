from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for model-gateway. Add service-specific fields here."""

    service_name: str = "model-gateway"
