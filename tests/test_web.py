"""Dashboard delivery must coexist with the existing API used by n8n."""
from fastapi.testclient import TestClient

from api.main import app


def test_dashboard_and_assets_are_served():
    client = TestClient(app)
    response = client.get("/ui/")
    assert response.status_code == 200
    assert 'lang="de"' in response.text
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/style.css").status_code == 200


def test_dashboard_does_not_shadow_api_endpoints():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/health", "/jobs", "/jobs/cached", "/jobs/stats"):
        assert "get" in paths[path]
    # Missing assets should not silently return the dashboard document.
    assert client.get("/ui/missing.js").status_code == 404

