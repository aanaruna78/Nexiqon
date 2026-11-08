"""ClamAV adapter speaking the clamd INSTREAM protocol over TCP."""

from __future__ import annotations

import asyncio
import struct

from nexiqon_core.scanning import ScanResult, ScanUnavailable

CHUNK = 64 * 1024


class ClamdScanner:
    name = "clamav"

    def __init__(self, host: str, port: int, timeout: float = 60.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    async def scan(self, data: bytes) -> ScanResult:
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(self._host, self._port)
                try:
                    writer.write(b"zINSTREAM\0")
                    for i in range(0, len(data), CHUNK):
                        part = data[i : i + CHUNK]
                        writer.write(struct.pack("!L", len(part)) + part)
                        await writer.drain()
                    writer.write(struct.pack("!L", 0))
                    await writer.drain()
                    reply = (await reader.read(4096)).rstrip(b"\0").decode(errors="replace").strip()
                finally:
                    writer.close()
        except (TimeoutError, OSError) as exc:
            raise ScanUnavailable(f"clamd unavailable: {exc}") from exc
        # "stream: OK" | "stream: <Signature> FOUND" | "... ERROR"
        if reply.endswith("OK"):
            return ScanResult(clean=True, scanner=self.name)
        if reply.endswith("FOUND"):
            signature = reply.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanResult(clean=False, signature=signature, scanner=self.name)
        raise ScanUnavailable(f"clamd error: {reply[:200]}")
