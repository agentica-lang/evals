import asyncio
from urllib.parse import urlsplit


class NoResponse(Exception):
    pass


async def get(url: str, timeout_ms: int) -> tuple[int, bytes]:
    """One GET on a connection of its own; the status and the body, or NoResponse when the whole response did not
    arrive within timeout_ms."""
    try:
        return await exchange(url, timeout_ms)
    except (OSError, TimeoutError, asyncio.IncompleteReadError, ValueError) as exc:
        raise NoResponse() from exc


async def exchange(url: str, timeout_ms: int) -> tuple[int, bytes]:
    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    async with asyncio.timeout(timeout_ms / 1000) as limit:
        reader, writer = await asyncio.open_connection(parts.hostname, parts.port or 80)
        try:
            writer.write(f"GET {target} HTTP/1.1\r\nHost: {parts.netloc}\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            status, headers = parse_head(head)
            body = await read_body(reader, headers)
        finally:
            writer.close()
    return status, body


def parse_head(head: bytes) -> tuple[int, dict[str, str]]:
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers


async def read_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> bytes:
    if "content-length" in headers:
        return await reader.readexactly(int(headers["content-length"]))
    if headers.get("transfer-encoding", "").lower() == "chunked":
        return await read_chunks(reader)
    return await reader.read()


async def read_chunks(reader: asyncio.StreamReader) -> bytes:
    body = b""
    while True:
        size = int((await reader.readuntil(b"\r\n")).split(b";")[0], 16)
        if size == 0:
            await reader.readuntil(b"\r\n")
            return body
        body += await reader.readexactly(size)
        await reader.readexactly(2)
