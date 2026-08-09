"""End-to-end checks against the FastAPI app and the plugin registration."""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    server = ApiServer(kernel)
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_status_endpoint_returns_json(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["devices"]


def test_devices_endpoint(client):
    devices = client.get("/api/devices").json()
    assert isinstance(devices, list)
    assert devices[0]["spooler"]["present"] is True


def test_websocket_sends_snapshot_on_connect(client):
    with client.websocket_connect("/api/ws") as ws:
        payload = json.loads(ws.receive_text())
        assert payload["type"] == "snapshot"
        assert payload["data"]["devices"]


def test_no_write_endpoints_exist(client):
    """Phase 1 is read-only — guard against accidentally adding a mutation."""
    methods = {
        method
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    assert methods <= {"GET", "HEAD"}


def test_console_command_is_registered(kernel):
    output = []
    kernel.channel("console").watch(output.append)
    kernel.console("help openkerf\n")
    assert any("openkerf" in str(line) for line in output)


def test_signal_bridge_forwards_kernel_signals(kernel):
    server = ApiServer(kernel)
    published = []
    server.bridge.publish_threadsafe = published.append
    server._attach_signals()
    try:
        # Emit the way the engine does: context.signal() fills in the path.
        kernel.root.signal("spooler;queue", 3)
        kernel.process_queue()
    finally:
        server._detach_signals()

    codes = [event["code"] for event in published]
    assert "spooler;queue" in codes
    assert published[codes.index("spooler;queue")]["args"] == [3]
