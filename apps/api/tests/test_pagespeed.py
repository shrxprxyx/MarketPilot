"""PageSpeed Insights step (FR-AUD-04). Google is a MockTransport, so nothing touches the
network; the crawl behind it is the same mock site the engine tests use."""
import json
from typing import Any

import httpx

from app.audit.crawler import CrawlResult, crawl
from app.audit.pagespeed import STRATEGIES, collect_pagespeed, pick_pages
from tests.test_audit_engine import allow_all, fetcher, home

SECRET = "k-secret-123"
PAGES = {
    "/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
    # /missing is linked most but is a 404, so it can never be measured.
    "/": home("/a", "/b", "/c", "/d", "/e", "/f", "/g", "/missing"),
    "/a": home("/d", "/c", "/missing"),
    "/b": home("/d", "/missing"),
    "/c": home("/missing"),
    "/d": home(), "/e": home(), "/f": home(), "/g": home(),
    "/missing": httpx.Response(404, text="gone", headers={"content-type": "text/html"}),
}


async def _crawl() -> CrawlResult:
    assert allow_all  # the fetcher helper skips the DNS guard
    async with fetcher(dict(PAGES)) as f:
        return await crawl("https://acme.test", f)


def _lighthouse(score: float = 0.9, lcp: float = 1800.0) -> dict[str, Any]:
    return {
        "lighthouseResult": {
            "categories": {"performance": {"score": score}},
            "audits": {
                "largest-contentful-paint": {"numericValue": lcp},
                "cumulative-layout-shift": {"numericValue": 0.05},
                "total-blocking-time": {"numericValue": 120.0},
            },
        }
    }


def _google(handler: Any = None) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if handler is not None:
            return handler(request)
        return httpx.Response(200, json=_lighthouse())

    return httpx.MockTransport(respond), seen


async def test_it_measures_the_home_page_and_the_five_most_linked_pages() -> None:
    crawl_result = await _crawl()
    assert [u.removeprefix("https://acme.test") or "/" for u in pick_pages(crawl_result)] == [
        "/", "/d", "/c", "/a", "/b", "/e",
    ]


async def test_it_reads_the_score_and_core_web_vitals_for_both_strategies() -> None:
    transport, seen = _google()
    out = await collect_pagespeed(await _crawl(), SECRET, transport=transport)
    assert out["status"] == "done"
    assert len(out["results"]) == 6 * len(STRATEGIES)
    first = out["results"][0]
    assert first == {
        "url": "https://acme.test/", "strategy": "mobile", "score": 90, "lcp_ms": 1800.0,
        "cls": 0.05, "tbt_ms": 120.0, "error": None,
    }
    assert {r["strategy"] for r in out["results"]} == set(STRATEGIES)
    assert {r.url.params["strategy"] for r in seen} == set(STRATEGIES)
    assert all(r.url.params["key"] == SECRET for r in seen)


async def test_without_a_key_the_step_is_skipped_and_nothing_is_requested() -> None:
    transport, seen = _google()
    out = await collect_pagespeed(await _crawl(), "", transport=transport)
    assert out["status"] == "skipped"
    assert out["results"] == []
    assert out["reason"]
    assert seen == []


async def test_a_failed_call_is_recorded_on_its_row_and_the_rest_continue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url, strategy = request.url.params["url"], request.url.params["strategy"]
        if url.endswith("/d"):
            return httpx.Response(429, json={"error": {"message": "quota"}})
        if url.endswith("/c"):
            return httpx.Response(400, json={"error": {"message": "Lighthouse returned error"}})
        if url.endswith("/a"):
            raise httpx.ReadTimeout("slow", request=request)
        if url.endswith("/b"):
            return httpx.Response(200, text="<html>not json</html>")
        if url.endswith("/e") and strategy == "mobile":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_lighthouse(score=0.5))

    transport, _ = _google(handler)
    out = await collect_pagespeed(await _crawl(), SECRET, transport=transport)
    by_page = {
        (r["url"].removeprefix("https://acme.test"), r["strategy"]): r for r in out["results"]
    }
    assert "quota" in by_page[("/d", "mobile")]["error"]
    assert "Lighthouse returned error" in by_page[("/c", "desktop")]["error"]
    assert "timed out" in by_page[("/a", "mobile")]["error"]
    assert "unreadable" in by_page[("/b", "mobile")]["error"]
    assert "HTTP 500" in by_page[("/e", "mobile")]["error"]
    assert by_page[("/e", "desktop")]["score"] == 50  # the same page's other strategy still ran
    assert by_page[("/", "mobile")]["score"] == 50
    assert SECRET not in json.dumps(out)


async def test_a_result_without_lighthouse_data_has_empty_numbers_not_an_error() -> None:
    transport, _ = _google(lambda _r: httpx.Response(200, json={}))
    out = await collect_pagespeed(await _crawl(), SECRET, transport=transport)
    assert out["results"][0]["score"] is None
    assert out["results"][0]["error"] is None


async def test_it_reports_progress_and_stops_when_asked() -> None:
    transport, seen = _google()
    progress: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        progress.append((done, total))

    stop_after = 3

    async def should_stop() -> bool:
        return len(seen) >= stop_after

    out = await collect_pagespeed(
        await _crawl(), SECRET, transport=transport, on_progress=on_progress,
        should_stop=should_stop,
    )
    assert len(out["results"]) == stop_after
    assert progress == [(0, 12), (1, 12), (2, 12)]
