from pathlib import Path

from pydantic import Field

from nexiqon_core.blobs import BlobSettings
from nexiqon_core.fetch import FetchPolicy
from nexiqon_core.scanning import ScanSettings
from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for ingestion."""

    service_name: str = "ingestion"
    blobs: BlobSettings = Field(default_factory=BlobSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    fetch: FetchPolicy = Field(default_factory=FetchPolicy)
    # Service URLs; derived from deploy/groups.yaml when unset.
    config_url: str | None = None
    model_gateway_url: str | None = None
    retrieval_url: str | None = None
    profile_environment: str = "dev"
    task_queue: str = "ingestion"
    run_worker: bool = True  # run the Temporal worker in this process when workflows are enabled
    # Sticky workflow cache (Temporal default 1000). 0 disables it (tests restarting workers).
    worker_max_cached_workflows: int = 1000
    scratch_dir: Path = Path("/tmp/nexiqon-ingestion")  # noqa: S108 - per-run subdirectories
    max_upload_bytes: int = 50 * 1024 * 1024
    max_items_per_sync: int = 5000
    embed_batch_size: int = 64
    concurrency: int = 4
    # Operator-provisioned connector secrets, keyed "<tenant_id>/<name>" (from OpenBao in production).
    connector_credentials: dict[str, dict[str, str]] = Field(default_factory=dict)
