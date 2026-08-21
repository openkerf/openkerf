"""Automatisch bewaren en herstellen."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.autosave import INTERVAL
from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "a.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def a_rect(client):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 10},
    ).json()["ids"][0]


def test_nothing_to_restore_at_first(client):
    assert client.get("/api/design/autosave").json()["exists"] is False


def test_a_design_is_saved_and_can_come_back(client, server):
    a_rect(client)
    assert server.autosave.save() is True

    state = client.get("/api/design/autosave").json()
    assert state["exists"] is True
    assert state["when"]

    client.post("/api/design/clear")
    response = client.post("/api/design/autosave/restore")

    assert response.status_code == 200
    assert len(client.get("/api/design").json()["elements"]) == 1


def test_an_empty_design_never_overwrites_a_good_one(client, server):
    """
    Otherwise "new design" erases precisely the file you need as soon as something goes
    wrong.
    """
    a_rect(client)
    server.autosave.save()
    client.post("/api/design/clear")

    assert server.autosave.save() is False
    assert client.get("/api/design/autosave").json()["exists"] is True


def test_saving_is_throttled(client, server):
    """Dragging one shape sends dozens of signals; they do not all go to disk."""
    a_rect(client)

    assert server.autosave.touch() is True
    assert server.autosave.touch() is False


def test_restoring_over_existing_work_is_refused(client, server):
    a_rect(client)
    server.autosave.save()

    response = client.post("/api/design/autosave/restore")

    assert response.status_code == 409


def test_it_can_be_thrown_away(client, server):
    a_rect(client)
    server.autosave.save()

    client.delete("/api/design/autosave")

    assert client.get("/api/design/autosave").json()["exists"] is False


def test_throwing_it_away_does_not_leave_you_without_a_net(client, server):
    """
    "Start with an empty canvas" throws the recovery file away, and after that you simply
    work on. The brake measures from the last write, so without this reset the autosave keeps
    quiet for a whole interval — and if you stop drawing in that time, there is nothing at all.
    Measured on a running server: discard, draw four shapes, wait thirty seconds, no
    herstelbestand.
    """
    a_rect(client)
    # Through touch(), not save(): the brake only starts running once something has been
    # written past it, and that is exactly the state where it goes wrong.
    assert server.autosave.touch() is True

    client.delete("/api/design/autosave")
    a_rect(client)

    assert server.autosave.touch() is True
    assert client.get("/api/design/autosave").json()["exists"] is True


def test_a_new_design_after_exporting_is_not_haunted(client, server):
    """
    Draw, export, start something new — and the next load asked whether you wanted to restore
    that just-exported drawing. There is nothing to recover there: it is on disk under your own
    name. A dialog that comes past on every new design you learn to click away, and then you
    miss it on the day it *is* about something.
    """
    a_rect(client)
    server.autosave.save()
    client.get("/api/design/export.svg")

    client.post("/api/design/clear")

    assert client.get("/api/design/autosave").json()["exists"] is False


def test_unsaved_work_keeps_its_net_even_when_you_clear_the_canvas(client, server):
    """
    The other side, and it weighs more: anybody who draws without saving and then clears the
    canvas has to be able to get it back.
    """
    a_rect(client)
    server.autosave.save()

    client.post("/api/design/clear")

    assert client.get("/api/design/autosave").json()["exists"] is True


def test_the_last_change_before_you_walk_away_still_lands(client, server, monkeypatch):
    """
    `touch` writes the first change and then brakes. Anybody who draws another two shapes in
    that interval and then walks to the machine never got a write for those two: no further
    signal comes to hang one on. Measured on a running server: three shapes in three seconds,
    process
    afgeschoten, één vorm in het herstelbestand.

    `flush` hangs off the scheduler as a kernel job and picks the tail up.
    """
    a_rect(client)
    assert server.autosave.touch() is True

    a_rect(client)
    a_rect(client)
    assert server.autosave.touch() is False, "the brake should still be on"
    # Nothing left to do without the tail: no change is coming.
    assert server.autosave.flush() is False, "inside the interval it keeps waiting"

    # The interval runs out while nobody is drawing any more.
    monkeypatch.setattr(
        "openkerf_api.autosave.time.monotonic",
        lambda: server.autosave._last + INTERVAL + 1,
    )

    assert server.autosave.flush() is True
    assert server.autosave.flush() is False, "once is enough; do not keep writing"


def test_clearing_the_design_does_not_use_up_the_throttle(client, server):
    """
    Clearing sends a tree signal, so `touch()` comes past — but there is nothing
    to save. Without this rule that *did* set the clock, and the first twenty
    seconds of your next design sat outside the safety net. Measured on a running
    server: clear, draw four shapes, no recovery file.
    """
    a_rect(client)
    assert server.autosave.touch() is True

    client.delete("/api/design/autosave")
    client.post("/api/design/clear")
    assert server.autosave.touch() is False, "an empty design writes nothing"

    a_rect(client)

    assert server.autosave.touch() is True


def test_after_restoring_the_next_change_is_saved_again(client, server):
    """The same after restoring: what you do after putting it back is protected."""
    a_rect(client)
    assert server.autosave.touch() is True
    client.post("/api/design/clear")
    client.post("/api/design/autosave/restore")

    a_rect(client)

    assert server.autosave.touch() is True


def test_autosaving_does_not_rename_your_document(kernel, client, tmp_path):
    """
    Saving automatically writes to `recovery.svg`, and `save` puts that name on
    `elements.basename`. That name then came back as the job name: every job in
    the queue was called "recovery.svg", even on a fresh design where nothing had
    been recovered. Two jobs with the same name cannot be told apart at a laser.
    """

    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    kernel.elements._filename = "/somewhere/my-design.svg"

    _autosave(kernel, tmp_path).save()

    assert kernel.elements.basename == "my-design.svg"


def test_autosaving_leaves_an_unnamed_document_unnamed(kernel, client, tmp_path):
    """Without a name it stays nameless — then our own job name makes something up."""

    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    before = getattr(kernel.elements, "basename", None)

    _autosave(kernel, tmp_path).save()

    assert getattr(kernel.elements, "basename", None) == before


def _autosave(kernel, tmp_path):
    """The autosave the way the server makes it, with a path of its own for the test."""
    from openkerf_api.autosave import Autosave
    from openkerf_api.document import Document
    from openkerf_api.drawing import Drawing

    return Autosave(kernel, Drawing(kernel), Document(), tmp_path / "herstel.svg")
