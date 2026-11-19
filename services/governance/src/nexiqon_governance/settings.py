from pydantic import Field

from nexiqon_core.blobs import BlobSettings
from nexiqon_core.lifecycle import RetentionPolicy
from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for governance."""

    service_name: str = "governance"
    # Governance's own signing key (ADR 0017): the only identity the lifecycle endpoints accept.
    governance_identity: ServiceIdentitySettings = ServiceIdentitySettings()
    blobs: BlobSettings = Field(default_factory=BlobSettings)  # export archives
    task_queue: str = "governance"
    run_worker: bool = True
    worker_max_cached_workflows: int = 1000
    # A deletion waits this long (and can be cancelled) before anything is removed.
    deletion_grace_hours: float = 72.0
    export_link_days: int = 7  # export archives are removed after this
    retention_hour_utc: int = 3  # the daily platform-wide retention sweep
    retention_profile: str = "standard"  # each tenant's own version of it, from config
    fallback_retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    profile_environment: str = "dev"
    # Service URLs by name (tests); otherwise from deploy/groups.yaml.
    service_urls: dict[str, str] = Field(default_factory=dict)
