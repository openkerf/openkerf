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
        # First the server introduces itself: by this id a reconnecting client sees whether
        # it is talking to the same process as before the silence, or whether the engine has
        # restarted and the page is from another life (gap E2).
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
        # Starting over. Throws the design and the sheets away, so it belongs behind the same
        # gate as opening; the frontend asks first.
        "/api/project/new",
        "/api/design/elements",
        "/api/design/elements/delete",
        "/api/design/elements/duplicate",
        # Cut, copy and paste (usability round). The engine's clipboard is the store; these
        # three routes only set the emphasis and hand back the state. Pasting writes in the
        # tree, so behind the same gate as the rest.
        "/api/design/clipboard/copy",
        "/api/design/clipboard/cut",
        "/api/design/clipboard/paste",
        "/api/design/operations",
        # A layer's order and kind. All three write in the operation tree and not to the
        # machine: `move` shifts a layer in the burn order (L1), `sort` puts engraving before
        # cutting in one action (L2), and `type` replaces a layer with one of another kind with
        # the shapes in it (L3) — that last one is a POST and not a PATCH because the layer
        # gets a new id. See the "Layers" section in FEATURE-GAPS.md.
        "/api/design/operations/{operation_id}/move",
        # Gap L2: engraving before cutting in one action. Writes to the burn order in the
        # tree, so behind the same gate.
        "/api/design/operations/sort",
        # Gap L3: an existing layer's operation kind. Replaces the node and moves the
        # references — a route of its own, because the id changes.
        "/api/design/operations/{operation_id}/type",
        "/api/design/operations/sort",
        "/api/design/operations/{operation_id}/type",
        "/api/design/align",
        "/api/design/offset",
        "/api/design/simplify",
        # Rounding or chamfering corners. Rounding a rectangle stays a rectangle; everything
        # else becomes a path, and that is one-way.
        "/api/design/corners",
        "/api/design/split",
        "/api/design/fill",
        "/api/design/single-layer",
        "/api/design/operations/prune",
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
        # Gap J6: positions this machine remembers. Writes to the device service's settings,
        # so behind the same gate as movement.
        "/api/machine/positions",
        # Gap J12: the user's zero point. Like the positions it writes to the device
        # service's settings, and it moves the work on its way to the machine — so certainly
        # behind the gate.
        "/api/machine/origin",
        # Gap J11: adjusting speed and power during a running job. This sends realtime bytes
        # to the driver; that is touching the machine.
        "/api/job/adjust",
        "/api/machine/unlock",
        "/api/machine/connect",
        "/api/machine/disconnect",
        "/api/machine/lock",
        "/api/design/resize",
        "/api/design/rotate",
        "/api/design/assign",
        "/api/design/unassign",
        # Decision B2: one click on a palette colour. Writes to the tree (the selection
        # moves) or to the drawing colour, so behind the same gate.
        "/api/design/palette",
        "/api/design/undo",
        "/api/design/redo",
        "/api/library/materials",
        "/api/library/presets",
        "/api/library/machines",
        "/api/library/presets/{preset_id}/apply",
        # Decision B7: exchanging the library. Upload and preview are POSTs too — they write
        # a file in the upload directory and so belong behind the same gate as the import
        # itself.
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
        # Only computes: hands the shape back as path data, and leaves the drawing alone. See
        # test_generator_preview.py.
        "/api/design/generate/preview",
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
        # Gap T7: named generator settings. Writes only in the library — no machine, no
        # design — but in *your* library, so behind the same gate as the rest of it.
        "/api/library/testgrids/recipes",
        # Gap E5: reading a machine profile in. The upload writes a file in the upload
        # directory and the import creates a machine with settings that decide where the head
        # goes — both behind the gate.
        "/api/machines/import/upload",
        "/api/machines/import",
        # Rekent alleen; zie READ_ONLY_POSTS in test_write_actions.py.
        "/api/library/testgrids/preview",
        # Tile series: the board is bigger than the bed, so start/align/burn/advance/cancel
        # write the series out and drive the spooler.
        "/api/tiling/start",
        "/api/tiling/align",
        "/api/tiling/burn",
        "/api/tiling/advance",
        "/api/tiling/cancel",
    }

    methods = {
        method
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    # PUT arrived with `/api/library/testgrids/{grid_id}/alignment` (T4): a test board's
    # alignment is replaced in its entirety, not partly updated. That is defensible REST, but
    # it is the only PUT in an API where every other change is a PATCH — the choice belongs to
    # that surface's owner, not to this test.
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
