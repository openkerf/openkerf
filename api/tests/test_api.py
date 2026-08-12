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
        # Eerst stelt de server zich voor: aan dit id ziet een herverbindende
        # client of hij tegen hetzelfde proces praat als vóór de stilte, of dat
        # de engine herstart is en de pagina van een ander leven is (gat E2).
        hello = json.loads(ws.receive_text())
        assert hello["type"] == "hello"
        assert hello["instance"]
        payload = json.loads(ws.receive_text())
        assert payload["type"] == "snapshot"
        assert payload["data"]["devices"]


def test_write_routes_are_limited_to_the_known_set(client):
    """
    Phase 2 adds writes deliberately. Anything beyond this list — moving the
    head, toggling the laser — is a later phase and must be a conscious change.
    See test_write_actions.py for the auth guard on each of these.
    """
    posts = {
        route.path
        for route in client.app.routes
        if "POST" in getattr(route, "methods", set())
    }
    assert posts == {
        "/api/job/load",
        "/api/job/start",
        "/api/job/pause",
        "/api/job/resume",
        "/api/job/stop",
        "/api/spooler/clear",
        "/api/machines",
        "/api/machines/{path}/activate",
        "/api/machines/{path}/rename",
        "/api/design/clear",
        "/api/design/elements/{element_id}/image",
        "/api/design/elements/{element_id}/vectorise",
        "/api/design/elements/{element_id}/crop",
        "/api/project/open",
        "/api/design/elements",
        "/api/design/elements/delete",
        "/api/design/elements/duplicate",
        "/api/design/operations",
        # Volgorde en soort van een laag. Alle drie schrijven in de
        # bewerkingenboom en niet aan de machine: `move` schuift een laag op in
        # de brandvolgorde (L1), `sort` zet graveren vóór snijden in één
        # handeling (L2), en `type` vervangt een laag door een van een ander
        # soort met de vormen erin (L3) — dat laatste is een POST en geen PATCH
        # omdat de laag een nieuw id krijgt. Zie de sectie "Lagen" in
        # FEATURE-GAPS.md.
        "/api/design/operations/{operation_id}/move",
        # Gat L2: graveren vóór snijden in één handeling. Schrijft aan de
        # brandvolgorde in de boom, dus achter dezelfde poort.
        "/api/design/operations/sort",
        # Gat L3: het soort bewerking van een bestaande laag. Vervangt de knoop
        # en verhuist de referenties — een eigen route, want het id verandert.
        "/api/design/operations/{operation_id}/type",
        "/api/design/operations/sort",
        "/api/design/operations/{operation_id}/type",
        "/api/design/align",
        "/api/design/offset",
        "/api/design/simplify",
        "/api/design/effect",
        "/api/design/mirror",
        "/api/design/boolean",
        "/api/design/group",
        "/api/design/ungroup",
        "/api/design/move",
        "/api/machine/home",
        "/api/machine/move",
        "/api/machine/jog",
        "/api/machine/focus",
        "/api/machine/frame",
        # Gat J6: posities die deze machine onthoudt. Schrijft aan de settings
        # van de device-service, dus achter dezelfde poort als bewegen.
        "/api/machine/positions",
        "/api/machine/unlock",
        "/api/machine/lock",
        "/api/design/resize",
        "/api/design/rotate",
        "/api/design/assign",
        "/api/design/unassign",
        # Besluit B2: één klik op een paletkleur. Schrijft aan de boom (de
        # selectie verhuist) of aan de tekenkleur, dus achter dezelfde poort.
        "/api/design/palette",
        "/api/design/undo",
        "/api/design/redo",
        "/api/library/materials",
        "/api/library/presets",
        "/api/library/machines",
        "/api/library/presets/{preset_id}/apply",
        # Besluit B7: de bibliotheek uitwisselen. Uploaden en voorbeeld zijn ook
        # POSTs — ze schrijven een bestand in de uploadmap en horen dus achter
        # dezelfde poort als het importeren zelf.
        "/api/library/import/upload",
        "/api/library/import/preview",
        "/api/library/import",
        "/api/clipart/insert",
        "/api/design/fonts/import",
        "/api/sheets",
        "/api/sheets/{sheet_id}/activate",
        "/api/sheets/{sheet_id}/move",
        "/api/camera/start",
        "/api/camera/stop",
        "/api/camera/calibrate",
        "/api/camera/corrected",
        "/api/design/path",
        "/api/design/autosave/restore",
        "/api/design/nest",
        "/api/design/generate/grid",
        "/api/design/generate/radial",
        "/api/design/generate/polygon",
        "/api/design/generate/box",
        "/api/design/generate/qrcode",
        "/api/design/generate/arctext",
        "/api/design/generate/barcode",
        "/api/presetariat/import",
        "/api/library/testgrids",
        "/api/library/testgrids/{grid_id}/photo",
        "/api/library/testgrids/{grid_id}/remove-from-design",
        "/api/library/testgrids/{grid_id}/presets",
        # Rekent alleen; zie READ_ONLY_POSTS in test_write_actions.py.
        "/api/library/testgrids/preview",
    }

    methods = {
        method
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    # PUT kwam erbij met `/api/library/testgrids/{grid_id}/alignment` (T4): de
    # uitlijning van een testbord wordt in zijn geheel vervangen, niet deels
    # bijgewerkt. Dat is verdedigbaar REST, maar het is wel de enige PUT in een
    # API waar elke andere wijziging PATCH is — de keuze hoort bij de eigenaar
    # van dat oppervlak, niet bij deze test.
    assert methods <= {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}


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
