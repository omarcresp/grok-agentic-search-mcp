"""Fetch real evidence directly, without another model or search provider."""

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from .extractor import MAX_BYTES
from .extractor import MAX_TEXT as MAX_TEXT
from .extractor import extract_text as extract_text
from .extractor import normalize_text as normalize_text
from .models import SearchOptions, Source


def public_ip(host: str) -> bool:
    address = ipaddress.ip_address(host.split("%")[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not (address.is_multicast or address.is_reserved)


def canonical_url(url: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("Control characters in URL")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("https", "http") or not host or parts.username or parts.password:
        raise ValueError("Only public HTTP(S) URLs without credentials can be read")
    if parts.port not in (None, 80, 443):
        raise ValueError("Only HTTP(S) ports 80 and 443 can be read")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        host = host.encode("idna").decode("ascii")
    else:
        if not public_ip(host):
            raise ValueError("Non-public address blocked")
    netloc = f"[{host}]" if ":" in host else host
    if parts.port and parts.port != (443 if parts.scheme == "https" else 80):
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def urls_in_query(query: str) -> list[str]:
    return list(
        dict.fromkeys(u.rstrip(".,;:!?)]}>") for u in re.findall(r'https?://[^\s<>"\x27]+', query))
    )


class SourcePolicy:
    def __init__(self, options: SearchOptions):
        self.options = options

    def allows(self, url: str) -> bool:
        parts = urlsplit(canonical_url(url))
        host = parts.hostname
        o = self.options
        if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com"):
            handle = parts.path.strip("/").split("/")[0].lower()
            return (
                o.include_x
                and (not o.allowed_x_handles or handle in o.allowed_x_handles)
                and handle not in o.excluded_x_handles
            )
        if host == "t.co":
            # Redirect ownership cannot establish an X author; resolve primary URLs instead.
            return False

        def matches(domain: str) -> bool:
            return host == domain or host.endswith("." + domain)

        return (not o.allowed_domains or any(matches(d) for d in o.allowed_domains)) and not any(
            matches(d) for d in o.excluded_domains
        )


class PublicResolver(AbstractResolver):
    """Validate the exact DNS results used by the connector, avoiding a preflight DNS race."""

    def __init__(self):
        self.delegate = DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await self.delegate.resolve(host, port, family)
        if not addresses or any(not public_ip(a["host"]) for a in addresses):
            raise OSError("Non-public DNS result blocked")
        return addresses

    async def close(self):
        await self.delegate.close()


async def extract_in_process(body: bytes, media_type: str) -> tuple[str, str, bool]:
    # Parser cancellation must stop actual work, not leave a CPU-bound thread running.
    # Neither source bytes nor URLs are executable command arguments; no shell is used.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("extractor.py")),
        media_type,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=256 * 1024,
        env={
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")
        },
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(input=body), timeout=5)
        if process.returncode != 0:
            raise ValueError("Source parser failed or exceeded resource limits")
        title, text, truncated = json.loads(output)
        return title, text, truncated
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class SourceReader:
    def __init__(self, policy: SourcePolicy):
        self.policy = policy
        self.session = None
        self.resolver = None
        self.semaphore = asyncio.Semaphore(4)

    async def __aenter__(self):
        self.resolver = PublicResolver()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=self.resolver, limit=4),
            timeout=aiohttp.ClientTimeout(total=20),
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": "GrokSearchMCP/0.2 (research evidence reader)"},
        )
        return self

    async def __aexit__(self, *_):
        await self.session.close()
        await self.resolver.close()

    async def read(self, url: str) -> Source:
        source = Source(
            id="s_" + hashlib.sha256(url.encode()).hexdigest()[:16], requested_url=url, url=url
        )
        try:
            async with self.semaphore:
                # One deadline includes redirects and parsing, rather than resetting at each hop.
                await asyncio.wait_for(self._read(source), timeout=25)
        except (ValueError, OSError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            source.error = f"Source unavailable ({type(exc).__name__}): {str(exc)[:160]}"
        except Exception as exc:
            source.error = f"Source could not be parsed ({type(exc).__name__})"
        return source

    async def _read(self, source: Source) -> None:
        url = canonical_url(source.requested_url)
        for _ in range(6):
            # Re-check policy and literal IPs at every redirect; resolver checks the connected IPs.
            url = canonical_url(url)
            if not self.policy.allows(url):
                raise ValueError("URL excluded by source policy")
            async with self.session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect missing location")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                media_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                if media_type not in (
                    "text/html",
                    "application/xhtml+xml",
                    "application/pdf",
                    "text/plain",
                    "text/markdown",
                    "application/json",
                ):
                    raise ValueError(f"Unsupported content type: {media_type or 'unknown'}")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError("Source exceeds 2 MiB read limit")
                title, text, truncated = await extract_in_process(bytes(body), media_type)
                if len(text) < 80:
                    raise ValueError("Insufficient readable source text")
                source.url = url
                source.id = "s_" + hashlib.sha256(url.encode()).hexdigest()[:16]
                source.title = title or urlsplit(url).hostname
                source.media_type = media_type
                source.text = text
                source.truncated = truncated
                source.content_hash = hashlib.sha256(text.encode()).hexdigest()
                source.status = "read"
                return
        raise ValueError("Too many redirects")
