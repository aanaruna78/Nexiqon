"""Malware scanning port (IN-05). Adapter: adapters/clamav.py (clamd INSTREAM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


class ScanSettings(BaseModel):
    backend: str = "clamav"  # clamav | none (development only: nothing is scanned)
    clamd_host: str = "clamav"
    clamd_port: int = 3310
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None
    scanner: str = "none"


class ScanUnavailable(Exception):
    """The scanner could not give a verdict. Callers must not treat content as clean."""


class Scanner(Protocol):
    name: str

    async def scan(self, data: bytes) -> ScanResult: ...


class NoScanner:
    """Development only: reports content as clean without scanning (recorded as scanner=none)."""

    name = "none"

    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=True, scanner=self.name)


def create_scanner(settings: ScanSettings) -> Scanner:
    if settings.backend == "clamav":
        from nexiqon_core.adapters.clamav import ClamdScanner

        return ClamdScanner(settings.clamd_host, settings.clamd_port, settings.timeout_seconds)
    if settings.backend == "none":
        return NoScanner()
    raise ValueError(f"unknown scan backend {settings.backend!r}")
