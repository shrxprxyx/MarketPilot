"""The 0 to 100 audit score (FR-AUD-06). Deterministic and explainable:

* Each category starts at 100 and loses points per issue type (finding `code`). Severity sets
  the points: critical 50, high 25, medium 12, low 5.
* Page-level issues scale with how much of the crawl they touch: half the points when one
  page is affected, all of them when every page is. Site-level issues cost the full amount.
* The overall score is the weighted sum of the category scores.
"""
from collections import defaultdict

from app.audit.checks import Finding

SEVERITY_POINTS = {"critical": 50, "high": 25, "medium": 12, "low": 5}
WEIGHTS = {"technical": 0.25, "on_page": 0.35, "links": 0.25, "mobile": 0.15}
# Issues about the site as a whole rather than individual pages: always the full penalty.
SITE_LEVEL = {
    "not_https", "robots_unavailable", "robots_missing", "sitemap_missing", "start_unreachable",
}


def score_audit(findings: list[Finding], pages_crawled: int) -> tuple[int, dict[str, int]]:
    """Returns (overall score, score per category)."""
    pages = max(pages_crawled, 1)
    by_code: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_code[f.code].append(f)

    lost: dict[str, float] = defaultdict(float)
    for items in by_code.values():
        first = items[0]
        ratio = 1.0 if first.code in SITE_LEVEL else min(1.0, len(items) / pages)
        lost[first.category] += SEVERITY_POINTS[first.severity] * (0.5 + 0.5 * ratio)

    categories = {c: max(0, round(100 - lost[c])) for c in WEIGHTS}
    overall = round(sum(categories[c] * w for c, w in WEIGHTS.items()))
    return overall, categories
