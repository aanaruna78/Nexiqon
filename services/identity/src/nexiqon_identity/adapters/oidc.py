"""OIDC adapter: verifies IdP-issued JWTs (Clerk, Keycloak, Auth0, generic OIDC) via JWKS."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import jwt

from nexiqon_core.errors import ServiceUnavailable, Unauthorized
from nexiqon_identity.idp import IdentityClaims
from nexiqon_identity.settings import IdpProviderSettings

JwksFetcher = Callable[[str], Awaitable[dict[str, Any]]]
MFA_AMR = {"mfa", "otp", "hwk", "swk", "sms", "totp", "webauthn"}


async def http_fetch_jwks(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


class _JwksCache:
    def __init__(self, fetch: JwksFetcher, ttl: float = 600.0, min_refresh: float = 30.0) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._min_refresh = min_refresh
        self._keys: dict[str, dict[str, jwt.PyJWK]] = {}
        self._fetched_at: dict[str, float] = {}

    async def key(self, url: str, kid: str) -> jwt.PyJWK:
        now = time.monotonic()
        keys = self._keys.get(url, {})
        age = now - self._fetched_at.get(url, 0.0)
        # Refresh when stale, or on an unknown kid (key rotation) at most every min_refresh seconds.
        if age > self._ttl or (kid not in keys and age > self._min_refresh):
            try:
                raw = await self._fetch(url)
            except (httpx.HTTPError, ValueError) as exc:
                raise ServiceUnavailable("Identity provider keys unavailable") from exc
            keys = _signing_keys(raw)
            self._keys[url] = keys
            self._fetched_at[url] = now
        if kid not in keys:
            raise Unauthorized("Unknown signing key")
        return keys[kid]


def _signing_keys(raw: dict[str, Any]) -> dict[str, jwt.PyJWK]:
    """Signature keys only: IdPs (e.g. Keycloak) also publish encryption keys (use=enc)."""
    keys: dict[str, jwt.PyJWK] = {}
    for item in raw.get("keys", []):
        if not isinstance(item, dict) or "kid" not in item or item.get("use", "sig") != "sig":
            continue
        try:
            keys[str(item["kid"])] = jwt.PyJWK(item)
        except jwt.PyJWKError:
            continue  # unsupported key type/algorithm: ignore rather than fail every login
    return keys


class OidcVerifier:
    """Implements :class:`nexiqon_identity.idp.IdentityProvider` for any number of issuers."""

    def __init__(
        self, providers: list[IdpProviderSettings], fetch: JwksFetcher = http_fetch_jwks
    ) -> None:
        self._providers = {p.issuer.rstrip("/"): p for p in providers}
        self._jwks = _JwksCache(fetch)

    async def verify(self, token: str) -> IdentityClaims:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthorized("Malformed identity token") from exc
        provider = self._providers.get(str(unverified.get("iss", "")).rstrip("/"))
        if provider is None:
            raise Unauthorized("Untrusted identity provider")
        key = await self._jwks.key(provider.jwks_url, str(header.get("kid", "")))
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=provider.algorithms,
                issuer=unverified["iss"],
                audience=provider.audiences or None,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": bool(provider.audiences),
                },
                leeway=5,
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized("Invalid identity token") from exc
        if provider.authorized_parties and claims.get("azp") not in provider.authorized_parties:
            raise Unauthorized("Token not issued for this application")
        return _normalize(provider, claims)


def _normalize(p: IdpProviderSettings, claims: dict[str, Any]) -> IdentityClaims:
    email = claims.get(p.claim_email)
    org_ref = claims.get(p.claim_org) if p.claim_org else None
    if p.kind == "clerk":
        org = claims.get("o")  # Clerk session token v2
        if org_ref is None and isinstance(org, dict):
            org_ref = org.get("id")
        fva = claims.get("fva")
        mfa = isinstance(fva, list) and len(fva) == 2 and fva[1] != -1
    else:
        amr = claims.get("amr") or []
        mfa = bool(MFA_AMR.intersection(amr if isinstance(amr, list) else [amr])) or (
            claims.get("acr") in p.mfa_acr_values
        )
    return IdentityClaims(
        provider=p.name,
        issuer=str(claims["iss"]).rstrip("/"),
        subject=str(claims["sub"]),
        email=email.lower() if isinstance(email, str) else None,
        email_verified=claims.get(p.claim_email_verified) is True,
        name=claims.get(p.claim_name) if isinstance(claims.get(p.claim_name), str) else None,
        org_ref=str(org_ref) if org_ref else None,
        mfa=mfa,
        expires_at=int(claims["exp"]),
    )
