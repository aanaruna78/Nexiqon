from typing import Any

from pydantic import Field

from nexiqon_core.settings import CoreSettings
from nexiqon_core.signing import SigningSettings


class ServiceSettings(CoreSettings):
    """Settings for config. Deployment/region layers and floors are operator-controlled."""

    service_name: str = "config"
    # Layer 2 and 3 of the resolution hierarchy, keyed like defaults/platform.yaml ("agent": {...}).
    deployment_layer: dict[str, Any] = Field(default_factory=dict)
    region_layers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Extra floors for this deployment, e.g. on-prem: model.chat.provider subset_of [openai_compatible].
    deployment_floors: list[dict[str, Any]] = Field(default_factory=list)
    # Signs configuration snapshots pulled by data planes (hybrid mode).
    snapshot_signing: SigningSettings = Field(default_factory=SigningSettings)
