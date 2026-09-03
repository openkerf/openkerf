"""End-to-end checks against the FastAPI app and the plugin registration."""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    # A library of its own, and therefore state files of its own. Without a path this
    # server reads and writes in the developer's *real* settings directory — their
    # sheets, and since this round the list a series is attached to. `/api/job/start`
    # below vets that list, so a series left attached in the running app would decide
    # what this test file measures. The same trap CLAUDE.md records for `-P/--profile`.
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
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
        # A node on a segment (P1). The pen can draw a curve, and this is the other half:
        # repairing one that was imported.
        "/api/design/elements/{element_id}/nodes",
        "/api/design/elements/{element_id}/crop",
        # "Burn only once": a jig frame is cut once and then fifty pieces go through it.
        # Writes our own `mkonce` on the shape, so it is a write on the tree like a lock
        # or a colour — and it decides what a series leaves off forty-nine plates.
        "/api/design/elements/{element_id}/once",
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
        # Locking a shape: the engine's own `lock` flag, so a write on the tree.
        "/api/design/lock",
        # Shapes lying on top of each other. Looking is a GET; removing takes ids in
        # the body and deletes, so it is a write like any other delete.
        "/api/design/duplicates/remove",
        "/api/design/fill",
        "/api/design/single-layer",
        "/api/design/operations/prune",
        "/api/design/effect",
        # Gap T1: bridges (tabs) in a cut line. Writes two attributes on the shapes, so
        # behind the same gate as the rest of the tree; `clear` is a POST because the ids
        # travel in the body.
        "/api/design/bridges",
        "/api/design/bridges/clear",
        # A stencil sets the same two attributes as a bridge does, on the same shapes, and
        # is behind the same gate for the same reason. It carries a `preview` flag that
        # writes nothing, which is why it is not in READ_ONLY_POSTS: one route with two
        # behaviours belongs on the strict side of that line.
        "/api/design/stencil",
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
        # The rotary. Machine-wide settings that scale Y on the way to the machine, so a
        # write that changes what burns — behind the gate with the rest of the machine.
        "/api/machine/rotary",
        "/api/machine/rotary/calibrate",
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
        # Two names for one board, joined. Moves every setting, board and recipe onto one
        # material and deletes the other, so it writes more than a rename does.
        "/api/library/materials/{material_id}/merge-into/{target_id}",
        "/api/library/presets",
        # The settings that belong to no machine, onto the active one. Writes
        # `machine_id` on rows the user did not name one by one, so it is behind the gate
        # with the rest of the library.
        "/api/library/presets/adopt",
        "/api/library/machines",
        # The other half of the same story: two profiles for one laser. Deletes a profile
        # and re-parents its presets and boards.
        "/api/library/machines/{machine_id}/merge-into/{target_id}",
        # Waving the starting-points offer away, or saying the tube power is not known.
        # One column on the machine profile, but a write on the library all the same.
        "/api/library/starter/dismiss",
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
        # Gap G1: the field of slits that makes sheet material bend.
        "/api/design/generate/hinge",
        # Gap H4: a focus test. Draws a board and its heights ride along in the plan as
        # `z_move` steps, so it writes on the tree like any other generator.
        "/api/design/generate/focus",
        # Writes a real .openkerf-lib in the upload directory out of catalogue rows, and
        # answers with the same preview as an uploaded library. It writes no database row
        # itself — `/api/library/import` does that — but it does write a file on this
        # machine's disk, so it is gated exactly like the upload it replaces.
        "/api/presetariat/stage",
        # Offering one of your own settings. It writes the contributor's handle beside
        # the library and the outcome of the burn onto the row, which is why a GET beside
        # it does the looking: the panel asks what a contribution would say before
        # anything is written.
        "/api/presetariat/contribution/{preset_id}",
        "/api/library/testgrids",
        "/api/library/testgrids/{grid_id}/photo",
        # A photograph with no board id in the path: it reads the code on the plank and
        # names its own board. A write like the id route beside it — it stores a file and
        # points a row at it — and it is in this list separately because a route that
        # writes without being told *which* row to write on is exactly the kind of thing
        # this list exists to make somebody type out on purpose.
        "/api/library/testgrids/photo",
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
        # Calculates only; see READ_ONLY_POSTS in test_write_actions.py.
        "/api/library/testgrids/preview",
        # Tile series: the board is bigger than the bed, so start/align/burn/advance/cancel
        # write the series out and drive the spooler.
        "/api/tiling/start",
        "/api/tiling/align",
        "/api/tiling/burn",
        "/api/tiling/advance",
        "/api/tiling/cancel",
        # Gap H2: print and cut. Pointing out the marks, driving to them and clearing the
        # alignment all decide where a job burns, so all three are behind the gate.
        "/api/printcut/marks",
        "/api/printcut/measure",
        "/api/printcut/clear",
        # A series: one design burned once per row of a list. The upload writes a file
        # in the upload directory; attach writes the list beside the library and
        # re-renders the bed; start/burn/advance/redo/stop keep a run's bookkeeping and
        # drive the spooler. All six change something.
        "/api/series/upload",
        "/api/series/attach",
        # Pointing the bed at one row is reading, but it writes the run file's pointer
        # and re-renders the drawing, so it is gated like the rest of the family.
        # Filling a plate with one piece per row: it copies shapes onto the drawing, so
        # it is a write like any other generator. The GET beside it only counts.
        "/api/series/plate",
        "/api/series/row",
        "/api/series/start",
        "/api/series/burn",
        "/api/series/advance",
        "/api/series/redo",
        "/api/series/stop",
        # Calculates only — it reads the uploaded file again with a different answer to
        # the header question and writes nothing. Behind the gate all the same, because
        # it reads a file off this machine's disk by name and that directory also holds
        # what other import routes put there. See READ_ONLY_POSTS in
        # test_write_actions.py for why it is deliberately not listed as exempt.
        "/api/series/preview",
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


# ------------------------------------------- the library's own verbs, at the route
#
# The library functions behind these are pinned in test_library_edit.py. What is checked
# here is the wiring, which is where a verb the interface cannot reach comes from: a body
# key nobody sends, or a flag spelled differently on the two sides.


def test_a_material_can_be_renamed_merged_and_counted_over_http(client):
    """
    None of these three verbs existed as a route until this round, which is why the live
    library holds both `Multiplex berken` and `Berkentriplex` for one board: with no
    PATCH, correcting a name meant adding a second material beside the first.
    """
    library = client.server.library
    keep = client.post(
        "/api/library/materials", json={"name": "Berkentriplex"}
    ).json()
    spare = library.add_material("Multiplex berken")
    library.add_preset(
        material_id=spare["id"],
        operation="snijden",
        speed_mm_s=12,
        power_percent=70,
    )

    renamed = client.patch(
        f"/api/library/materials/{keep['id']}",
        json={"name": "Birch plywood", "synonyms": ["berkentriplex"]},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Birch plywood"
    assert "berkentriplex" in renamed.json()["synonyms"]

    usage = client.get(f"/api/library/materials/{spare['id']}/usage").json()
    assert usage["presets"] == 1

    merged = client.post(
        f"/api/library/materials/{spare['id']}/merge-into/{keep['id']}"
    )
    assert merged.status_code == 200, merged.text
    assert [m["name"] for m in client.get("/api/library/materials").json()] == [
        "Birch plywood"
    ]
    assert len(client.get("/api/library/presets").json()) == 1


def test_removing_a_material_that_carries_work_needs_a_second_word(client):
    """
    Measured on a copy of the live library: deleting `Berkentriplex` silently took six
    settings, two of them measured with photographs, orphaned two boards — and the route
    answered `{"removed": 6}`. That was a data-loss button with a one-word label.

    The flag is a query parameter, so this is also the check that the two sides spell it
    the same way: a body on a DELETE does not survive every client, and a flag that never
    arrives makes the refusal permanent.
    """
    library = client.server.library
    material = library.add_material("MDF")
    library.add_preset(
        material_id=material["id"],
        operation="snijden",
        speed_mm_s=10,
        power_percent=80,
    )

    refused = client.delete(f"/api/library/materials/{material['id']}")

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "library.material.inUse"
    assert "1" in refused.json()["detail"]

    gone = client.delete(
        f"/api/library/materials/{material['id']}?with_everything=true"
    )

    assert gone.status_code == 200, gone.text
    assert gone.json()["presets"] == 1
    assert client.get("/api/library/materials").json() == []
    assert client.get("/api/library/presets").json() == []


def test_a_refusal_of_ours_inside_a_command_route_is_a_409_and_not_a_500(client):
    """
    A route wrapped in act() must answer our own refusals, not fall over on them.

    act() caught CommandError only, so a DesignError raised anywhere inside
    /api/job/start — the one button every client presses to burn — left FastAPI to
    answer 500 with no sentence and no code, and the panel could then only say that
    something went wrong. Anything that vets a job before it goes to the spooler
    raises exactly that, so this is the contract of the route and not a detail of one
    caller.

    The refusal is raised from the first thing the route does with the drawing, which
    is also why this test is safe to run with a machine reachable: no plan is built
    and nothing reaches the spooler.
    """

    def no_burn_while_something_else_counts():
        raise DesignError(
            "A series is going, so this button would burn one plate and count "
            "nothing. Burn from the Series panel.",
            code="series.runGoing",
        )

    client.server.printcut.mutators = no_burn_while_something_else_counts

    response = client.post("/api/job/start")
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.runGoing"
    # A string, not the {command, output} shape act() gives an engine failure: every
    # client in this API reads `detail` as the sentence to show.
    assert response.json()["detail"].startswith("A series is going")


def test_burn_only_once_is_one_route_with_two_answers(client):
    """
    The route that marks a jig frame, and the same route that unmarks it.

    Absent `once` means switching it on, because that is what the menu row does the
    first time it is pressed; the other wording sends false. Both go through `manage()`,
    so a shape that is not there answers 409 with a sentence rather than 500 — the
    right-click menu is built from a snapshot that can be a second old.
    """
    element = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 20},
    ).json()["ids"][0]

    assert client.post(f"/api/design/elements/{element}/once").status_code == 200
    assert client.get("/api/design").json()["elements"][0]["once"] is True

    off = client.post(f"/api/design/elements/{element}/once", json={"once": False})

    assert off.status_code == 200
    assert off.json()["changed"] == 1
    assert client.get("/api/design").json()["elements"][0]["once"] is False
    assert client.post("/api/design/elements/nope/once").status_code == 409


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
