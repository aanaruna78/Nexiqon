from pydantic import BaseModel, Field, SecretStr

from nexiqon_core.fetch import FetchPolicy
from nexiqon_core.settings import CoreSettings


class SecretsSettings(BaseModel):
    backend: str = "openbao"  # openbao | memory (tests)
    address: str = "http://openbao:8200"
    token: SecretStr | None = None
    mount: str = "secret"  # KV v2 mount; tenant secrets live under tenants/<tenant_id>/


class ServiceSettings(CoreSettings):
    """Settings for tool-gateway."""

    service_name: str = "tool-gateway"
    config_url: str | None = None  # derived from deploy/groups.yaml when unset
    tool_environment: str = "dev"
    definition_cache_seconds: float = 30.0
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    egress: FetchPolicy = Field(default_factory=FetchPolicy)
    allow_insecure_http: bool = False  # development only (mock APIs on the compose network)
    max_argument_bytes: int = 16_384
    default_max_result_bytes: int = 8_192
    default_timeout_ms: int = 10_000
    approval_ttl_seconds: int = 900
    circuit_failures: int = 5
    circuit_cooldown_seconds: float = 30.0
