"""Object storage port (raw uploaded/fetched files). Adapters: adapters/s3.py; memory for tests.

Keys are always tenant-prefixed through :func:`tenant_key`, so one tenant's key can never name
another tenant's object.
"""

from __future__ import annotations

import re
import uuid
from typing import Protocol

from pydantic import BaseModel, SecretStr

_SAFE = re.compile(r"^[A-Za-z0-9._/-]{1,900}$")


class BlobSettings(BaseModel):
    backend: str = "memory"  # memory | s3
    endpoint: str = "http://seaweedfs:8333"
    region: str = "us-east-1"
    bucket: str = "nexiqon"
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class BlobNotFound(Exception):
    pass


def tenant_key(tenant_id: uuid.UUID, *parts: str) -> str:
    key = "/".join(["t", str(tenant_id), *parts])
    if not _SAFE.match(key) or ".." in key:
        raise ValueError("unsafe blob key")
    return key


class MemoryBlobStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise BlobNotFound(key) from None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def create_blob_store(settings: BlobSettings) -> BlobStore:
    if settings.backend == "s3":
        from nexiqon_core.adapters.s3 import S3BlobStore, S3Client

        if settings.access_key is None or settings.secret_key is None:
            raise ValueError("S3 blob storage needs access_key and secret_key")
        client = S3Client(
            settings.endpoint,
            settings.region,
            settings.access_key.get_secret_value(),
            settings.secret_key.get_secret_value(),
        )
        return S3BlobStore(client, settings.bucket)
    if settings.backend == "memory":
        return MemoryBlobStore()
    raise ValueError(f"unknown blob backend {settings.backend!r}")
