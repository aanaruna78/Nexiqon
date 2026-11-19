from pathlib import Path

from pydantic import Field

from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for the data-plane config mirror."""

    service_name: str = "config-mirror"
    # The control plane's config service, reached outbound only (e.g. https://cp.example.com/config).
    control_config_url: str = "http://config:8000/config"
    config_environment: str = "prod"  # which deployed configuration this data plane serves
    # Public keys that sign configuration snapshots (control plane's /config/.well-known/jwks.json).
    snapshot_public_keys: dict[str, str] = Field(default_factory=dict)
    cache_dir: Path = Path("/tmp/nexiqon-config-mirror")  # noqa: S108 - an emptyDir in Kubernetes
    refresh_seconds: float = 30.0  # a snapshot is re-checked (ETag) at most this often
    # The mirror's own identity: it pulls snapshots for a tenant as itself (ADR 0017).
    mirror_identity: ServiceIdentitySettings = ServiceIdentitySettings()
