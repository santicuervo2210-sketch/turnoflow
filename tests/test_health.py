from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "TurnoFlow"}


def test_static_assets_have_browser_cache_headers() -> None:
    client = TestClient(app)

    response = client.get("/static/css/styles.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
