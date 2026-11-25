"""Token lifetimes and claims (SRS §6, FR-AUTH-02)."""
import uuid
from datetime import datetime, timedelta, timezone

from app.auth.jwt import create_access_token, decode_access_token, refresh_token_expiry


def test_access_token_lasts_15_minutes_and_carries_a_unique_jti() -> None:
    args = (uuid.uuid4(), uuid.uuid4(), "admin")
    first = decode_access_token(create_access_token(*args))
    second = decode_access_token(create_access_token(*args))
    assert first and second
    assert first["exp"] - first["iat"] == 15 * 60
    assert first["jti"] and first["jti"] != second["jti"]


def test_refresh_token_lasts_7_days() -> None:
    remaining = refresh_token_expiry() - datetime.now(timezone.utc)
    assert timedelta(days=7) - timedelta(minutes=1) < remaining <= timedelta(days=7)
