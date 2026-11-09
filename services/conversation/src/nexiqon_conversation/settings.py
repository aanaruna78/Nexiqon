from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for conversation."""

    service_name: str = "conversation"
    agent_runtime_url: str | None = None  # derived from deploy/groups.yaml when unset
    config_url: str | None = None
    profile_environment: str = "dev"
    history_messages: int = 12
    default_retention_days: int = 365  # when the agent has no retention profile
    retention_sweep_seconds: float = 3600.0  # 0 disables the background sweep
