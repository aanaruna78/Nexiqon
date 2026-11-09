from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from nexiqon_core.settings import CoreSettings

Classification = Literal["public", "internal", "confidential", "restricted"]


class ProviderCredentials(BaseModel):
    """Platform-held provider keys (from OpenBao in production). Never returned by any API."""

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openai_compatible_api_key: SecretStr | None = None  # optional bearer for vLLM/Ollama


class ServiceSettings(CoreSettings):
    """Settings for model-gateway."""

    service_name: str = "model-gateway"
    providers: ProviderCredentials = Field(default_factory=ProviderCredentials)
    # Config service base URL; derived from deploy/groups.yaml when unset.
    config_url: str | None = None
    # Which deployed profiles this data plane uses. Operator-controlled, never chosen by callers.
    profile_environment: Literal["dev", "staging", "prod"] = "dev"
    default_profile: str = "cloud-frontier"
    profile_cache_seconds: float = 60.0
    # Data of these classifications must never reach a cloud provider, whatever a profile says.
    cloud_forbidden_classifications: list[Classification] = Field(
        default_factory=lambda: list[Classification](["restricted"])
    )
    default_timeout_seconds: float = 60.0
    max_batch_inputs: int = 256
    max_rerank_documents: int = 200
    prices_file: Path | None = None  # overrides defaults/prices.yaml
    # Development only: serve the deterministic "offline" provider (not a language model).
    allow_offline_provider: bool = False
