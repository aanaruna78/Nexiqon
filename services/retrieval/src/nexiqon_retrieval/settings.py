from pydantic import Field

from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for retrieval."""

    service_name: str = "retrieval"
    # Service URLs; derived from deploy/groups.yaml when unset.
    config_url: str | None = None
    model_gateway_url: str | None = None
    profile_environment: str = "dev"
    default_retrieval_profile: str = "standard"
    default_model_profile: str = "cloud-frontier"
    # Roles that see every collection's content regardless of its access groups (Playground, audits).
    acl_bypass_roles: list[str] = Field(default_factory=lambda: ["owner", "admin"])
    # Highest data classification an actor type may retrieve (public < internal < confidential
    # < restricted). Unlisted actor types have no limit beyond access groups.
    max_classification: dict[str, str] = Field(default_factory=lambda: {"widget": "internal"})
    hnsw_ef_search: int = 100
