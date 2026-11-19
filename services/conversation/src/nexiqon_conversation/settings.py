from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for conversation."""

    service_name: str = "conversation"
    agent_runtime_url: str | None = None  # derived from deploy/groups.yaml when unset
    config_url: str | None = None
    profile_environment: str = "dev"
    history_messages: int = 12
    default_retention_days: int = 365  # when the agent has no retention profile
    retention_sweep_seconds: float = 3600.0  # 0 disables the background sweep
    # Transcript emails (W-03) go through the notification service as conversation's own identity
    # (ADR 0017): a widget key alone can never send email.
    notification_url: str | None = None
    conversation_identity: ServiceIdentitySettings = ServiceIdentitySettings()
    transcript_cooldown_seconds: int = 600  # one transcript per conversation per 10 minutes
