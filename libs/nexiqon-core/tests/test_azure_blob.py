"""Azure Blob adapter (DV-03b): Shared Key requests accepted by Azurite, Microsoft's emulator."""

from __future__ import annotations

import base64
import shutil
import uuid
from collections.abc import Iterator

import httpx
import pytest

from nexiqon_core.adapters.azure_blob import AzureBlobStore, sign_shared_key
from nexiqon_core.blobs import BlobNotFound, BlobSettings, create_blob_store, tenant_key

# Azurite's published development account (not a secret).
ACCOUNT = "devstoreaccount1"
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def test_the_signature_covers_the_resource_query_and_ms_headers() -> None:
    url = httpx.URL("https://acct.blob.core.windows.net/files/a.txt", params={"Comp": "x"})
    base = {"x-ms-date": "Wed, 19 Nov 2026 10:00:00 GMT", "x-ms-version": "2023-11-03"}
    a = sign_shared_key("GET", url, base, account="acct", key=KEY)
    assert a.startswith("SharedKey acct:")
    assert a == sign_shared_key("GET", url, dict(base), account="acct", key=KEY)
    other = httpx.URL("https://acct.blob.core.windows.net/files/b.txt", params={"Comp": "x"})
    assert a != sign_shared_key("GET", other, base, account="acct", key=KEY)
    assert a != sign_shared_key("GET", url, {**base, "x-ms-date": "x"}, account="acct", key=KEY)
    assert a != sign_shared_key("DELETE", url, base, account="acct", key=KEY)


def test_settings_choose_the_azure_adapter() -> None:
    store = create_blob_store(
        BlobSettings(
            backend="azure",
            endpoint="https://acct.blob.core.windows.net",
            bucket="files",
            access_key="acct",  # type: ignore[arg-type]
            secret_key=KEY,  # type: ignore[arg-type]
        )
    )
    assert isinstance(store, AzureBlobStore)
    with pytest.raises(ValueError, match="account"):
        create_blob_store(BlobSettings(backend="azure"))


@pytest.fixture(scope="module")
def azurite() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker not available")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    container = (
        DockerContainer("mcr.microsoft.com/azure-storage/azurite:3.37.0")
        .with_command("azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck --loose")
        .with_exposed_ports(10000)
    )
    with container:
        wait_for_logs(container, "successfully listens", timeout=60)
        host, port = container.get_container_host_ip(), container.get_exposed_port(10000)
        yield f"http://{host}:{port}/{ACCOUNT}"


@pytest.mark.integration
async def test_put_get_delete_against_azurite(azurite: str) -> None:
    store = AzureBlobStore(azurite, ACCOUNT, KEY, "nexiqon")
    await store.ensure()
    key = tenant_key(uuid.uuid4(), "documents", "d1", "raw")
    await store.put(key, b"hello azure", "text/plain")
    assert await store.get(key) == b"hello azure"
    await store.delete(key)
    with pytest.raises(BlobNotFound):
        await store.get(key)
    await store.delete(key)  # deleting twice is fine
    other_key = base64.b64encode(b"not the account key").decode()
    wrong = AzureBlobStore(azurite, ACCOUNT, other_key, "nexiqon")
    with pytest.raises(Exception, match="403"):
        await wrong.put(key, b"x", "text/plain")
    await store.aclose()
    await wrong.aclose()
