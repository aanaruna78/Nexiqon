from nexiqon_core.settings import CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for authz."""

    service_name: str = "authz"
    opa_url: str = "http://opa:8181"
    opa_decision_path: str = "nexiqon/authz/decision"
    opa_timeout_seconds: float = 1.0
