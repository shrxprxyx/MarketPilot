"""Page speed through the PageSpeed Insights API (FR-AUD-04): the performance score and the lab
Core Web Vitals (LCP, CLS and TBT, the lab stand-in for INP) for mobile and desktop, for the home
page and the five most linked-to pages.

Google fetches the pages itself, so nothing here reaches a client's site. Without an API key the
step is skipped; a failed call is recorded on its row and never fails the audit."""
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from app.audit.checks import ok_page
from app.audit.crawler import CrawlResult

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
STRATEGIES = ("mobile", "desktop")
TOP_PAGES = 5
TIMEOUT_SECONDS = 90.0  # Lighthouse runs on Google's side and is slow

Progress = Callable[[int, int], Awaitable[None]]
ShouldStop = Callable[[], Awaitable[bool]]


@dataclass
class PageSpeedResult:
    url: str
    strategy: str
    score: int | None = None  # Lighthouse performance score, 0 to 100
    lcp_ms: float | None = None  # largest contentful paint
    cls: float | None = None  # cumulative layout shift
    tbt_ms: float | None = None  # total blocking time
    error: str | None = None


def pick_pages(crawl: CrawlResult) -> list[str]:
    """The home page, then the pages the most other pages link to (shallower first on a tie)."""
    ok = {url: rec for url, rec in crawl.pages.items() if ok_page(rec)}
    home = crawl.start_url if crawl.start_url in ok else next(iter(ok), None)
    if home is None:
        return []
    rest = sorted(
        (url for url in ok if url != home),
        key=lambda url: (-len(crawl.referrers.get(url, [])), ok[url].depth),
    )
    return [home, *rest[:TOP_PAGES]]


def _numeric(lighthouse: dict[str, Any], audit: str) -> float | None:
    value = (lighthouse.get("audits", {}).get(audit) or {}).get("numericValue")
    return float(value) if isinstance(value, (int, float)) else None


def _parse(url: str, strategy: str, body: dict[str, Any]) -> PageSpeedResult:
    lighthouse = body.get("lighthouseResult") or {}
    score = ((lighthouse.get("categories") or {}).get("performance") or {}).get("score")
    return PageSpeedResult(
        url=url,
        strategy=strategy,
        score=round(score * 100) if isinstance(score, (int, float)) else None,
        lcp_ms=_numeric(lighthouse, "largest-contentful-paint"),
        cls=_numeric(lighthouse, "cumulative-layout-shift"),
        tbt_ms=_numeric(lighthouse, "total-blocking-time"),
    )


async def _run_one(
    client: httpx.AsyncClient, api_key: str, url: str, strategy: str
) -> PageSpeedResult:
    try:
        resp = await client.get(
            ENDPOINT,
            params={"url": url, "strategy": strategy, "category": "performance", "key": api_key},
        )
    except httpx.TimeoutException:
        return PageSpeedResult(url, strategy, error="PageSpeed Insights timed out.")
    except httpx.HTTPError:
        return PageSpeedResult(url, strategy, error="PageSpeed Insights could not be reached.")
    if resp.status_code == 429:
        return PageSpeedResult(url, strategy, error="The PageSpeed Insights quota is used up.")
    if resp.status_code != 200:
        # Google's own message is kept (it names a bad key or an unreachable page). The request
        # URL, which holds the key, is never part of what is stored.
        try:
            reason = str(resp.json()["error"]["message"])[:300]
        except (ValueError, KeyError, TypeError):
            reason = f"HTTP {resp.status_code}"
        return PageSpeedResult(url, strategy, error=f"PageSpeed Insights refused: {reason}")
    try:
        return _parse(url, strategy, resp.json())
    except ValueError:
        return PageSpeedResult(url, strategy, error="PageSpeed Insights sent an unreadable answer.")


async def collect_pagespeed(
    crawl: CrawlResult,
    api_key: str,
    *,
    on_progress: Progress | None = None,
    should_stop: ShouldStop | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Returns what is stored in the audit summary: a status and one row per page and strategy.
    Stops early (keeping the rows so far) when `should_stop` says so."""
    if not api_key:
        return {"status": "skipped", "reason": "No PageSpeed Insights API key is configured.",
                "results": []}
    pages = pick_pages(crawl)
    jobs = [(url, strategy) for url in pages for strategy in STRATEGIES]
    results: list[PageSpeedResult] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        for done, (url, strategy) in enumerate(jobs):
            if should_stop is not None and await should_stop():
                break
            if on_progress is not None:
                await on_progress(done, len(jobs))
            results.append(await _run_one(client, api_key, url, strategy))
    return {"status": "done", "results": [asdict(r) for r in results]}
