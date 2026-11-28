"""Deterministic social metrics (FR-AUD-10). Pure functions over imported rows; the AI step later
writes insights on top of these numbers and never produces them."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

TOP = 5
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def engagements(post: dict[str, Any]) -> int:
    return int(post["likes"] + post["comments"] + post["shares"] + post["clicks"])


def _rate(engaged: int, impressions: int) -> float | None:
    return round(engaged / impressions * 100, 2) if impressions else None


def _average(totals: dict[Any, list[int]]) -> list[dict[str, Any]]:
    return [
        {"key": key, "posts": len(values), "avg_engagements": round(sum(values) / len(values), 1)}
        for key, values in totals.items()
    ]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _followers(daily: list[dict[str, Any]]) -> dict[str, Any] | None:
    points = sorted((d["day"], d["followers"]) for d in daily if d["followers"] is not None)
    if not points:
        return None
    first, last = points[0][1], points[-1][1]
    return {
        "start": first,
        "end": last,
        "growth": last - first,
        "growth_pct": round((last - first) / first * 100, 2) if first else None,
        "from": points[0][0].isoformat(),
        "to": points[-1][0].isoformat(),
    }


def _trend(posts: list[dict[str, Any]], daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Weekly reach and impressions: account totals when the export has them, else post sums."""
    weeks: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    if daily:
        for d in daily:
            week = weeks[_week_start(d["day"])]
            week[0] += d["reach"]
            week[1] += d["impressions"]
    else:
        for p in posts:
            week = weeks[_week_start(p["posted_at"].date())]
            week[0] += p["reach"]
            week[1] += p["impressions"]
    return [
        {"week": week.isoformat(), "reach": reach, "impressions": impressions}
        for week, (reach, impressions) in sorted(weeks.items())
    ]


def _cadence(posts: list[dict[str, Any]]) -> dict[str, Any]:
    if not posts:
        return {"posts": 0, "per_week": None}
    first = min(p["posted_at"] for p in posts)
    last = max(p["posted_at"] for p in posts)
    weeks = max((last - first).days / 7, 1.0)
    return {"posts": len(posts), "per_week": round(len(posts) / weeks, 1)}


def _brief(post: dict[str, Any]) -> dict[str, Any]:
    posted_at: datetime = post["posted_at"]
    return {
        "ref": post["ref"],
        "title": post["title"],
        "format": post["format"],
        "posted_at": posted_at.isoformat(),
        "engagements": engagements(post),
        "impressions": post["impressions"],
    }


def compute_metrics(posts: list[dict[str, Any]], daily: list[dict[str, Any]]) -> dict[str, Any]:
    by_day: dict[str, list[int]] = defaultdict(list)
    by_hour: dict[int, list[int]] = defaultdict(list)
    by_format: dict[str, list[int]] = defaultdict(list)
    for p in posts:
        e = engagements(p)
        by_day[WEEKDAYS[p["posted_at"].weekday()]].append(e)
        by_hour[p["posted_at"].hour].append(e)
        by_format[p["format"] or "unknown"].append(e)

    ranked = sorted(posts, key=lambda p: (-engagements(p), p["posted_at"], p["ref"]))
    impressions = sum(p["impressions"] for p in posts)

    def best(averaged: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(averaged, key=lambda r: (-r["avg_engagements"], str(r["key"])))

    return {
        "posts": len(posts),
        "followers": _followers(daily),
        "engagement_rate": _rate(sum(engagements(p) for p in posts), impressions),
        "trend": _trend(posts, daily),
        "cadence": _cadence(posts),
        "best_days": best(_average(by_day)),
        "best_hours_utc": best(_average(by_hour)),
        "best_formats": best(_average(by_format)),
        "top_posts": [_brief(p) for p in ranked[:TOP]],
        "bottom_posts": [_brief(p) for p in reversed(ranked[max(TOP, len(ranked) - TOP):])],
    }
