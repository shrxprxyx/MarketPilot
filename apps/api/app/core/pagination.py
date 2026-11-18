"""Opaque cursor pagination over (created_at, id) descending — the convention
§8 of the SRS calls for on every list endpoint. The cursor just encodes the last
seen row's sort key, so callers can't construct one that skips RLS/tenant
filtering; it's purely a resume-point, not a query parameter.
"""
import base64
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(id_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor.") from exc
