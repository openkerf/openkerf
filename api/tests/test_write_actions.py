"""Phase 2: write actions, their guard rails and device-dependent availability."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.commands import CommandError, CommandRunner
from openkerf_api.server import ApiServer

WRITE_ROUTES = [
    ("/api/job/start", {}),
    ("/api/job/pause", {}),
    ("/api/job/resume", {}),
    ("/api/job/stop", {}),
    ("/api/spooler/clear", {}),
]


@pytest.fixture
def local_client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as client:
        yield client


@pytest.fixture
def lan_server(kernel):
    return ApiServer(kernel, bind="0.0.0.0", token="test-token")


# --------------------------------------------------------------------- guard

# POSTs that compute rather than change. They take a body, which is why they
# are not GETs, but they touch neither the engine nor the database — see
# test_preview_plans_without_drawing, which proves it for this one.
READ_ONLY_POSTS = {"/api/library/testgrids/preview"}


def test_every_mutating_route_requires_the_write_guard(local_client):
    """A new write endpoint must not slip in without authentication."""
    mutating = [
        route
        for route in local_client.app.routes
        if getattr(route, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}
        and route.path not in READ_ONLY_POSTS
    ]
    assert mutating, "there are write routes"
    for route in mutating:
        names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
        assert "require_write" in names, f"{route.path} has no write guard"


def test_writes_are_open_on_localhost(local_client):
    assert local_client.post("/api/spooler/clear").status_code == 200


def test_writes_are_rejected_without_token_off_localhost(lan_server):
    with TestClient(lan_server.build_app()) as client:
        for path, body in WRITE_ROUTES:
            assert client.post(path, **body).status_code == 401, path


def test_writes_accept_bearer_token(lan_server):
    with TestClient(lan_server.build_app()) as client:
        response = client.post(
            "/api/spooler/clear", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200


def test_writes_accept_header_token(lan_server):
    with TestClient(lan_server.build_app()) as client:
        response = client.post(
            "/api/spooler/clear", headers={"X-OpenKerf-Token": "test-token"}
        )
        assert response.status_code == 200


def test_wrong_token_is_rejected(lan_server):
    with TestClient(lan_server.build_app()) as client:
        response = client.post(
            "/api/spooler/clear", headers={"Authorization": "Bearer nope"}
        )
        assert response.status_code == 401


def test_reading_stays_open_off_localhost(lan_server):
    with TestClient(lan_server.build_app()) as client:
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/capabilities").json()["auth_required"] is True


# -------------------------------------------------------------- job pipeline

def test_start_spools_a_job(kernel, local_client):
    kernel.console("rect 0 0 2cm 2cm\n")
    kernel.console("element* cut -s 10 -p 40\n")

    response = local_client.post("/api/job/start")

    assert response.status_code == 200
    assert len(kernel.device.spooler.queue) == 1
    assert any("Spooled Plan" in line for line in response.json()["output"])


def test_clear_empties_the_queue(kernel, local_client):
    kernel.console("rect 0 0 2cm 2cm\n")
    kernel.console("element* cut -s 10 -p 40\n")
    local_client.post("/api/job/start")
    assert len(kernel.device.spooler.queue) == 1

    assert local_client.post("/api/spooler/clear").status_code == 200
    assert len(kernel.device.spooler.queue) == 0


def test_load_accepts_an_upload(kernel, local_client):
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm">'
        b'<rect x="1" y="1" width="20" height="10"/></svg>'
    )
    before = len(list(kernel.elements.elems()))

    response = local_client.post(
        "/api/job/load", files={"file": ("design.svg", svg, "image/svg+xml")}
    )

    assert response.status_code == 200
    assert len(list(kernel.elements.elems())) > before


def test_upload_filename_cannot_escape_the_upload_directory(kernel):
    server = ApiServer(kernel)
    target = server._upload_path("../../etc/passwd")
    assert target.parent == server._upload_dir
    assert target.name == "passwd"


# ------------------------------------------------------------- capabilities

def test_capabilities_reflect_the_active_device(kernel, local_client):
    """pause/resume/estop come from the device service, not from the kernel."""
    dummy = local_client.get("/api/capabilities").json()["actions"]
    assert dummy["start"] is True
    assert dummy["pause"] is False

    kernel.console("service device start ruida -i\n")

    ruida = local_client.get("/api/capabilities").json()["actions"]
    assert ruida["pause"] is True
    assert ruida["resume"] is True
    assert ruida["stop"] is True


def test_unsupported_action_reports_a_conflict(local_client):
    """The dummy device has no pause; that must be a clean 409, not a 500."""
    response = local_client.post("/api/job/pause")
    assert response.status_code == 409
    assert "not a registered command" in " ".join(response.json()["detail"]["output"])


# ------------------------------------------------------------- CommandRunner

def test_runner_raises_on_unknown_command(kernel):
    runner = CommandRunner(kernel)
    with pytest.raises(CommandError):
        runner.run("this_command_does_not_exist")


def test_runner_strips_ansi_from_output(kernel):
    runner = CommandRunner(kernel)
    output = runner.run("version")
    assert output
    assert not any("\x1b[" in line for line in output)


def test_supports_matches_exactly(kernel):
    runner = CommandRunner(kernel)
    assert runner.supports("spool") is True
    assert runner.supports("spo") is False


def test_starting_an_empty_design_is_refused(local_client):
    """
    Dit meldde eerder "gelukt": je drukt op starten, de app zegt ja, en er
    gebeurt niets bij de machine. Dan sta je ernaast te wachten.
    """
    local_client.post("/api/design/clear")

    response = local_client.post("/api/job/start")

    assert response.status_code == 409
    melding = " ".join(response.json()["detail"]["output"])
    assert "niets klaar om te branden" in melding
    # En het zegt wat je eraan doet.
    assert "laag" in melding


def test_layers_that_are_all_switched_off_count_as_empty(local_client):
    """
    Een laag met 'meebranden' uit levert niets op. Staat álles uit, dan is de
    job leeg — ook al staat er van alles op het canvas.
    """
    local_client.post("/api/design/clear")
    local_client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    assert local_client.post("/api/job/start").status_code == 200

    # Een element belandt door de classificatie in meerdere lagen tegelijk, dus
    # ze moeten allemaal uit.
    for operation in local_client.get("/api/design").json()["operations"]:
        if operation["element_ids"]:
            local_client.patch(
                f"/api/design/operations/{operation['id']}", json={"output": False}
            )

    assert local_client.post("/api/job/start").status_code == 409
