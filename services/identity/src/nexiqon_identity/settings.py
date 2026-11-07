from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from nexiqon_core.settings import CoreSettings


class IdpProviderSettings(BaseModel):
    """One trusted identity provider (Clerk, Keycloak, Auth0 or any OIDC issuer)."""

    name: str
    kind: Literal["clerk", "keycloak", "auth0", "oidc"]
    issuer: str
    jwks_url: str
    audiences: list[str] = Field(default_factory=list)  # empty: audience not checked
    authorized_parties: list[str] = Field(default_factory=list)  # Clerk `azp` allowlist
    algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    claim_email: str = "email"
    claim_email_verified: str = "email_verified"
    claim_name: str = "name"
    claim_org: str | None = None  # e.g. Clerk "org_id"
    mfa_acr_values: list[str] = Field(default_factory=list)


class SigningSettings(BaseModel):
    """Keys for tenant-context tokens. Old keys stay listed (in JWKS) during rotation."""

    active_kid: str = ""
    private_keys: dict[str, SecretStr] = Field(default_factory=dict)  # kid -> PEM


class ServiceSettings(CoreSettings):
    """Settings for identity."""

    service_name: str = "identity"
    idp_providers: list[IdpProviderSettings] = Field(default_factory=list)
    signing: SigningSettings = Field(default_factory=SigningSettings)
    context_ttl_seconds: int = 300
    context_cache_seconds: int = 30
    require_admin_mfa: bool = True
    clerk_webhook_secret: SecretStr | None = None
    jit_provisioning: bool = True
