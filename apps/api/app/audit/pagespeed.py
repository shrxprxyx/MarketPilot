"""Page speed through the PageSpeed Insights API (FR-AUD-04, FR-AUD-05): the performance score
and the lab Core Web Vitals (LCP, CLS and TBT, the lab stand-in for INP) for mobile and desktop,
for the home page and the five most linked-to pages. Mobile-friendliness findings are extracted
from the Lighthouse result for the mobile run and returned as audit findings (FR-AUD-05).

Google fetches the pages itself, so nothing here reaches a client's site. Without an API key the
step is skipped; a failed call is recorded on its row and never fails the audit.
"""
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from app.audit.checks import Finding, ok_page
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
    score: int | None = None        # Lighthouse performance score, 0 to 100
    lcp_ms: float | None = None     # largest contentful paint
    cls: float | None = None        # cumulative layout shift
    tbt_ms: float | None = None     # total blocking time
    error: str | None = None


# ---------------------------------------------------------------------------
# Lighthouse mobile-friendliness audit mapping (FR-AUD-05)
# Each entry: lighthouse audit id -> (finding code, severity, title, recommendation)
# ---------------------------------------------------------------------------
_MOBILE_AUDITS: dict[str, tuple[str, str, str, str]] = {
    "viewport": (
        "lh_no_viewport",
        "high",
        "No mobile viewport tag",
        (
            "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            " to the <head>."
        ),
    ),
    "tap-targets": (
        "lh_tap_targets",
        "medium",
        "Tap targets are too small or too close together",
        "Make interactive elements at least 48 × 48 px with 8 px of padding between them.",
    ),
    "font-size": (
        "lh_font_size",
        "medium",
        "Text is too small to read on mobile",
        "Use a base font size of at least 16 px so users do not need to zoom.",
    ),
    "content-width": (
        "lh_content_width",
        "medium",
        "Content is wider than the screen",
        "Remove fixed widths and use relative units so the layout fits any viewport.",
    ),
    "uses-responsive-images": (
        "lh_responsive_images",
        "low",
        "Images are not sized for the device",
        "Use srcset or <picture> so mobile devices download appropriately sized images.",
    ),
    "image-aspect-ratio": (
        "lh_image_aspect_ratio",
        "low",
        "Images are displayed with an incorrect aspect ratio",
        "Set explicit width and height attributes on <img> tags to prevent layout shift.",
    ),
    "meta-viewport": (
        "lh_meta_viewport",
        "high",
        "Viewport meta tag disables user scaling",
        "Remove user-scalable=no and maximum-scale=1 from the viewport meta tag.",
    ),
}

# Lighthouse score threshold below which a scored audit is treated as failing.
# Unscored audits (score is None or -1) are always treated as informational only.
_FAIL_THRESHOLD = 0.9


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


def mobile_findings_from_response(url: str, body: dict[str, Any]) -> list[Finding]:
    """Extract failing Lighthouse mobile-friendliness audits from a PageSpeed API response
    and return them as Finding objects so they are stored with the crawl findings and
    contribute to the mobile category score (FR-AUD-05).

    Only audits that are both in _MOBILE_AUDITS and scored below _FAIL_THRESHOLD (or
    explicitly failed) are included. Audits the API did not return are skipped silently.
    """
    lighthouse = body.get("lighthouseResult") or {}
    lh_audits: dict[str, Any] = lighthouse.get("audits") or {}
    findings: list[Finding] = []

    for audit_id, (code, severity, title, recommendation) in _MOBILE_AUDITS.items():
        audit = lh_audits.get(audit_id)
        if audit is None:
            continue
        score_raw = audit.get("score")
        # score is 0–1 for scored audits, None or -1 for informational/not-applicable
        if score_raw is None or score_raw == -1:
            continue
        if float(score_raw) >= _FAIL_THRESHOLD:
            continue  # passing — no finding

        # Build a human-readable detail from the Lighthouse display value when available
        display = audit.get("displayValue") or ""
        description = audit.get("description") or ""
        # Strip markdown links from description (e.g. [Learn more](https://...))
        description = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", description)
        detail = display if display else description[:200] if description else title

        findings.append(
            Finding(
                code=code,
                category="mobile",
                severity=severity,
                title=title,
                detail=detail,
                recommendation=recommendation,
                url=url,
                metric={"lighthouse_score": round(float(score_raw) * 100)},
            )
        )

    return findings


async def _run_one(
    client: httpx.AsyncClient,
    api_key: str,
    url: str,
    strategy: str,
) -> tuple[PageSpeedResult, dict[str, Any]]:
    """Returns (PageSpeedResult, raw_body). raw_body is {} on error."""
    # For mobile we request performance + best-practices to get mobile-friendliness audits.
    categories = ["performance", "best-practices"] if strategy == "mobile" else ["performance"]
    params: dict[str, Any] = {"url": url, "strategy": strategy, "key": api_key}
    # httpx serialises list params correctly when passed as a list of tuples
    param_list = [(k, v) for k, v in params.items()]
    for cat in categories:
        param_list.append(("category", cat))

    try:
        resp = await client.get(ENDPOINT, params=param_list)
    except httpx.TimeoutException:
        return PageSpeedResult(url, strategy, error="PageSpeed Insights timed out."), {}
    except httpx.HTTPError:
        return PageSpeedResult(url, strategy, error="PageSpeed Insights could not be reached."), {}

    if resp.status_code == 429:
        return PageSpeedResult(url, strategy, error="The PageSpeed Insights quota is used up."), {}
    if resp.status_code != 200:
        try:
            reason = str(resp.json()["error"]["message"])[:300]
        except (ValueError, KeyError, TypeError):
            reason = f"HTTP {resp.status_code}"
        return PageSpeedResult(url, strategy, error=f"PageSpeed Insights refused: {reason}"), {}

    try:
        body = resp.json()
        return _parse(url, strategy, body), body
    except ValueError:
        return (
            PageSpeedResult(url, strategy, error="PageSpeed Insights sent an unreadable answer."),
            {},
        )


async def collect_pagespeed(
    crawl: CrawlResult,
    api_key: str,
    *,
    on_progress: Progress | None = None,
    should_stop: ShouldStop | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], list[Finding]]:
    """Returns (summary_dict, mobile_findings).

    summary_dict is what is stored in the audit summary JSONB (status + results).
    mobile_findings are Finding objects extracted from the mobile Lighthouse run;
    runner.py merges them into the main findings list before scoring.
    """
    if not api_key:
        return (
            {
                "status": "skipped",
                "reason": "No PageSpeed Insights API key is configured.",
                "results": [],
            },
            [],
        )

    pages = pick_pages(crawl)
    jobs = [(url, strategy) for url in pages for strategy in STRATEGIES]
    results: list[PageSpeedResult] = []
    mobile_findings: list[Finding] = []

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        for done, (url, strategy) in enumerate(jobs):
            if should_stop is not None and await should_stop():
                break
            if on_progress is not None:
                await on_progress(done, len(jobs))
            result, body = await _run_one(client, api_key, url, strategy)
            results.append(result)
            # Extract mobile-friendliness findings from the mobile run only
            if strategy == "mobile" and body:
                mobile_findings.extend(mobile_findings_from_response(url, body))

    summary: dict[str, Any] = {"status": "done", "results": [asdict(r) for r in results]}
    return summary, mobile_findings