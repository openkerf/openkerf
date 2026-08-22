"""
Locking a shape: protected from moving, sizing and deleting.

The shapes you must not touch are the ones you touch by accident — an alignment
mark, a sheet outline, a jig. One drag box takes them along with everything else
and you see it when the part comes out 3 mm off.

What is worth testing here is not that a flag can be set. It is the line the lock
draws: which verbs it refuses, which it deliberately lets through, and that a
mixed selection refuses as a whole instead of doing half the job.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignEditor, DesignError
from openkerf_api.locking import is_locked
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "l.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def editor(kernel):
    return DesignEditor(kernel)


def a_rect(drawing, x=10.0):
    return drawing.create("rect", x_mm=x, y_mm=10, width_mm=20, height_mm=15)["ids"][0]


# ----------------------------------------------------------------- the flag


def test_locking_sets_the_engines_own_flag(kernel, drawing):
    """
    Not a flag of our own, on purpose.

    `core/node/node.py:85` already has `lock`, and lines 366-399 derive can_move,
    can_scale and can_remove from it. A design locked here therefore opens locked in
    the wxPython interface, and a shape the engine refuses to move is one we refuse
    for the same reason.
    """
    shape = a_rect(drawing)

    drawing.set_locked([shape], True)

    node = kernel.elements.find_node(shape)
    assert is_locked(node) is True
    # `can_move` is a method and `can_remove` a property — the engine mixes the two,
    # which is worth knowing before you write a guard against either.
    assert node.can_move() is False
    assert node.can_remove is False


def test_unlocking_gives_it_back(drawing, kernel):
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    result = drawing.set_locked([shape], False)

    assert result["locked"] is False
    assert is_locked(kernel.elements.find_node(shape)) is False


def test_locking_what_is_already_locked_changes_nothing(drawing):
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    again = drawing.set_locked([shape], True)

    assert again["changed"] == 0


def test_locking_needs_a_selection(drawing):
    # The empty selection is refused one layer earlier, by `_ids`, and its sentence
    # is the same for every edit — better one wording for "you picked nothing" than
    # a private one per verb.
    with pytest.raises(DesignError, match="at least one element"):
        drawing.set_locked([], True)


def test_the_snapshot_carries_the_lock(client, drawing):
    """The canvas draws no handles on a locked shape, so it has to know per snapshot."""
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    element = next(
        e for e in client.get("/api/design").json()["elements"] if e["id"] == shape
    )

    assert element["locked"] is True


# --------------------------------------------------- what a lock refuses


def test_a_locked_shape_cannot_be_moved_sized_or_turned(drawing, editor):
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    for call in (
        lambda: editor.move(shape, 5, 0),
        lambda: editor.resize(shape, 0, 0, 30, 30),
        lambda: editor.rotate(shape, 15),
    ):
        with pytest.raises(DesignError) as refusal:
            call()
        assert refusal.value.code == "edit.locked"


def test_a_locked_shape_cannot_be_deleted(drawing, kernel):
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    with pytest.raises(DesignError):
        drawing.delete([shape])

    assert kernel.elements.find_node(shape) is not None


def test_the_geometry_verbs_all_refuse(drawing):
    """
    Every verb that changes the shape itself, in one list.

    They come through two funnels (`Drawing._nodes` and `DesignEditor._target`), and
    the point of the list is the next verb somebody adds: if it forgets to ask, this
    test does not catch it, but the list says which verbs were meant to be here.
    """
    first = a_rect(drawing, x=10)
    second = a_rect(drawing, x=60)
    drawing.set_locked([first, second], True)

    for call in (
        lambda: drawing.mirror([first], "horizontal"),
        lambda: drawing.align([first, second], "left"),
        lambda: drawing.boolean([first, second], "union"),
        lambda: drawing.offset([first], 1.0),
        lambda: drawing.simplify([first]),
        lambda: drawing.add_effect([first], "hatch"),
        lambda: drawing.clipboard_cut([first]),
    ):
        with pytest.raises(DesignError) as refusal:
            call()
        assert refusal.value.code == "edit.locked"


def test_a_mixed_selection_refuses_as_a_whole(drawing, editor, kernel):
    """
    All or nothing.

    Moving the four unlocked shapes of five and saying so afterwards leaves a
    half-moved drawing and no way back except undo — and undo in this engine steps
    further than you think (see test_edits.py). So nothing moves, and the refusal
    counts both numbers.
    """
    locked = a_rect(drawing, x=10)
    free = a_rect(drawing, x=60)
    drawing.set_locked([locked], True)
    before = [round(v, 1) for v in kernel.elements.find_node(free).bounds]

    with pytest.raises(DesignError) as refusal:
        editor.move([locked, free], 5, 0)

    assert "1 of the 2" in str(refusal.value)
    assert [round(v, 1) for v in kernel.elements.find_node(free).bounds] == before


# ------------------------------------------- what a lock deliberately allows


def test_a_locked_shape_can_still_change_layer_colour_fill_and_bridges(drawing, kernel):
    """
    The line is geometry and existence, not purpose.

    A locked alignment mark that could not be given a layer would be a lock that
    stops you working rather than one that stops an accident, so these four are
    allowed — and the panel says so in the same words.
    """
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    assert drawing.single_layer([shape], kind="cut")["assigned"] == 1
    assert drawing.paint([shape], "#0000ff", None)["operation_id"]
    assert drawing.fill([shape])["filled"] == 1
    assert drawing.set_bridges([shape], count=4, length_mm=2)["bridged"] == 1


def test_a_locked_shape_can_be_copied_and_duplicated(drawing, kernel):
    """The original stays where it is, so there is nothing to protect."""
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)
    before = len(list(kernel.elements.elems()))

    drawing.clipboard_copy([shape])
    drawing.duplicate([shape])

    assert len(list(kernel.elements.elems())) == before + 1


def test_the_copy_of_a_locked_shape_is_not_locked_itself(drawing, kernel):
    """
    Otherwise every duplicate would have to be unlocked before you could place it,
    which is the opposite of what duplicating is for.
    """
    shape = a_rect(drawing)
    drawing.set_locked([shape], True)

    made = drawing.duplicate([shape])
    fresh = [i for i in made["ids"] if i != shape]

    assert fresh, "duplicate produced nothing new"
    assert all(not is_locked(kernel.elements.find_node(i)) for i in fresh)


# ----------------------------------------------------------------- the route


def test_the_route_locks_and_unlocks(client):
    shape = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 15},
    ).json()["ids"][0]

    locked = client.post("/api/design/lock", json={"ids": [shape], "locked": True})
    assert locked.status_code == 200, locked.text
    assert locked.json()["locked"] is True

    refused = client.post(
        "/api/design/move", json={"ids": [shape], "dx_mm": 5, "dy_mm": 0}
    )
    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "edit.locked"

    free = client.post("/api/design/lock", json={"ids": [shape], "locked": False})
    assert free.status_code == 200
    assert (
        client.post(
            "/api/design/move", json={"ids": [shape], "dx_mm": 5, "dy_mm": 0}
        ).status_code
        == 200
    )
