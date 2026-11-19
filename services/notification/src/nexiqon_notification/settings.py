from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from nexiqon_core.fetch import FetchPolicy
from nexiqon_core.settings import CoreSettings


class EmailSettings(BaseModel):
    """Outgoing email. ``memory`` keeps messages in the process (tests, dev without a relay)."""

    backend: Literal["smtp", "memory"] = "memory"
    host: str = "localhost"
    port: int = 587
    starttls: bool = True
    username: str | None = None
    password: SecretStr | None = None
    sender: str = "Nexiqon <no-reply@nexiqon.local>"
    timeout_seconds: float = 15.0


class ServiceSettings(CoreSettings):
    """Settings for notification."""

    service_name: str = "notification"
    email: EmailSettings = Field(default_factory=EmailSettings)
    # A tenant may send at most this many emails per hour (abuse ceiling, not a quota).
    max_emails_per_hour: int = 200
    # And at most this many to one address per hour, so a form that sends copies (transcripts)
    # cannot be turned against someone's inbox.
    max_emails_per_recipient_per_hour: int = 3
    # Webhooks (NT-01): public HTTPS endpoints only, unless the operator allows more.
    webhooks: FetchPolicy = Field(
        default_factory=lambda: FetchPolicy(allowed_schemes=["https"], allowed_ports=[443, 8443])
    )
    webhook_retry_seconds: float = 30.0  # how often due retries are sent (0 disables the loop)
