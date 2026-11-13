from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for channel."""

    service_name: str = "channel"
    config_url: str | None = None  # derived from deploy/groups.yaml when unset
    agent_environment: str = "dev"
    settings_cache_seconds: float = 30.0
    # Channel's own signing key (ADR 0017). Separate from ``service_identity`` because in the
    # grouped topology channel shares a process, and so its settings files, with agent-runtime.
    channel_identity: ServiceIdentitySettings = ServiceIdentitySettings()
