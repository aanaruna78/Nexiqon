"""Minimal S3 API client (AWS Signature V4, path-style): works with AWS S3, DigitalOcean Spaces,
SeaweedFS, MinIO and other S3-compatible stores. Only the calls Nexiqon needs."""

from __future__ import annotations

import hashlib
import hmac
import xml.etree.ElementTree as ET  # parses S3 list responses only; expat ignores external entities
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from nexiqon_core.blobs import BlobNotFound

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_v4(
    method: str,
    url: httpx.URL,
    headers: dict[str, str],
    payload_hash: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
    service: str = "s3",
) -> str:
    """Return the Authorization header value. ``headers`` must include host and x-amz-* headers."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    canonical_uri = quote(url.path or "/", safe="/-_.~")
    query = sorted(
        (quote(k, safe="-_.~"), quote(v, safe="-_.~")) for k, v in url.params.multi_items()
    )
    canonical_query = "&".join(f"{k}={v}" for k, v in query)
    names = sorted(h.lower() for h in headers)
    lowered = {k.lower(): " ".join(v.strip().split()) for k, v in headers.items()}
    canonical_headers = "".join(f"{n}:{lowered[n]}\n" for n in names)
    signed = ";".join(names)
    canonical = "\n".join(
        [method, canonical_uri, canonical_query, canonical_headers, signed, payload_hash]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(
        _hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request"
    )
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}"


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    etag: str
    last_modified: str


class S3Error(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"S3 HTTP {status}: {message[:200]}")
        self.status = status


class S3Client:
    def __init__(
        self,
        endpoint: str,
        region: str,
        access_key: str,
        secret_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._region = region
        self._access = access_key
        self._secret = secret_key
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
        now = datetime.now(UTC)
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        headers = {
            "host": url.netloc.decode(),
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
            **(extra or {}),
        }
        headers["authorization"] = sign_v4(
            method,
            url,
            headers,
            payload_hash,
            access_key=self._access,
            secret_key=self._secret,
            region=self._region,
            now=now,
        )
        return await self._client.request(method, url, headers=headers, content=body or None)

    @staticmethod
    def _path(bucket: str, key: str = "") -> str:
        return f"/{bucket}/{key}" if key else f"/{bucket}"

    async def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        r = await self._request(
            "PUT", self._path(bucket, key), body=data, extra={"content-type": content_type}
        )
        if r.status_code >= 300:
            raise S3Error(r.status_code, r.text)

    async def get_object(self, bucket: str, key: str) -> bytes:
        r = await self._request("GET", self._path(bucket, key))
        if r.status_code == 404:
            raise BlobNotFound(key)
        if r.status_code >= 300:
            raise S3Error(r.status_code, r.text)
        return r.content

    async def delete_object(self, bucket: str, key: str) -> None:
        r = await self._request("DELETE", self._path(bucket, key))
        if r.status_code >= 300 and r.status_code != 404:
            raise S3Error(r.status_code, r.text)

    async def create_bucket(self, bucket: str) -> None:
        r = await self._request("PUT", self._path(bucket))
        if r.status_code >= 300 and r.status_code != 409:
            raise S3Error(r.status_code, r.text)

    async def list_objects(
        self, bucket: str, prefix: str = "", limit: int = 10_000
    ) -> list[S3Object]:
        objects: list[S3Object] = []
        token: str | None = None
        while len(objects) < limit:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            r = await self._request("GET", self._path(bucket), params=params)
            if r.status_code >= 300:
                raise S3Error(r.status_code, r.text)
            root = ET.fromstring(r.content)  # noqa: S314 - S3 XML; no DTD/entity expansion used
            ns = NS if root.tag.startswith(NS) else ""
            for item in root.findall(f"{ns}Contents"):
                objects.append(
                    S3Object(
                        key=item.findtext(f"{ns}Key", ""),
                        size=int(item.findtext(f"{ns}Size", "0")),
                        etag=item.findtext(f"{ns}ETag", "").strip('"'),
                        last_modified=item.findtext(f"{ns}LastModified", ""),
                    )
                )
            if root.findtext(f"{ns}IsTruncated", "false") != "true":
                break
            token = root.findtext(f"{ns}NextContinuationToken")
            if not token:
                break
        return objects[:limit]

    async def aclose(self) -> None:
        await self._client.aclose()


class S3BlobStore:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    async def ensure(self) -> None:
        """Create the bucket if missing (development stacks; production buckets come from IaC)."""
        await self.client.create_bucket(self.bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self.client.put_object(self.bucket, key, data, content_type)

    async def get(self, key: str) -> bytes:
        return await self.client.get_object(self.bucket, key)

    async def delete(self, key: str) -> None:
        await self.client.delete_object(self.bucket, key)
