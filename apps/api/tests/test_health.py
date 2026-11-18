from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    r = TestClient(app).get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_without_infra() -> None:
    """503 returns problem+json; 200 returns plain json."""
    r = TestClient(app).get("/api/v1/ready")
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert r.headers["content-type"] == "application/problem+json"