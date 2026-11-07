import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from nexiqon_core.errors import ServiceUnavailable, Unauthorized
from nexiqon_identity.adapters.oidc import OidcVerifier, _signing_keys
from nexiqon_identity.settings import IdpProviderSettings
from nexiqon_identity.testing import FakeIdp

ENC_KEY = {"kid": "enc-1", "kty": "RSA", "alg": "RSA-OAEP", "use": "enc", "n": "AQAB", "e": "AQAB"}


def test_encryption_and_unsupported_keys_are_ignored() -> None:
    sig = json.loads(ECAlgorithm.to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key()))
    sig.update(kid="sig-1")
    weird = {"kid": "weird", "kty": "oct", "alg": "nope", "k": "AAAA"}
    assert set(_signing_keys({"keys": [ENC_KEY, sig, weird]})) == {"sig-1"}


async def test_keycloak_style_jwks_verifies() -> None:
    idp = FakeIdp("https://kc.example.com/realms/x")
    jwks = idp.jwks()
    jwks["keys"].append(ENC_KEY)

    async def fetch(_: str) -> dict[str, object]:
        return jwks

    provider = IdpProviderSettings(
        name="kc", kind="keycloak", issuer=idp.issuer, jwks_url="mem://kc"
    )
    claims = await OidcVerifier([provider], fetch).verify(idp.user("u1", "u1@example.com"))
    assert (claims.subject, claims.email, claims.mfa) == ("u1", "u1@example.com", True)


async def test_jwks_outage_is_503_not_500() -> None:
    import httpx

    idp = FakeIdp("https://kc.example.com/realms/y")

    async def fetch(_: str) -> dict[str, object]:
        raise httpx.ConnectError("down")

    provider = IdpProviderSettings(
        name="kc", kind="keycloak", issuer=idp.issuer, jwks_url="mem://kc"
    )
    with pytest.raises(ServiceUnavailable):
        await OidcVerifier([provider], fetch).verify(idp.user("u1"))
    with pytest.raises(Unauthorized):
        await OidcVerifier([provider], fetch).verify("not-a-token")
