"""Offline licence (DV-06): a signed statement of who may run this installation, until when, and
for how many organizations. Verified with the vendor's public key only, so it works without any
network access (air-gapped installs).

Format: a compact JWS (ES256) whose claims are :class:`Licence`. The vendor issues it with
``tools/licence/issue.py``; the installation reads it from ``licence.file`` or ``licence.token``.

Policy, applied by identity (ADR 0027):
* invalid or missing (when required): identity does not start;
* ``expiring`` (30 days or less left) and ``grace`` (expired, within ``grace_days``): everything
  works, and admins see the status;
* ``expired`` (after the grace period): staff can no longer sign in; widgets and API keys keep
  answering, so the customer's own users are never cut off by a renewal delay.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import jwt
from pydantic import BaseModel, Field, SecretStr

Status = Literal["unlicensed", "valid", "expiring", "grace", "expired"]
EXPIRING_DAYS = 30


class LicenceInvalid(Exception):
    pass


class Licence(BaseModel):
    id: str
    customer: str
    issued: date
    expires: date
    grace_days: int = 30
    max_tenants: int | None = None  # None: unlimited
    deployment: Literal["private", "air-gapped", "hybrid", "any"] = "any"
    features: list[str] = Field(default_factory=list)

    def status(self, today: date | None = None) -> Status:
        today = today or datetime.now(UTC).date()
        if today <= self.expires - timedelta(days=EXPIRING_DAYS):
            return "valid"
        if today <= self.expires:
            return "expiring"
        if today <= self.expires + timedelta(days=self.grace_days):
            return "grace"
        return "expired"


class LicenceSettings(BaseModel):
    """``required``: identity refuses to start without a valid licence (private and air-gapped
    profiles). ``public_keys``: the vendor's licence verification keys (kid -> PEM)."""

    required: bool = False
    file: Path | None = None
    token: SecretStr | None = None
    public_keys: dict[str, str] = Field(default_factory=dict)


def issue(licence: Licence, private_pem: str, kid: str) -> str:
    """Vendor side: sign a licence."""
    return jwt.encode(
        {**licence.model_dump(mode="json"), "typ": "nexiqon-licence"},
        private_pem,
        algorithm="ES256",
        headers={"kid": kid},
    )


def verify(token: str, public_keys: dict[str, str]) -> Licence:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as exc:
        raise LicenceInvalid("The licence is not a signed licence file") from exc
    key = public_keys.get(str(kid))
    if key is None:
        raise LicenceInvalid(f"The licence was signed with an unknown key ({kid})")
    try:
        claims = jwt.decode(token, key, algorithms=["ES256"], options={"require": ["typ"]})
    except jwt.PyJWTError as exc:
        raise LicenceInvalid("The licence signature does not verify") from exc
    if claims.pop("typ") != "nexiqon-licence":
        raise LicenceInvalid("Not a Nexiqon licence")
    return Licence.model_validate(claims)


def load(settings: LicenceSettings) -> Licence | None:
    """The installation's licence, verified; ``None`` when none is configured and none is required.
    Raises :class:`LicenceInvalid` when one is configured but does not verify, or one is required
    and missing."""
    token = settings.token.get_secret_value() if settings.token else None
    if token is None and settings.file is not None:
        if not settings.file.exists():
            raise LicenceInvalid(f"Licence file {settings.file} not found")
        token = settings.file.read_text().strip()
    if not token:
        if settings.required:
            raise LicenceInvalid("This installation needs a licence (licence.file)")
        return None
    return verify(token, settings.public_keys)
