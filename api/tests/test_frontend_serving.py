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


def test_client_routes_fall_back_to_index(kernel, tmp_path):
    """/setup exists only in the browser, so it must serve the app shell."""
    (tmp_path / "index.html").write_text("<h1>OpenKerf</h1>")

    server = ApiServer(kernel, frontend=str(tmp_path))
    with TestClient(server.build_app()) as client:
        assert client.get("/setup").text == "<h1>OpenKerf</h1>"
        # A missing asset must still 404 — serving HTML as JS breaks the page.
        assert client.get("/_app/immutable/gone.js").status_code == 404


def test_missing_frontend_directory_falls_back(kernel, tmp_path):
    server = ApiServer(kernel, frontend=str(tmp_path / "does-not-exist"))
    with TestClient(server.build_app()) as client:
        assert client.get("/").status_code == 200
        assert "OpenKerf API" in client.get("/").text


def test_an_unknown_api_path_is_a_404_not_the_html_page(tmp_path, kernel):
    """
    This was confusing: an unknown /api path fell into the SPA fallback. A GET got
    the HTML page back where the frontend expected JSON, and a POST got "405 Method
    Not Allowed" because the fallback only knows GET. So anybody running an older
    server beside a newer frontend saw a message that made no sense at all.
    """
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><title>OpenKerf</title>")
    server = ApiServer(kernel, frontend=str(build), library_path=tmp_path / "f.db")

    with TestClient(server.build_app()) as client:
        get = client.get("/api/bestaat-niet")
        post = client.post("/api/bestaat-niet", json={})

        assert get.status_code == 404
        assert "Unknown API route" in get.json()["detail"]
        assert post.status_code == 404
        # De echte SPA-route blijft wél de app teruggeven.
        assert client.get("/setup").status_code == 200
