from pathlib import Path

from nexiqon_core.settings import CoreSettings, ServiceIdentitySettings


class ServiceSettings(CoreSettings):
    """Settings for evaluation."""

    service_name: str = "evaluation"
    # Evaluation's own signing key (ADR 0017). Its own field, not ``service_identity``: other
    # services in the same deployment group may sign as themselves.
    evaluation_identity: ServiceIdentitySettings = ServiceIdentitySettings()
    # Service URLs; derived from deploy/groups.yaml when unset.
    agent_runtime_url: str | None = None
    config_url: str | None = None
    task_queue: str = "evaluation"
    run_worker: bool = True  # run the Temporal worker in this process when workflows are enabled
    worker_max_cached_workflows: int = 1000
    concurrency: int = 4  # cases asked at once per run
    max_cases: int = 500  # per test set
    case_timeout_seconds: int = 120
    # Gate defaults when an assistant's release gate does not set its own (QA-02).
    gate_min_pass_rate: float = 0.8
    gate_max_drop: float = 0.05
    # Ready-made Domain Packs: <dir>/<name>/eval/gold.yaml seeds a test set.
    pack_gallery_dir: Path = Path("packs")
