from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for agent-runtime. Add service-specific fields here."""

    service_name: str = "agent-runtime"
