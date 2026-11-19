from pathlib import Path
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
    # Ready-made Domain Packs offered in Studio's setup guide (ST-13): <dir>/<name>/pack.yaml.
    pack_gallery_dir: Path = Path("packs")
    # Safe publish (QA-02): the evaluation service answers release-gate checks; derived from
    # deploy/groups.yaml when unset. A gated version is compared with the one live here.
    evaluation_url: str | None = None
    gate_baseline_environment: str = "dev"
