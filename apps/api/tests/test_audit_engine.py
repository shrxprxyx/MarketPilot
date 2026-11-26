"""Audit engine core (FR-AUD-01 to 03, 06, 07): fetcher, robots, crawler, checks, scoring.
No network: sites are served by httpx's MockTransport and the DNS guard is stubbed, except in
the SSRF tests, which use IP literals so nothing is resolved."""
import asyncio

import httpx
import pytest

from app.audit.checks import Finding, run_checks
from app.audit.crawler import crawl, normalize
from app.audit.fetcher import SafeFetcher
from app.audit.parse import parse_page
from app.audit.scoring import score_audit
from app.core.ssrf import UnsafeDestination, check_destination

GOOD_TITLE = "Acme Pet Supplies | Quality food and toys"  # 42 chars
GOOD_DESC = "Acme sells quality pet food, toys and accessories, shipped across the country."


def page(
    title: str | None = GOOD_TITLE,
    *,
    desc: str | None = GOOD_DESC,
    h1: int = 1,
    links: tuple[str, ...] = (),
    extra: str = "",
    viewport: bool = True,
    full: bool = True,
) -> str:
    head = ""
    if title is not None:
        head += f"<title>{title}</title>"
    if desc is not None:
        head += f'<meta name="description" content="{desc}">'
    if viewport:
        head += '<meta name="viewport" content="width=device-width, initial-scale=1">'
    if full:
        head += '<link rel="canonical" href="https://acme.test/">'
        head += '<meta property="og:title" content="t"><meta property="og:description" content="d">'
        head += '<meta property="og:image" content="i">'
        head += '<script type="application/ld+json">{"@type": "Organization"}</script>'
    body = "<h1>Welcome</h1>" * h1 + "".join(f'<a href="{href}">x</a>' for href in links) + extra
    return f"<html><head>{head}</head><body>{body}</body></html>"


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


SITEMAP = "<urlset><url><loc>https://acme.test/</loc></url><url><loc>https://acme.test/a</loc></url></urlset>"


def site(routes: dict[str, httpx.Response | str]) -> httpx.MockTransport:
    """Serves `routes` by URL path; anything else is a 404. A str value is an HTML page."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        hit = routes.get(key)
        if hit is None:
            return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
        return html(hit) if isinstance(hit, str) else hit

    return httpx.MockTransport(handler)


async def allow_all(url: str) -> None:
    return None


def fetcher(routes: dict[str, httpx.Response | str], **kw: object) -> SafeFetcher:
    return SafeFetcher(check=allow_all, transport=site(routes), min_interval=0, **kw)  # type: ignore[arg-type]


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


# --- SSRF (FR-AUD-07) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("ftp://example.com/", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("http://169.254.169.254/latest", "blocked"),
        ("http://127.0.0.1/", "private"),
        ("http://10.0.0.1/", "private"),
        ("http://[::1]/", "private"),
    ],
)
async def test_ssrf_guard_rejects_unsafe_destinations(url: str, kind: str) -> None:
    with pytest.raises(UnsafeDestination) as exc:
        await check_destination(url, allow_private=False)
    assert exc.value.kind == kind


async def test_private_addresses_can_be_allowed_but_metadata_never() -> None:
    await check_destination("http://127.0.0.1/", allow_private=True)
    with pytest.raises(UnsafeDestination):
        await check_destination("http://169.254.169.254/", allow_private=True)


async def test_default_fetcher_refuses_private_hosts_without_connecting() -> None:
    async with SafeFetcher(min_interval=0) as f:
        result = await f.fetch("http://127.0.0.1:9/")
    assert result.error == "blocked"
    assert result.status is None


async def test_every_redirect_hop_is_checked() -> None:
    seen: list[str] = []

    async def check(url: str) -> None:
        seen.append(url)
        if "internal" in url:
            raise UnsafeDestination("private")

    routes = {"/": httpx.Response(302, headers={"location": "http://internal.test/admin"})}
    async with SafeFetcher(check=check, transport=site(routes), min_interval=0) as f:
        result = await f.fetch("https://acme.test/")
    assert result.error == "blocked"
    assert seen == ["https://acme.test/", "http://internal.test/admin"]
    assert result.chain == [("https://acme.test/", 302)]


# --- Fetcher -------------------------------------------------------------------------------


async def test_fetch_reads_html_and_records_a_redirect_chain() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/old": httpx.Response(301, headers={"location": "/mid"}),
        "/mid": httpx.Response(302, headers={"location": "/new"}),
        "/new": page(),
    }
    async with fetcher(routes) as f:
        r = await f.fetch("https://acme.test/old")
    assert r.status == 200
    assert r.final_url == "https://acme.test/new"
    assert r.chain == [("https://acme.test/old", 301), ("https://acme.test/mid", 302)]
    assert r.body and "<h1>" in r.body


async def test_redirect_loop_and_too_many_redirects() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/a": httpx.Response(302, headers={"location": "/b"}),
        "/b": httpx.Response(302, headers={"location": "/a"}),
    }
    for i in range(10):
        routes[f"/h{i}"] = httpx.Response(302, headers={"location": f"/h{i + 1}"})
    async with fetcher(routes) as f:
        loop = await f.fetch("https://acme.test/a")
        long = await f.fetch("https://acme.test/h0")
    assert loop.error == "redirect_loop"
    assert long.error == "too_many_redirects"


async def test_oversized_and_non_text_responses_are_not_read() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/big": html("x" * 5000),
        "/img": httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}),
    }
    async with fetcher(routes, max_bytes=1000) as f:
        big = await f.fetch("https://acme.test/big")
        img = await f.fetch("https://acme.test/img")
    assert big.error == "too_large"
    assert big.body is None
    assert img.status == 200
    assert img.body is None
    assert img.content_type == "image/png"


async def test_timeouts_and_network_errors_are_reported_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/slow":
            raise httpx.ReadTimeout("slow")
        raise httpx.ConnectError("down")

    async with SafeFetcher(
        check=allow_all, transport=httpx.MockTransport(handler), min_interval=0
    ) as f:
        assert (await f.fetch("https://acme.test/slow")).error == "timeout"
        assert (await f.fetch("https://acme.test/x")).error == "network"


async def test_requests_to_one_host_are_spaced_out(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr("app.audit.fetcher.asyncio.sleep", fake_sleep)
    async with SafeFetcher(
        check=allow_all, transport=site({"/": page()}), min_interval=1.0
    ) as f:
        await f.fetch("https://acme.test/")
        await f.fetch("https://acme.test/")
        await f.fetch("https://other.test/")  # another host is not delayed
    assert len(sleeps) == 1
    assert 0.5 < sleeps[0] <= 1.0


# --- Parser --------------------------------------------------------------------------------


def test_parser_extracts_the_on_page_signals() -> None:
    d = parse_page(
        page(
            "  My  Title ",
            h1=2,
            links=("/a", "https://other.test/", ""),
            extra='<img src="a.png" alt="ok"><img src="b.png"><img src="c.png" alt=" ">'
            "<h2>Sub</h2>",
        )
    )
    assert d.title == "My Title"
    assert d.meta_description == GOOD_DESC
    assert d.viewport and d.canonical
    assert d.h1_count == 2
    assert (d.images, d.images_missing_alt) == (3, 2)
    assert d.open_graph == {"og:title", "og:description", "og:image"}
    assert d.has_structured_data
    assert d.links == ["/a", "https://other.test/"]
    assert d.headings == ["Welcome", "Welcome", "Sub"]


def test_parser_survives_broken_markup_and_bad_json_ld() -> None:
    d = parse_page(
        '<title>T</title><h1>Unclosed<script type="application/ld+json">{oops</script><img>'
    )
    assert d.title == "T"
    assert d.images == 1
    assert not d.has_structured_data


# --- Crawler (FR-AUD-01, 02) ---------------------------------------------------------------


def test_normalize_drops_fragments_default_ports_and_case() -> None:
    assert normalize("HTTPS://Acme.test:443/a#top") == "https://acme.test/a"
    assert normalize("http://acme.test") == "http://acme.test/"
    assert normalize("https://acme.test:8443/a?x=1") == "https://acme.test:8443/a?x=1"


def home(*links: str, **kw: object) -> str:
    return page(links=links, **kw)  # type: ignore[arg-type]


async def test_crawl_stays_on_origin_and_checks_outbound_links() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        "/sitemap.xml": httpx.Response(200, text=SITEMAP, headers={"content-type": "text/xml"}),
        "/": home("/a", "https://acme.test/b#x", "https://ext.test/ok", "https://ext.test/gone",
                  "mailto:hi@acme.test", "javascript:void(0)"),
        "/a": home("/b"),
        "/b": home("/"),
        "/ok": "fine",
        "/gone": httpx.Response(404, text="x"),
    }
    async with fetcher(routes) as f:
        result = await crawl("https://acme.test", f)
    assert set(result.pages) == {
        "https://acme.test/", "https://acme.test/a", "https://acme.test/b",
    }
    assert result.sitemap_present and result.sitemap_urls == 2
    assert result.robots.present
    assert set(result.external) == {"https://ext.test/ok", "https://ext.test/gone"}
    assert result.external["https://ext.test/gone"].fetch.status == 404
    assert result.external["https://ext.test/ok"].fetch.body is None  # status only
    assert result.referrers["https://acme.test/b"] == ["https://acme.test/", "https://acme.test/a"]


async def test_crawl_respects_depth_and_page_limits_and_reports_truncation() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/": home("/1"), "/1": home("/2"), "/2": home("/3"), "/3": home("/4"), "/4": home(),
    }
    async with fetcher(routes) as f:
        shallow = await crawl("https://acme.test", f, max_depth=2)
    assert set(shallow.pages) == {
        "https://acme.test/", "https://acme.test/1", "https://acme.test/2",
    }
    routes = {"/": home("/1", "/2", "/3"), "/1": home(), "/2": home(), "/3": home()}
    async with fetcher(routes) as f:
        capped = await crawl("https://acme.test", f, max_pages=2)
    assert len(capped.pages) == 2
    assert capped.truncated


async def test_crawl_honours_robots_disallow() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /private\n"),
        "/": home("/public", "/private/secret"),
        "/public": home(),
        "/private/secret": home(),
    }
    async with fetcher(routes) as f:
        result = await crawl("https://acme.test", f)
    assert "https://acme.test/private/secret" not in result.pages
    assert result.skipped_by_robots == 1


async def test_robots_5xx_means_disallow_all_and_404_means_allow_all() -> None:
    async with fetcher({"/robots.txt": httpx.Response(503), "/": home()}) as f:
        down = await crawl("https://acme.test", f)
    assert down.robots.unavailable
    assert down.pages == {}
    async with fetcher({"/": home()}) as f:
        missing = await crawl("https://acme.test", f)
    assert not missing.robots.present
    assert "https://acme.test/" in missing.pages


async def test_crawl_follows_the_start_redirect_to_the_real_host() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "acme.test":
            return httpx.Response(301, headers={"location": f"https://www.acme.test{request.url.path}"})
        return html(home("/a")) if request.url.path in ("/", "/a") else httpx.Response(404)

    async with SafeFetcher(
        check=allow_all, transport=httpx.MockTransport(handler), min_interval=0
    ) as f:
        result = await crawl("https://acme.test", f)
    assert result.origin == "www.acme.test"
    assert "https://www.acme.test/a" in result.pages


async def test_crawl_reports_progress_and_can_be_cancelled() -> None:
    routes: dict[str, httpx.Response | str] = {"/": home("/a", "/b"), "/a": home(), "/b": home()}
    ticks: list[tuple[int, int]] = []

    async def progress(done: int, total: int, message: str) -> None:
        ticks.append((done, total))

    async with fetcher(routes) as f:
        await crawl("https://acme.test", f, max_pages=10, on_progress=progress)
    assert ticks == [(1, 10), (2, 10), (3, 10)]

    calls = 0

    async def stop() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    async with fetcher(routes) as f:
        result = await crawl("https://acme.test", f, should_stop=stop)
    assert result.cancelled
    assert len(result.pages) == 1


# --- Checks (FR-AUD-02, 03) ----------------------------------------------------------------


async def audit(
    routes: dict[str, httpx.Response | str], url: str = "https://acme.test"
) -> list[Finding]:
    async with fetcher(routes) as f:
        return run_checks(await crawl(url, f))


CLEAN_SITE: dict[str, httpx.Response | str] = {
    "/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
    "/sitemap.xml": httpx.Response(200, text=SITEMAP),
    "/": home("/a"),
    "/a": home(title="Another page about Acme dog treats and chews", desc=GOOD_DESC + " More."),
}


async def test_a_healthy_site_has_no_findings() -> None:
    assert await audit(CLEAN_SITE) == []


async def test_on_page_problems_are_found_with_severities() -> None:
    routes = dict(CLEAN_SITE)
    routes["/"] = page(
        None, desc=None, h1=0, links=("/a",), viewport=False, full=False,
        extra='<img src="x.png">',
    )
    found = {f.code: f for f in await audit(routes) if f.url == "https://acme.test/"}
    assert found["title_missing"].severity == "high"
    assert found["description_missing"].severity == "medium"
    assert found["h1_missing"].severity == "high"
    assert found["canonical_missing"].severity == "low"
    assert found["images_missing_alt"].metric == {"missing": 1, "total": 1}
    assert set(found["open_graph_missing"].metric["missing"]) == {
        "og:description", "og:image", "og:title",
    }
    assert found["structured_data_missing"].severity == "low"
    assert found["viewport_missing"].category == "mobile"


async def test_length_and_multiple_h1_checks() -> None:
    routes = dict(CLEAN_SITE)
    routes["/"] = page("Short", desc="tiny", h1=2, links=("/a",))
    routes["/a"] = page("T" * 80, desc="d" * 200)
    found = await audit(routes)
    assert {"title_short", "description_length", "h1_multiple", "title_long"} <= set(codes(found))
    assert sum(f.code == "description_length" for f in found) == 2


async def test_duplicate_titles_are_grouped_into_one_finding() -> None:
    routes = dict(CLEAN_SITE)
    routes["/"] = home("/a", "/b")
    routes["/a"] = home()
    routes["/b"] = home()
    dup = [f for f in await audit(routes) if f.code == "title_duplicate"]
    assert len(dup) == 1
    assert len(dup[0].metric["urls"]) == 3


async def test_broken_links_redirects_and_site_level_checks() -> None:
    routes: dict[str, httpx.Response | str] = {
        "/": home("/gone", "/boom", "/chain", "/loop", "https://ext.test/dead"),
        "/gone": httpx.Response(404, text="x"),
        "/boom": httpx.Response(500, text="x"),
        "/chain": httpx.Response(301, headers={"location": "/c2"}),
        "/c2": httpx.Response(301, headers={"location": "/c3"}),
        "/c3": httpx.Response(301, headers={"location": "/end"}),
        "/end": home(),
        "/loop": httpx.Response(302, headers={"location": "/loop2"}),
        "/loop2": httpx.Response(302, headers={"location": "/loop"}),
        "/dead": httpx.Response(410),
    }
    found = await audit(routes, "http://acme.test")
    by_code: dict[str, list[Finding]] = {}
    for f in found:
        by_code.setdefault(f.code, []).append(f)
    assert {f.url for f in by_code["broken_internal_link"]} == {
        "http://acme.test/gone", "http://acme.test/boom",
    }
    assert by_code["broken_external_link"][0].url == "https://ext.test/dead"
    assert by_code["redirect_chain"][0].metric["hops"] == 3
    assert "redirect_loop" in by_code
    assert {"not_https", "robots_missing", "sitemap_missing"} <= set(by_code)


async def test_unreachable_start_page_is_critical() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with SafeFetcher(
        check=allow_all, transport=httpx.MockTransport(handler), min_interval=0
    ) as f:
        found = run_checks(await crawl("https://acme.test", f))
    start = next(f for f in found if f.code == "start_unreachable")
    assert start.severity == "critical"


async def test_noindex_pages_are_flagged() -> None:
    routes = dict(CLEAN_SITE)
    routes["/a"] = page(
        title="Another page about Acme dog treats and chews", desc=GOOD_DESC + " More.",
        extra='<meta name="robots" content="NOINDEX, follow">',
    ).replace("</head>", '<meta name="robots" content="NOINDEX, follow"></head>')
    assert "noindex" in codes(await audit(routes))


# --- Scoring (FR-AUD-06) -------------------------------------------------------------------


def f(code: str, category: str, severity: str) -> Finding:
    return Finding(code, category, severity, code, "", "", url=f"https://acme.test/{code}")


def test_no_findings_scores_100() -> None:
    full = {"technical": 100, "on_page": 100, "links": 100, "mobile": 100}
    assert score_audit([], 10) == (100, full)


def test_site_level_issue_costs_full_points_and_page_level_scales_with_coverage() -> None:
    overall, cats = score_audit([f("sitemap_missing", "technical", "medium")], 50)
    assert cats["technical"] == 88  # 100 - 12, not discounted by page count
    one_of_ten = score_audit([f("h1_missing", "on_page", "high")], 10)[1]["on_page"]
    all_ten = score_audit(
        [Finding("h1_missing", "on_page", "high", "t", "", "", url=f"/{i}") for i in range(10)], 10
    )[1]["on_page"]
    assert one_of_ten == 100 - round(25 * 0.55)
    assert all_ten == 75
    assert overall == round(88 * 0.25 + 100 * 0.75)


def test_scores_floor_at_zero_and_are_weighted() -> None:
    many = [f(f"c{i}", "links", "critical") for i in range(5)]
    overall, cats = score_audit(many, 1)
    assert cats["links"] == 0
    assert overall == 75  # the other three categories are untouched
    assert 0 <= overall <= 100
