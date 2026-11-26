"""SSRF-safe HTTP fetching for the audit crawler (FR-AUD-01, FR-AUD-07).

Every hop, including each redirect target, is checked against the SSRF guard before a request
is made. Redirects are followed by hand so the whole chain is recorded and loops are caught.
Responses are size-limited and only text-like content types are read. Requests to one host are
spaced out (default 1 per second)."""
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import settings
from app.core.ssrf import UnsafeDestination, check_destination

USER_AGENT = "MarketPilotBot/1.0 (+site audit)"
TIMEOUT_SECONDS = 10.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
MIN_INTERVAL_SECONDS = 1.0
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/xml", "application/xml")

Check = Callable[[str], Awaitable[None]]


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None = None
    chain: list[tuple[str, int]] = field(default_factory=list)  # (url, status) per redirect hop
    content_type: str | None = None
    body: str | None = None
    # timeout, network, blocked, too_large, redirect_loop, too_many_redirects
    error: str | None = None
    elapsed_ms: int = 0


async def _default_check(url: str) -> None:
    await check_destination(url, allow_private=settings.allow_private_base_urls)


class SafeFetcher:
    def __init__(
        self,
        *,
        check: Check = _default_check,
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval: float = MIN_INTERVAL_SECONDS,
        timeout: float = TIMEOUT_SECONDS,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self._check = check
        self._min_interval = min_interval
        self._max_bytes = max_bytes
        self._next_slot: dict[str, float] = {}
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "SafeFetcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _throttle(self, host: str) -> None:
        """Reserve this host's next request slot before sleeping, so concurrent callers queue
        up instead of all waking at once."""
        now = time.monotonic()
        slot = max(now, self._next_slot.get(host, 0.0))
        self._next_slot[host] = slot + self._min_interval
        if slot > now:
            await asyncio.sleep(slot - now)

    async def fetch(self, url: str, *, read_body: bool = True) -> FetchResult:
        """GET `url`. With `read_body=False` only the status is wanted (link checking), so the
        body is never downloaded."""
        result = FetchResult(url=url, final_url=url)
        started = time.monotonic()
        current = url
        seen = {url}
        try:
            for _ in range(MAX_REDIRECTS + 1):
                try:
                    await self._check(current)
                except UnsafeDestination:
                    result.error = "blocked"
                    return result
                await self._throttle(urlsplit(current).netloc.lower())
                async with self._http.stream("GET", current) as resp:
                    result.final_url, result.status = current, resp.status_code
                    location = resp.headers.get("location")
                    if resp.is_redirect and location:
                        result.chain.append((current, resp.status_code))
                        current = urljoin(current, location)
                        if current in seen:
                            result.error = "redirect_loop"
                            return result
                        seen.add(current)
                        continue
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    result.content_type = ctype or None
                    if read_body and ctype in TEXT_TYPES:
                        await self._read(resp, result)
                    return result
            result.error = "too_many_redirects"
            return result
        except httpx.TimeoutException:
            result.error = "timeout"
            return result
        except httpx.HTTPError:
            result.error = "network"
            return result
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)

    async def _read(self, resp: httpx.Response, result: FetchResult) -> None:
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            result.error = "too_large"
            return
        data = bytearray()
        async for chunk in resp.aiter_bytes():
            data.extend(chunk)
            if len(data) > self._max_bytes:
                result.error = "too_large"
                return
        result.body = bytes(data).decode(resp.encoding or "utf-8", errors="replace")
