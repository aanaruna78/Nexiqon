"""Minimal Azure Blob Storage client (Shared Key authorization): the three calls Nexiqon needs.

Azure Blob does not speak the S3 API, so Azure installs (DV-03b) use this adapter instead:
``blobs.backend: azure``, ``endpoint: https://<account>.blob.core.windows.net``,
``access_key: <account>``, ``secret_key: <account key>``, ``bucket: <container>``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from email.utils import formatdate

import httpx

from nexiqon_core.blobs import BlobNotFound

API_VERSION = "2023-11-03"


def sign_shared_key(
    method: str,
    url: httpx.URL,
    headers: dict[str, str],
    *,
    account: str,
    key: str,
) -> str:
    """Return the Authorization header value (Shared Key, service version 2015-02-21 and later).
    ``headers`` holds every header sent, lower-cased, including x-ms-date and x-ms-version."""

    def h(name: str) -> str:
        return headers.get(name, "")

    length = h("content-length")
    canonical_headers = "".join(
        f"{k}:{v.strip()}\n" for k, v in sorted(headers.items()) if k.startswith("x-ms-")
    )
    resource = f"/{account}{url.path}"
    for name, value in sorted((k.lower(), v) for k, v in url.params.multi_items()):
        resource += f"\n{name}:{value}"
    to_sign = "\n".join(
        [
            method,
            h("content-encoding"),
            h("content-language"),
            "" if length == "0" else length,
            h("content-md5"),
            h("content-type"),
            "",  # Date: x-ms-date is used instead
            h("if-modified-since"),
            h("if-match"),
            h("if-none-match"),
            h("if-unmodified-since"),
            h("range"),
            canonical_headers + resource,
        ]
    )
    digest = hmac.new(base64.b64decode(key), to_sign.encode(), hashlib.sha256).digest()
    return f"SharedKey {account}:{base64.b64encode(digest).decode()}"


class AzureBlobError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Azure Blob {status}: {body[:300]}")
        self.status = status


class AzureBlobStore:
    def __init__(
        self,
        endpoint: str,
        account: str,
        key: str,
        container: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._account = account
        self._key = key
        self._container = container
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: bytes = b"",
        extra: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = httpx.URL(f"{self._endpoint}{path}", params=params or {})
        headers = {
            "x-ms-date": formatdate(usegmt=True),
            "x-ms-version": API_VERSION,
            "content-length": str(len(body)),
            **(extra or {}),
        }
        headers["authorization"] = sign_shared_key(
            method, url, headers, account=self._account, key=self._key
        )
        return await self._client.request(method, url, headers=headers, content=body)

    def _path(self, key: str = "") -> str:
        return f"/{self._container}/{key}" if key else f"/{self._container}"

    async def ensure(self) -> None:
        """Create the container if it does not exist (development and tests)."""
        r = await self._request("PUT", self._path(), params={"restype": "container"})
        if r.status_code not in (201, 409):
            raise AzureBlobError(r.status_code, r.text)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        r = await self._request(
            "PUT",
            self._path(key),
            body=data,
            extra={"x-ms-blob-type": "BlockBlob", "content-type": content_type},
        )
        if r.status_code != 201:
            raise AzureBlobError(r.status_code, r.text)

    async def get(self, key: str) -> bytes:
        r = await self._request("GET", self._path(key))
        if r.status_code == 404:
            raise BlobNotFound(key)
        if r.status_code != 200:
            raise AzureBlobError(r.status_code, r.text)
        return r.content

    async def delete(self, key: str) -> None:
        r = await self._request("DELETE", self._path(key))
        if r.status_code not in (202, 404):
            raise AzureBlobError(r.status_code, r.text)

    async def aclose(self) -> None:
        await self._client.aclose()
