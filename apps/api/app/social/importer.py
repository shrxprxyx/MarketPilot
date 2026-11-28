"""Reads a performance export (CSV or JSON) into validated rows (FR-AUD-09). Each platform has its
own template: the column names its native export uses. Nothing is saved here, so the same code
serves the preview and the final import."""
import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAX_CHARS = 2_000_000
MAX_ROWS = 5000
POST_COUNTS = ("impressions", "reach", "likes", "comments", "shares", "clicks")

# canonical field -> accepted column names (normalised: lower case, underscores). The first
# name is the one shown in the template.
_POSTS: dict[str, dict[str, list[str]]] = {
    "facebook": {
        "posted_at": ["publish_time", "posted_at", "date"],
        "ref": ["post_id", "permalink", "ref"],
        "title": ["title", "post_message", "message"],
        "format": ["post_type", "format"],
        "impressions": ["impressions", "lifetime_post_total_impressions"],
        "reach": ["reach", "lifetime_post_total_reach"],
        "likes": ["reactions", "likes"],
        "comments": ["comments"],
        "shares": ["shares"],
        "clicks": ["link_clicks", "clicks"],
    },
    "instagram": {
        "posted_at": ["publish_time", "posted_at", "date"],
        "ref": ["permalink", "post_id", "ref"],
        "title": ["description", "title", "caption"],
        "format": ["post_type", "media_type", "format"],
        "impressions": ["impressions", "views"],
        "reach": ["reach"],
        "likes": ["likes"],
        "comments": ["comments"],
        "shares": ["shares"],
        "clicks": ["link_clicks", "profile_visits", "clicks"],
    },
    "linkedin": {
        "posted_at": ["created_date", "posted_at", "date"],
        "ref": ["post_link", "post_id", "ref"],
        "title": ["post_title", "title"],
        "format": ["content_type", "format"],
        "impressions": ["impressions"],
        "reach": ["unique_impressions", "reach"],
        "likes": ["reactions", "likes"],
        "comments": ["comments"],
        "shares": ["reposts", "shares"],
        "clicks": ["clicks"],
    },
}
_DAILY = {
    "day": ["date", "day"],
    "followers": ["followers", "total_followers", "follower_count"],
    "reach": ["reach"],
    "impressions": ["impressions"],
}
_REQUIRED = {"posts": "posted_at", "daily": "day"}
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d")


class ImportFileError(ValueError):
    """The file as a whole cannot be read (as opposed to a bad row)."""


@dataclass
class RowError:
    row: int  # 1 is the first data row
    message: str


@dataclass
class ImportResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    total: int = 0


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def template(platform: str, kind: str) -> dict[str, list[str]]:
    return _DAILY if kind == "daily" else _POSTS[platform]


def _read(content: str, fmt: str) -> list[dict[str, Any]]:
    if len(content) > MAX_CHARS:
        raise ImportFileError("The file is too large (2 MB at most).")
    if fmt == "json":
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ImportFileError("The file is not valid JSON.") from exc
        if isinstance(data, dict):
            data = data.get("rows") or data.get("data")
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ImportFileError("JSON must be a list of objects (or {\"rows\": [...]}).")
        rows = data
    else:
        rows = list(csv.DictReader(io.StringIO(content.lstrip("﻿"))))
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f"Too many rows ({MAX_ROWS} at most).")
    return [{_norm(str(k)): v for k, v in r.items() if k is not None} for r in rows]


def _lookup(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _datetime(value: Any) -> datetime:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)  # noqa: DTZ007 - made aware just below
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Cannot read the date '{text}'.") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _count(value: Any, name: str, *, blank: int | None) -> int | None:
    if value is None:
        return blank
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except ValueError:
        raise ValueError(f"{name} must be a number.") from None
    if number < 0:
        raise ValueError(f"{name} cannot be negative.")
    return number


def _posts_row(row: dict[str, Any], cols: dict[str, list[str]]) -> dict[str, Any]:
    raw_date = _lookup(row, cols["posted_at"])
    if raw_date is None:
        raise ValueError(f"{cols['posted_at'][0]} is missing.")
    posted_at = _datetime(raw_date)
    title = _lookup(row, cols["title"])
    title = str(title).strip()[:300] if title is not None else None
    ref = _lookup(row, cols["ref"])
    fmt = _lookup(row, cols["format"])
    out: dict[str, Any] = {
        "ref": str(ref).strip()[:500] if ref is not None
        else f"{posted_at.isoformat()}|{title or ''}"[:500],
        "posted_at": posted_at,
        "title": title,
        "format": str(fmt).strip().lower()[:40] if fmt is not None else None,
    }
    for name in POST_COUNTS:
        out[name] = _count(_lookup(row, cols[name]), name, blank=0)
    return out


def _daily_row(row: dict[str, Any], cols: dict[str, list[str]]) -> dict[str, Any]:
    raw_day = _lookup(row, cols["day"])
    if raw_day is None:
        raise ValueError(f"{cols['day'][0]} is missing.")
    return {
        "day": _datetime(raw_day).date(),
        "followers": _count(_lookup(row, cols["followers"]), "followers", blank=None),
        "reach": _count(_lookup(row, cols["reach"]), "reach", blank=0),
        "impressions": _count(_lookup(row, cols["impressions"]), "impressions", blank=0),
    }


def parse_export(platform: str, kind: str, fmt: str, content: str) -> ImportResult:
    cols = template(platform, kind)
    rows = _read(content, fmt)
    if not rows:
        raise ImportFileError("The file has no rows.")
    required = cols[_REQUIRED[kind]]
    if not any(name in rows[0] for name in required):
        raise ImportFileError(
            f"Missing the '{required[0]}' column. Found: {', '.join(sorted(rows[0])) or 'none'}."
        )
    build = _posts_row if kind == "posts" else _daily_row
    key = "ref" if kind == "posts" else "day"
    result = ImportResult(total=len(rows))
    seen: dict[Any, dict[str, Any]] = {}
    for number, row in enumerate(rows, start=1):
        try:
            parsed = build(row, cols)
        except ValueError as exc:
            result.errors.append(RowError(number, str(exc)))
            continue
        seen[parsed[key]] = parsed  # a repeated post or day: the last row wins
    result.rows = list(seen.values())
    return result
