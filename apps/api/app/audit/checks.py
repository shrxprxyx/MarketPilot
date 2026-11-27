"""Turns a crawl into findings (FR-AUD-02, FR-AUD-03, and the viewport part of FR-AUD-05).

Each finding has a stable `code` so two audits can be compared later (new / fixed / unchanged
is keyed on code + url). Everything here is deterministic; no model is involved."""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.audit.crawler import HTML_TYPES, CrawlResult, PageRecord

SEVERITIES = ("critical", "high", "medium", "low")
CATEGORIES = ("technical", "on_page", "links", "mobile")

TITLE_RANGE = (30, 60)
DESCRIPTION_RANGE = (70, 160)
REDIRECT_CHAIN_LIMIT = 2  # hops; a single redirect is normal


@dataclass
class Finding:
    code: str
    category: str
    severity: str
    title: str
    detail: str
    recommendation: str
    url: str | None = None
    metric: dict[str, Any] = field(default_factory=dict)


def ok_page(rec: PageRecord) -> bool:
    return (
        rec.data is not None
        and rec.fetch.status is not None
        and 200 <= rec.fetch.status < 300
        and rec.fetch.content_type in HTML_TYPES
    )


def run_checks(crawl: CrawlResult) -> list[Finding]:
    findings: list[Finding] = []
    findings += _site_checks(crawl)
    findings += _fetch_problems(crawl)
    findings += _redirects(crawl)
    findings += _link_checks(crawl)
    html_pages = [r for r in crawl.pages.values() if ok_page(r)]
    for rec in html_pages:
        findings += _on_page(rec)
    findings += _duplicate_titles(html_pages)
    return findings


def _site_checks(crawl: CrawlResult) -> list[Finding]:
    out: list[Finding] = []
    if urlsplit(crawl.start_url).scheme != "https":
        out.append(Finding(
            "not_https", "technical", "high", "The site is not served over HTTPS",
            "The start URL uses plain HTTP, so traffic is unencrypted and browsers warn visitors.",
            "Install a TLS certificate and redirect all HTTP traffic to HTTPS.",
            url=crawl.start_url,
        ))
    if crawl.robots.error in ("timeout", "network", "blocked"):
        out += _unreachable(crawl.start_url, crawl.robots.error, is_start=True)
    elif crawl.robots.unavailable:
        out.append(Finding(
            "robots_unavailable", "technical", "high", "robots.txt could not be fetched",
            "The server errored on /robots.txt, so crawlers must assume the whole site is closed.",
            "Fix the error so /robots.txt returns 200 or 404.", url=crawl.robots_url,
        ))
    elif not crawl.robots.present:
        out.append(Finding(
            "robots_missing", "technical", "low", "No robots.txt file",
            "There is no /robots.txt, so crawler rules and the sitemap location are not declared.",
            "Add a robots.txt that allows crawling and points to your sitemap.",
            url=crawl.robots_url,
        ))
    if not crawl.sitemap_present:
        out.append(Finding(
            "sitemap_missing", "technical", "medium", "No sitemap.xml found",
            "No valid XML sitemap was found, so search engines may miss pages.",
            "Publish a sitemap.xml and reference it from robots.txt.", url=crawl.sitemap_url,
        ))
    return out


def _fetch_problems(crawl: CrawlResult) -> list[Finding]:
    out: list[Finding] = []
    for rec in crawl.pages.values():
        f = rec.fetch
        is_start = rec.url == crawl.start_url
        if f.error in ("timeout", "network", "blocked"):
            out += _unreachable(rec.url, f.error, is_start=is_start)
        elif f.error == "too_large":
            out.append(Finding(
                "page_too_large", "technical", "medium", "Page is too large to analyse",
                "The response was bigger than the 2 MB audit limit, so it was skipped.",
                "Reduce the page's HTML size.", url=rec.url,
            ))
        elif f.status is not None and f.status >= 400:
            out.append(Finding(
                "broken_internal_link", "links", "critical" if is_start else "high",
                f"Page returns HTTP {f.status}",
                f"This internal page answered {f.status}."
                + (f" Linked from {', '.join(crawl.referrers.get(rec.url, [])[:3])}."
                   if crawl.referrers.get(rec.url) else ""),
                "Fix the page, or update or remove the links that point to it.",
                url=rec.url, metric={"status": f.status},
            ))
        elif ok_page(rec) and "noindex" in ((rec.data and rec.data.robots_meta) or ""):
            out.append(Finding(
                "noindex", "technical", "medium", "Page is blocked from search with noindex",
                "A robots meta tag tells search engines not to index this page.",
                "Remove noindex if the page should appear in search results.", url=rec.url,
            ))
    return out


def _unreachable(url: str, error: str, *, is_start: bool) -> list[Finding]:
    reason = {
        "timeout": "timed out",
        "network": "could not be reached",
        "blocked": "was refused by the safety checks",
    }[error]
    return [Finding(
        "start_unreachable" if is_start else "page_unreachable", "links",
        "critical" if is_start else "high",
        "The site could not be audited" if is_start else "A page could not be loaded",
        f"The request {reason}.",
        "Check that the site is online and reachable from the public internet.",
        url=url,
    )]


def _redirects(crawl: CrawlResult) -> list[Finding]:
    out: list[Finding] = []
    for rec in crawl.pages.values():
        f = rec.fetch
        if f.error == "redirect_loop":
            out.append(Finding(
                "redirect_loop", "links", "high", "Redirect loop",
                "This URL redirects back to a URL it already passed through.",
                "Fix the redirect rules so the URL resolves to a final page.",
                url=rec.url, metric={"chain": [u for u, _ in f.chain]},
            ))
        elif len(f.chain) > REDIRECT_CHAIN_LIMIT or f.error == "too_many_redirects":
            out.append(Finding(
                "redirect_chain", "links", "medium", "Long redirect chain",
                f"This URL passes through {len(f.chain)} redirects before reaching a page.",
                "Redirect straight to the final URL in one step.",
                url=rec.url, metric={"hops": len(f.chain)},
            ))
    return out


def _link_checks(crawl: CrawlResult) -> list[Finding]:
    out: list[Finding] = []
    for link in crawl.external.values():
        f = link.fetch
        broken = f.error in ("timeout", "network") or (f.status is not None and f.status >= 400)
        if not broken:
            continue
        what = f"HTTP {f.status}" if f.status else f.error
        out.append(Finding(
            "broken_external_link", "links", "medium", f"Broken outbound link ({what})",
            f"{link.url} did not load. Found on {', '.join(link.found_on) or 'the site'}.",
            "Update or remove the link.", url=link.url,
            metric={"status": f.status, "error": f.error, "found_on": link.found_on},
        ))
    return out


def _on_page(rec: PageRecord) -> list[Finding]:
    d = rec.data
    assert d is not None
    url = rec.url
    out: list[Finding] = []

    def add(code: str, category: str, severity: str, title: str, detail: str, fix: str,
            **metric: Any) -> None:
        out.append(Finding(code, category, severity, title, detail, fix, url=url, metric=metric))

    title = (d.title or "").strip()
    if not title:
        add("title_missing", "on_page", "high", "Missing page title",
            "The page has no <title>, which is the main headline in search results.",
            "Add a unique, descriptive title of 30 to 60 characters.")
    elif len(title) < TITLE_RANGE[0]:
        add("title_short", "on_page", "low", "Page title is too short",
            f"The title is {len(title)} characters; under {TITLE_RANGE[0]} wastes ranking space.",
            "Expand the title to 30 to 60 characters.", length=len(title))
    elif len(title) > TITLE_RANGE[1]:
        add("title_long", "on_page", "low", "Page title is too long",
            f"The title is {len(title)} characters and may be cut off in search results.",
            "Shorten the title to 60 characters or fewer.", length=len(title))

    desc = (d.meta_description or "").strip()
    if not desc:
        add("description_missing", "on_page", "medium", "Missing meta description",
            "Without a meta description, search engines pick random page text as the snippet.",
            "Write a unique summary of 70 to 160 characters.")
    elif not DESCRIPTION_RANGE[0] <= len(desc) <= DESCRIPTION_RANGE[1]:
        add("description_length", "on_page", "low", "Meta description length is off",
            f"The description is {len(desc)} characters; aim for 70 to 160.",
            "Rewrite the description to 70 to 160 characters.", length=len(desc))

    if d.h1_count == 0:
        add("h1_missing", "on_page", "high", "Missing H1 heading",
            "The page has no H1, so its main topic is unclear to readers and search engines.",
            "Add exactly one H1 that describes the page.")
    elif d.h1_count > 1:
        add("h1_multiple", "on_page", "medium", "More than one H1 heading",
            f"The page has {d.h1_count} H1 headings.", "Keep one H1 and use H2 or H3 below it.",
            count=d.h1_count)

    if not d.canonical:
        add("canonical_missing", "on_page", "low", "No canonical tag",
            "Without a canonical link, duplicate URLs can compete with each other in search.",
            'Add <link rel="canonical"> pointing to the preferred URL.')

    if d.images_missing_alt:
        add("images_missing_alt", "on_page", "medium", "Images without alt text",
            f"{d.images_missing_alt} of {d.images} images have no alt text.",
            "Describe each meaningful image in its alt attribute.",
            missing=d.images_missing_alt, total=d.images)

    missing_og = sorted({"og:title", "og:description", "og:image"} - d.open_graph)
    if missing_og:
        add("open_graph_missing", "on_page", "low", "Incomplete Open Graph tags",
            f"Missing {', '.join(missing_og)}, so shared links may look bare on social networks.",
            "Add og:title, og:description and og:image.", missing=missing_og)

    if not d.has_structured_data:
        add("structured_data_missing", "on_page", "low", "No structured data",
            "The page has no JSON-LD, so it is not eligible for rich results.",
            "Add schema.org JSON-LD that fits the page, such as Organization or Article.")

    if not d.viewport:
        add("viewport_missing", "mobile", "high", "No mobile viewport tag",
            "Without a viewport meta tag, phones show a shrunken desktop layout.",
            'Add <meta name="viewport" content="width=device-width, initial-scale=1">.')
    return out


def _duplicate_titles(pages: list[PageRecord]) -> list[Finding]:
    groups: dict[str, list[str]] = defaultdict(list)
    for rec in pages:
        title = (rec.data.title if rec.data else None) or ""
        if title.strip():
            groups[title.strip().lower()].append(rec.url)
    return [
        Finding(
            "title_duplicate", "on_page", "medium", "Duplicate page title",
            f'{len(urls)} pages share the title "{title}".',
            "Give every page its own title.", url=urls[0], metric={"urls": urls[:10]},
        )
        for title, urls in groups.items() if len(urls) > 1
    ]
