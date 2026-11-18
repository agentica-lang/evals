import asyncio
from urllib.parse import urlsplit


class NoResponse(Exception):
    pass


async def get(url: str, timeout_ms: int) -> tuple[int, bytes]:
    """One GET on a connection of its own; the status and the body, or NoResponse."""
    try:
        return await asyncio.wait_for(exchange(url), timeout_ms / 1000)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError) as exc:
        raise NoResponse() from exc


async def exchange(url: str) -> tuple[int, bytes]:
    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    reader, writer = await asyncio.open_connection(parts.hostname, parts.port or 80)
    try:
        writer.write(f"GET {target} HTTP/1.1\r\nHost: {parts.netloc}\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split(" ")[1])
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        if "content-length" in headers:
            body = await reader.readexactly(int(headers["content-length"]))
        elif headers.get("transfer-encoding", "").lower() == "chunked":
            body = await read_chunks(reader)
        else:
            body = await reader.read()
        return status, body
    finally:
        writer.close()


async def read_chunks(reader: asyncio.StreamReader) -> bytes:
    body = b""
    while True:
        size = int((await reader.readuntil(b"\r\n")).split(b";")[0], 16)
        if size == 0:
            await reader.readuntil(b"\r\n")
            return body
        body += await reader.readexactly(size)
        await reader.readexactly(2)
