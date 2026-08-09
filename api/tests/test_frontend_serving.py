"""The API serves the built frontend, so the user installs one thing."""

from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


def test_dev_page_when_no_frontend_is_configured(kernel):
    with TestClient(ApiServer(kernel).build_app()) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "OpenKerf API" in response.text


def test_frontend_is_served_at_root(kernel, tmp_path):
    (tmp_path / "index.html").write_text("<h1>OpenKerf</h1>")
    (tmp_path / "app.js").write_text("console.log('hi')")

    server = ApiServer(kernel, frontend=str(tmp_path))
    with TestClient(server.build_app()) as client:
        assert client.get("/").text == "<h1>OpenKerf</h1>"
        assert client.get("/app.js").status_code == 200
        # The static mount must not shadow the API.
        assert client.get("/api/health").json()["ok"] is True


def test_missing_frontend_directory_falls_back(kernel, tmp_path):
    server = ApiServer(kernel, frontend=str(tmp_path / "does-not-exist"))
    with TestClient(server.build_app()) as client:
        assert client.get("/").status_code == 200
        assert "OpenKerf API" in client.get("/").text
