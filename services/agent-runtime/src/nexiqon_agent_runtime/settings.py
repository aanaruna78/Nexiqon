from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for agent-runtime."""

    service_name: str = "agent-runtime"
    # Service URLs; derived from deploy/groups.yaml when unset.
    config_url: str | None = None
    ingestion_url: str | None = None
    retrieval_url: str | None = None
    model_gateway_url: str | None = None
    tool_gateway_url: str | None = None
    agent_environment: str = "dev"
    agent_cache_seconds: float = 30.0
    max_steps: int = 40  # LangGraph recursion limit per run (stops loops between nodes)
    run_timeout_seconds: float = 120.0
    history_messages: int = 12
