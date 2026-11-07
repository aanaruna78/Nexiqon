"""flagd adapter for OpenFeature (vendor SDK kept behind the flags port)."""

from __future__ import annotations

from openfeature.contrib.provider.flagd import FlagdProvider
from openfeature.provider import AbstractProvider


def flagd_provider(host: str, port: int) -> AbstractProvider:
    return FlagdProvider(host=host, port=port)
