"""Same-origin site crawler (FR-AUD-01, FR-AUD-02). Breadth-first from the client's URL, up to
`max_pages` pages and `max_depth` links deep, honouring robots.txt. Pages are fetched one at a
time: requests to a single host are limited to one per second anyway, so concurrency would only
help the (cross-host) external link checks, which do run in parallel."""
import asyncio
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from app.audit.fetcher import FetchResult, SafeFetcher
from app.audit.parse import PageData, parse_page
from app.audit.robots import Robots

MAX_PAGES = 100
MAX_DEPTH = 3
MAX_EXTERNAL_LINKS = 50
EXTERNAL_CONCURRENCY = 5
HTML_TYPES = ("text/html", "application/xhtml+xml")

Progress = Callable[[int, int, str], Awaitable[None]]
ShouldStop = Callable[[], Awaitable[bool]]


@dataclass
class PageRecord:
    url: str
    depth: int
    fetch: FetchResult
    data: PageData | None = None  # parsed HTML, or None when the page is not HTML / not read


@dataclass
class LinkCheck:
    url: str
    fetch: FetchResult
    found_on: list[str] = field(default_factory=list)


@dataclass
class CrawlResult:
    start_url: str
    origin: str  # host the crawl stayed on, after the start URL's redirects
    robots: Robots
    robots_url: str
    sitemap_url: str
    sitemap_present: bool = False
    sitemap_urls: int = 0
    pages: dict[str, PageRecord] = field(default_factory=dict)
    external: dict[str, LinkCheck] = field(default_factory=dict)
    referrers: dict[str, list[str]] = field(default_factory=dict)  # url -> pages linking to it
    skipped_by_robots: int = 0
    truncated: bool = False  # more pages were reachable than `max_pages` allowed
    cancelled: bool = False


def normalize(url: str) -> str:
    """Fragment dropped, scheme and host lower-cased, default port removed, empty path -> '/'."""
    parts = urlsplit(urldefrag(url).url)
    host = (parts.hostname or "").lower()
    default = 443 if parts.scheme == "https" else 80
    netloc = host if parts.port in (None, default) else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


async def crawl(
    start_url: str,
    fetcher: SafeFetcher,
    *,
    max_pages: int = MAX_PAGES,
    max_depth: int = MAX_DEPTH,
    on_progress: Progress | None = None,
    should_stop: ShouldStop | None = None,
) -> CrawlResult:
    start = normalize(start_url)
    base = urlsplit(start)
    root = f"{base.scheme}://{base.netloc}"

    robots_fetch = await fetcher.fetch(f"{root}/robots.txt")
    origin = _host(robots_fetch.final_url) or _host(start)
    origin_root = f"{urlsplit(robots_fetch.final_url).scheme}://{urlsplit(robots_fetch.final_url).netloc}"
    robots = Robots(robots_fetch)

    sitemap_url = robots.sitemaps[0] if robots.sitemaps else f"{origin_root}/sitemap.xml"
    result = CrawlResult(
        start_url=start,
        origin=origin,
        robots=robots,
        robots_url=robots_fetch.final_url,
        sitemap_url=sitemap_url,
    )
    await _read_sitemap(fetcher, result)

    seen = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        if should_stop and await should_stop():
            result.cancelled = True
            return result
        if len(result.pages) >= max_pages:
            result.truncated = True
            break
        url, depth = queue.popleft()
        if not robots.allows(url):
            result.skipped_by_robots += 1
            continue
        fetch = await fetcher.fetch(url)
        record = PageRecord(url=url, depth=depth, fetch=fetch)
        result.pages[url] = record
        seen.add(normalize(fetch.final_url))
        if on_progress:
            await on_progress(len(result.pages), max_pages, f"Crawled {len(result.pages)} pages")
        if fetch.body is None or fetch.content_type not in HTML_TYPES:
            continue
        record.data = parse_page(fetch.body)
        for href in record.data.links:
            link = normalize(urljoin(fetch.final_url, href))
            if not _is_http(link):
                continue
            result.referrers.setdefault(link, [])
            if len(result.referrers[link]) < 5:
                result.referrers[link].append(url)
            if _host(link) == origin:
                if link not in seen and depth + 1 <= max_depth:
                    seen.add(link)
                    queue.append((link, depth + 1))
            elif link not in result.external and len(result.external) < MAX_EXTERNAL_LINKS:
                result.external[link] = LinkCheck(url=link, fetch=FetchResult(link, link))

    await _check_external(fetcher, result, should_stop)
    return result


async def _read_sitemap(fetcher: SafeFetcher, result: CrawlResult) -> None:
    fetch = await fetcher.fetch(result.sitemap_url)
    body = fetch.body or ""
    if fetch.status == 200 and ("<urlset" in body or "<sitemapindex" in body):
        result.sitemap_present = True
        result.sitemap_urls = len(re.findall(r"<loc>", body))


async def _check_external(
    fetcher: SafeFetcher, result: CrawlResult, should_stop: ShouldStop | None
) -> None:
    """Status-only checks of outbound links. Different hosts are throttled independently, so
    a few can run at once."""
    gate = asyncio.Semaphore(EXTERNAL_CONCURRENCY)

    async def one(check: LinkCheck) -> None:
        async with gate:
            if should_stop and await should_stop():
                return
            check.fetch = await fetcher.fetch(check.url, read_body=False)
            check.found_on = result.referrers.get(check.url, [])[:3]

    await asyncio.gather(*(one(c) for c in result.external.values()))
    if should_stop and await should_stop():
        result.cancelled = True
