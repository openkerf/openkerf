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
    # Decision B7: taking a library in may overwrite measurements. From outside your own
    # computer that must never happen without a token.
    ("/api/library/import", {"json": {}}),
    ("/api/library/import/preview", {"json": {}}),
    # Gap T7: saving a named recipe writes in the library.
    ("/api/library/testgrids/recipes", {"json": {}}),
    # A photograph of a burned board, with and without the board's id in the path. Both
    # decide which board a picture is evidence for, and every preset drawn off that board
    # carries the picture — so from outside this computer neither may happen without a
    # token. The id route was only ever covered by the walk-every-route check above; since
    # it started reading the code in the pixels it earns a call of its own here.
    (
        "/api/library/testgrids/photo",
        {"files": {"file": ("board.jpg", b"not really a photograph", "image/jpeg")}},
    ),
    (
        "/api/library/testgrids/1/photo",
        {"files": {"file": ("board.jpg", b"not really a photograph", "image/jpeg")}},
    ),
    # Gap E5: reading a machine profile in creates a machine with a bed, an interface and an
    # address. That decides where the head goes.
    ("/api/machines/import", {"json": {}}),
    # A series. The upload writes a file in the upload directory, attaching decides what
    # fifty plates will say, and the five run verbs keep the bookkeeping of which plates
    # are burned and hand jobs to the spooler. `preview` is in here too although it
    # computes only: it reads a file off this machine's disk by name.
    ("/api/series/upload", {"files": {"file": ("n.csv", b"name\nAnna\n", "text/csv")}}),
    ("/api/series/attach", {"json": {}}),
    ("/api/series/preview", {"json": {}}),
    ("/api/series/plate", {"json": {}}),
    ("/api/series/row", {"json": {"row": 0}}),
    ("/api/series/start", {"json": {}}),
    ("/api/series/burn", {"json": {}}),
    ("/api/series/advance", {"json": {}}),
    ("/api/series/redo", {"json": {}}),
    ("/api/series/stop", {"json": {}}),
    # "Burn only once" decides whether a jig frame is in every plate of a series or in
    # the first one, so it decides what the laser does and belongs behind the gate with
    # the rest of the family.
    ("/api/design/elements/x/once", {"json": {"once": True}}),
    # Joining two names for one board, and two profiles for one laser. Both delete a row
    # and re-parent everything that hung off it; from outside this computer that must
    # never happen without a token.
    ("/api/library/materials/1/merge-into/2", {}),
    ("/api/library/machines/1/merge-into/2", {}),
    # Adopting the settings that belong to no machine claims they were measured on this
    # one. That is a statement about somebody's measurements, so it is gated.
    ("/api/library/presets/adopt", {"json": {}}),
    # Waving the starting-points offer away writes on the machine profile, and a machine
    # that has been told to stop offering never asks again.
    ("/api/library/starter/dismiss", {"json": {}}),
    # Staging writes a library file into the upload directory — the same directory that
    # holds bundles and machine profiles somebody else put there, which is the reason
    # `/api/library/import/upload` is in this list too.
    ("/api/presetariat/stage", {"json": {}}),
    # Remembering who is offering, and what came out of the material. Both are writes on
    # this computer — one beside the library, one on the row — and the handle is the
    # attribution the whole catalogue is licensed on, so it may not be settable from the
    # network without a token.
    ("/api/presetariat/contribution/1", {"json": {"by": "somebody"}}),
]

# And the same for DELETE, which had no list at all until this round — the guard test
# above walks the app and would have caught a missing dependency, but nothing proved that
# an unauthenticated *call* is refused. These three are the round's destructive verbs: a
# material with everything on it, a whole import, and a test board with its photograph.
WRITE_ROUTES_DELETE = [
    ("/api/library/materials/1", {}),
    ("/api/library/materials/1?with_everything=true", {}),
    ("/api/library/imports/presetariat-20260823-000000", {}),
    ("/api/library/testgrids/1", {}),
]

# The same requirement for the other verbs. A grid photo's alignment is a PUT and would
# otherwise fall outside the token check above.
WRITE_ROUTES_PUT = [
    ("/api/library/testgrids/1/alignment", {"json": {"corners": None}}),
]


@pytest.fixture
def local_client(kernel, tmp_path):
    # A library of its own, and therefore a sheets directory of its own: without a path this
    # test writes and reads in the user's *real* settings directory, down to their running
    # project's sheets.
    with TestClient(ApiServer(kernel, library_path=tmp_path / "w.db").build_app()) as client:
        yield client


@pytest.fixture
def lan_server(kernel, tmp_path):
    return ApiServer(
        kernel, bind="0.0.0.0", token="test-token", library_path=tmp_path / "lan.db"
    )


# --------------------------------------------------------------------- guard

# POSTs that compute rather than change. They take a body, which is why they
# are not GETs, but they touch neither the engine nor the database — see
# test_preview_plans_without_drawing, which proves it for this one.
READ_ONLY_POSTS = {
    "/api/library/testgrids/preview",
    # A generator's preview: computes the shape and sends it back as path data, without
    # hanging it on the drawing. Proved by test_the_preview_leaves_the_drawing_alone.
    "/api/design/generate/preview",
}

# `/api/series/preview` belongs to that family by what it does — it re-reads an uploaded
# file with a different answer to the header question and changes nothing — and it is
# deliberately *not* listed above. Being in this set means this test asks nothing of the
# route, and that route reads a file off this machine's disk by name: the upload
# directory it reads from also holds library bundles and machine profiles somebody else
# put there, so off localhost it must stay behind the token. It is in WRITE_ROUTES
# instead, where the guard is exercised rather than excused.


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


def test_machine_detection_is_not_a_write_route(local_client):
    """
    Decision B6: searching is reading. So the detection is a GET without a guard — and that
    is only allowed as long as it creates nothing and connects to nothing. If it ever becomes a
    POST, it belongs in the list above and behind the lock; this test is the place where that
    stands out.
    """
    scan = [r for r in local_client.app.routes if getattr(r, "path", "") == "/api/machines/scan"]
    assert scan and scan[0].methods == {"GET"}


def test_writes_are_open_on_localhost(local_client):
    assert local_client.post("/api/spooler/clear").status_code == 200


def test_writes_are_rejected_without_token_off_localhost(lan_server):
    with TestClient(lan_server.build_app()) as client:
        for path, body in WRITE_ROUTES:
            assert client.post(path, **body).status_code == 401, path
        for path, body in WRITE_ROUTES_PUT:
            assert client.put(path, **body).status_code == 401, path
        for path, body in WRITE_ROUTES_DELETE:
            assert client.delete(path, **body).status_code == 401, path


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


def test_importing_a_second_drawing_adds_to_the_first(kernel, local_client):
    """
    Importing adds. Emptying the bed first is what *opening* means.

    A sheet is a plate, and a plate holds more than one part: whoever imports a
    second drawing is laying a second part on it. It used to be gone — the
    interface emptied the bed before every import, so the first drawing
    disappeared. Measured then: five shapes, import one more, one shape on the bed.
    """
    def a_square(x: int) -> bytes:
        return (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="200mm">'
            b'<rect x="%d" y="10" width="20" height="10"/></svg>' % x
        )

    first = local_client.post(
        "/api/job/load", files={"file": ("one.svg", a_square(10), "image/svg+xml")}
    )
    assert first.status_code == 200, first.text
    after_one = len(list(kernel.elements.elems()))

    second = local_client.post(
        "/api/job/load", files={"file": ("two.svg", a_square(60), "image/svg+xml")}
    )

    assert second.status_code == 200, second.text
    assert len(list(kernel.elements.elems())) == after_one + 1
    # And it says what came in, so the interface can select exactly that.
    body = second.json()
    assert body["count"] == 1
    assert len(body["added"]) == 1
    assert kernel.elements.find_node(body["added"][0]) is not None


def test_an_import_onto_work_leaves_the_design_unsaved(kernel, local_client):
    """
    An empty bed plus a file *is* that file; a mixture exists nowhere on disk.

    The route marked the design clean after every load, which was right while
    importing replaced everything. Now that it adds, that would tell the recovery
    file there is nothing to keep — and the work you imported onto would be the
    thing that gets lost.
    """
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="80mm">'
        b'<rect x="1" y="1" width="20" height="10"/></svg>'
    )

    local_client.post("/api/job/load", files={"file": ("one.svg", svg, "image/svg+xml")})
    assert local_client.get("/api/design").json()["dirty"] is False

    local_client.post("/api/job/load", files={"file": ("two.svg", svg, "image/svg+xml")})

    assert local_client.get("/api/design").json()["dirty"] is True


def test_load_refuses_a_file_that_is_not_a_drawing(kernel, local_client):
    """
    A renamed or half-downloaded file came out as HTTP 200 {"ok": true}: the engine shouts
    "File is Malformed" on the console channel and then returns neatly. The user saw an empty
    bed and no reason at all.
    """
    response = local_client.post(
        "/api/job/load",
        files={"file": ("broken.svg", b"this is not a drawing", "image/svg+xml")},
    )

    assert response.status_code == 409
    message = " ".join(response.json()["detail"]["output"])
    assert "broken.svg" in message
    # The user's language, not the protocol's: no "Malformed", no temp path.
    assert "Malformed" not in message
    assert "/var/" not in message


def test_load_says_so_when_the_file_holds_no_shapes(kernel, local_client):
    """An SVG without shapes loads without complaint and gives an empty bed."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm"></svg>'

    response = local_client.post(
        "/api/job/load", files={"file": ("empty.svg", svg, "image/svg+xml")}
    )

    assert response.status_code == 409
    assert "no shapes" in " ".join(response.json()["detail"]["output"])


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
    This used to report "succeeded": you press start, the app says yes, and nothing
    happens at the machine. Then you stand there waiting.

    This refusal is `_require_something_to_burn`, shared with `build_job_bytes`
    (the Ruida upload), so it is our own `DesignError` — a plain-string `detail`,
    not `{"command", "output"}` like an engine-side `CommandError`.
    """
    local_client.post("/api/design/clear")

    response = local_client.post("/api/job/start")

    assert response.status_code == 409
    message = response.json()["detail"]
    assert "nothing ready to burn" in message
    # And it says what to do about it.
    assert "layer" in message


def test_layers_that_are_all_switched_off_count_as_empty(local_client):
    """
    A layer with 'burn along' off gives nothing. If *everything* is off, the job is
    empty — however much is on the canvas.
    """
    local_client.post("/api/design/clear")
    local_client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    assert local_client.post("/api/job/start").status_code == 200

    # Classification lands an element in several layers at once, so they all have
    # to be switched off.
    for operation in local_client.get("/api/design").json()["operations"]:
        if operation["element_ids"]:
            local_client.patch(
                f"/api/design/operations/{operation['id']}", json={"output": False}
            )

    assert local_client.post("/api/job/start").status_code == 409


# ------------------------------------------------------------- pauze/hervat


class _Driver:
    def __init__(self):
        self.paused = False


class _BrokenLihuiyu:
    """
    A lihuiyu device, with exactly the bug the real engine has.

    `resume` is in there twice (device.py:855 and device.py:1045); the second
    registration wins and starts the controller instead of the driver. So the flag
    stays put and the machine stays quiet. `pause` is a toggle.
    """

    def __init__(self):
        self.driver = _Driver()
        self.ran = []

    def console(self, line):
        command = line.strip()
        self.ran.append(command)
        if command == "pause":
            self.driver.paused = not self.driver.paused
        # "resume" deliberately does nothing to driver.paused here.

    def channel(self, _name):
        class Channel:
            @staticmethod
            def watch(_fn):
                pass

            @staticmethod
            def unwatch(_fn):
                pass

        return Channel()

    @property
    def device(self):
        return self


def test_resume_actually_resumes_on_a_lihuiyu():
    """
    Resuming has to make the machine run, not only put a line on the console.
    Without the check afterwards `driver.paused` stayed True and a paused job on a
    K40 never got going again.
    """
    kernel = _BrokenLihuiyu()
    runner = CommandRunner(kernel)

    runner.pause()
    assert kernel.driver.paused is True

    runner.resume()
    assert kernel.driver.paused is False, "the resume button left the machine standing"
    assert kernel.ran == ["pause", "resume", "pause"]


def test_pause_does_not_double_as_resume():
    """
    In the engine `pause` is a toggle. So pressing Pause twice set the machine
    burning again, under a button that says "Pause".
    """
    kernel = _BrokenLihuiyu()
    runner = CommandRunner(kernel)

    runner.pause()
    runner.pause()
    assert kernel.driver.paused is True


def test_resume_is_a_no_op_when_nothing_is_paused():
    kernel = _BrokenLihuiyu()
    runner = CommandRunner(kernel)

    runner.resume()
    assert kernel.ran == []
    assert kernel.driver.paused is False
