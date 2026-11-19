from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for metering."""

    service_name: str = "metering"
    # Metering's own signing key (ADR 0017): reads assistants' packs (KPIs) from config and
    # unanswered questions from conversation for the content-gap report.
    metering_identity: ServiceIdentitySettings = ServiceIdentitySettings()
    config_url: str | None = None
    conversation_url: str | None = None
    profile_environment: str = "dev"
    gap_similarity: float = 0.3  # how alike two questions must be to share a topic
