"""
The pre-flight of a series: the time of the plate now on the bed, times the plates left.

`/api/job/estimate` reads the drawing, and during a series the drawing holds more than
this plate is going to burn: the places the list has no names left for still carry the
literal `{name#+2}` as real geometry, and a jig frame marked "burn only once" is still
there on the second plate. The burn takes both of them out through
`series.OverrunMutator`; before this file the estimate did not, and the interface was
about to multiply the difference by the plates still to come.

Every number in these docstrings was measured on the design `a_series()` below — three
places on one sheet (`{name}`, `{name#+1}`, `{name#+2}`), five names, one frame marked
burn-once — with the pointer on the last sheetful, which is the plate that costs stock.

No job here reaches a machine: the kernel fixture activates the dummy device, so a burn
spools and nothing moves.
"""

import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api.series import OverrunMutator
from openkerf_api.server import ApiServer

FIVE = ("Anna", "Bram", "Cees", "Daan", "Eva")


@pytest.fixture
def server(kernel, tmp_path):
    # A library of its own, so the series file lands beside it in tmp_path and not in the
    # developer's real settings directory next to the list their own app has attached.
    return ApiServer(kernel, library_path=tmp_path / "estimate.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def a_text(client, template: str, y: float):
    response = client.post(
        "/api/design/elements",
        json={
            "type": "text",
            "x_mm": 10.0,
            "y_mm": y,
            "text": template,
            "font_size_mm": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def a_series(client, names=FIVE):
    """
    Three places on a sheet, five names, and a jig frame that is cut once.

    The layer list is thrown away once the shapes are on the bed and one layer is made
    here, with every shape assigned to it. Not tidiness: the engine loads the layer list
    of whatever ran last out of an `operations.cfg` that hangs on the kernel *name* and
    ignores `ignore_settings` (`core/elements/elements.py:764`, and the row CLAUDE.md
    keeps about it). Measured while writing this file: a text landed in an inherited
    engrave layer with `output` off, so the burn refused with "There is nothing ready to
    burn"; and assigning to a layer of our own is not enough either, because a layer
    holds *references* — the shapes then sat in two layers and would have burned twice.

    Returns the id of the frame and the id of the text that reads past the end of the
    list on the last sheetful — the two shapes the last burn leaves out.
    """
    shapes = [
        a_text(client, "{name}", 10.0),
        a_text(client, "{name#+1}", 30.0),
        a_text(client, "{name#+2}", 50.0),
    ]
    overrun = shapes[-1]
    frame = client.post(
        "/api/design/elements",
        json={
            "type": "rect",
            "x_mm": 5.0,
            "y_mm": 5.0,
            "width_mm": 90.0,
            "height_mm": 60.0,
        },
    ).json()["ids"][0]
    shapes.append(frame)
    marked = client.post(f"/api/design/elements/{frame}/once", json={"once": True})
    assert marked.status_code == 200, marked.text
    # After the shapes, not before: placing one makes a layer for it, so a layer list
    # cleared first would be back by now.
    assert client.delete("/api/design/operations").status_code == 200
    layer = client.post(
        "/api/design/operations", json={"type": "cut", "speed": 20, "power_percent": 65}
    ).json()
    assigned = client.post(
        "/api/design/assign", json={"ids": shapes, "operation_id": layer["id"]}
    )
    assert assigned.status_code == 200, assigned.text
    burning = [row for row in client.get("/api/job/layers").json()["layers"]]
    assert [row["elements"] for row in burning] == [4], burning

    csv = ("name\n" + "\n".join(names) + "\n").encode("utf-8")
    uploaded = client.post(
        "/api/series/upload", files={"file": ("names.csv", csv, "text/csv")}
    )
    assert uploaded.status_code == 200, uploaded.text
    attached = client.post(
        "/api/series/attach", json={"file": uploaded.json()["file"]}
    )
    assert attached.status_code == 200, attached.text
    # Three places on the sheet, so one burn eats three rows and five names are two
    # plates. The second is the short one.
    assert attached.json()["step"] == 3
    assert attached.json()["burns"] == 2
    return frame, overrun


def to_the_last_sheetful(client):
    """Start, burn the full sheet, move on: the pointer lands on the short plate."""
    assert client.post("/api/series/start", json={"row": 0}).status_code == 200
    burned = client.post("/api/series/burn", json={})
    assert burned.status_code == 200, burned.text
    assert burned.json()["burned_rows"] == [0, 1, 2]
    moved = client.post("/api/series/advance")
    assert moved.status_code == 200, moved.text
    assert moved.json()["current_row"] == 3


def estimate(client, exact: bool = False) -> dict:
    response = client.get(
        "/api/job/estimate" + ("?exact=1" if exact else "")
    )
    assert response.status_code == 200, response.text
    return response.json()


def plan_of_the_burn(server, mutators=()):
    """
    The real cut plan, built the way a burn builds it, harvested for time and pieces.

    The independent reference for the two tests that ask whether the estimate agrees with
    the burn. It runs the phases `Drawing._plan_estimate_locked` runs and sums the same
    two durations, with the difference that the mutators go on in between — which is
    exactly the thing the estimate route could not do before.
    """
    runner = server.commands
    with runner.claim_plan():
        try:
            runner.run("plan clear copy")
            runner._apply_mutators(list(mutators))
            runner.run("plan preprocess validate blob preopt optimize")
            seconds = 0.0
            objects = 0
            for item in server.kernel.planner.default_plan.plan:
                for name in ("duration_cut", "duration_travel"):
                    call = getattr(item, name, None)
                    if callable(call):
                        seconds += float(call())
                try:
                    objects += len(list(item))
                except TypeError:  # a console step is not a bag of cut objects
                    pass
            return round(seconds, 1), objects
        finally:
            runner.run("plan clear")


# ------------------------------------------------------- the plate on the bed


def test_the_estimate_leaves_out_the_place_this_plate_has_no_name_for(client):
    """
    The last sheetful is short, and the estimate must be short with it.

    Catches the estimate counting the literal placeholder as work. Five names over three
    places leaves the third place on the second plate with no row to fill it, and the
    engine does not leave it blank — `core/wordlist.py:597` only substitutes when the
    value is not None, so the nine characters `{name#+2}` stay in the text and are
    rendered as a path like any other. The burn removes that shape
    (`series.OverrunMutator`); this route did not.

    Measured on this design, geometry route: the drawing as it stands is **36.2 s over 4
    parts** and this plate is **9.5 s over 2 parts**. Of the 26.7 s difference the frame
    is 15.0 s and the literal placeholder 11.3 s, and both were being multiplied by the
    plates still to come. The reference here is `Drawing.estimate` called straight, which
    is literally what this route did before, so the assertion is the bug and not a
    threshold somebody has to maintain.
    """
    frame, overrun = a_series(client)
    to_the_last_sheetful(client)
    server = client.server

    as_it_stands = server.drawing.estimate(
        server.library, server.provenance, server._active_sheet()
    )
    answer = estimate(client)

    # Two shapes left of four: this plate burns `Daan` and `Eva` and nothing else.
    assert as_it_stands["parts"] == 4
    assert answer["parts"] == 2
    assert answer["method"] == "geometry"
    # And the two that are gone are gone from the seconds too, not only from the count.
    assert answer["seconds"] < as_it_stands["seconds"] / 2


def test_a_jig_frame_is_not_in_the_estimate_of_the_second_plate(client):
    """
    A frame that is cut once is not cut again, and not timed again either.

    Catches the estimate charging a burn-once shape to every plate. The frame here is
    90×60 mm of cutting — measured 15.0 s on its own — and on plate two of fifty it is
    not going to be cut at all, because `OverrunMutator` takes any `mkonce` child out of
    every burn after the first of the run.

    The first plate does carry it, and that is the other half of the same rule: `first`
    means the first plate of *this run*, so an operator who starts at row 12 gets the jig
    at that moment. Measured here: **31.5 s over 4 parts** on the first plate against
    **9.5 s over 2 parts** on the second.
    """
    a_series(client)
    assert client.post("/api/series/start", json={"row": 0}).status_code == 200

    first = estimate(client)
    assert first["parts"] == 4, "the first plate of a run cuts the jig"

    assert client.post("/api/series/burn", json={}).status_code == 200
    assert client.post("/api/series/advance").status_code == 200
    second = estimate(client)

    assert second["parts"] == 2
    assert second["seconds"] < first["seconds"]


def test_the_estimate_and_the_burn_agree_to_the_second(client):
    """
    Both routes answer about one design: the one the burn is going to send.

    This is the test that makes the fix a fact rather than a hope. The estimate cannot
    hand a plan mutator to either of its routes — the geometry one never builds a plan
    and the exact one builds it in one console line — so it hides what the mutator would
    remove instead, and this asserts that hiding and removing come to the same plan.

    Measured on this design: the plan built as this route used to build it held **409 cut
    objects and 37.3 s**; built with `OverrunMutator` it holds **172 objects and 9.8 s**;
    built with those same shapes hidden — which is what `exact=1` now does — it holds
    **172 objects and 9.8 s**, equal to the digit. The engine is why: every operation
    skips a hidden child on its way to cutcode (`core/node/op_cut.py:458`,
    `op_engrave.py:411`, `op_dots.py:313`, `op_raster.py:492`).

    Catches a hiding mechanism that the engine honours only for some kinds of layer, and
    it would catch a future engine that stopped honouring it at all — which would put the
    estimate back to answering about a job nobody runs.
    """
    a_series(client)
    to_the_last_sheetful(client)
    server = client.server

    without = plan_of_the_burn(server)
    with_mutator = plan_of_the_burn(
        server, [OverrunMutator(server.kernel.elements, first=False)]
    )
    exact = estimate(client, exact=True)

    assert without[1] > with_mutator[1], "the mutator has to take work out"
    assert exact["seconds"] == with_mutator[0]
    assert exact["seconds"] < without[0]
    # The cheap route is measured on the same design, so it may differ from the plan only
    # by what it always differs by: the travel order the optimiser picks. Measured 9.5 s
    # against 9.8 s, 3 % apart.
    assert abs(estimate(client)["seconds"] - with_mutator[0]) < with_mutator[0] / 10


# --------------------------------------------------------- the plates to come


def test_the_estimate_says_how_many_burns_are_still_due(client):
    """
    The number the interface multiplies by comes from the sum that made the seconds.

    A job of fifty burns must never show the time of one, and the way that goes wrong is
    the panel counting plates itself. So the answer carries the count, and it counts the
    way the run does: the burns whose rows are not all done — exactly how many times Burn
    still has to be pressed, because that is the set `Series.advance` walks.

    Catches the plausible arithmetic `burns - current_burn + 1`. Here that is the same
    number until a plate is redone: this list is five names over three places, so two
    burns, and asking for the first one again once both are burned leaves one plate due
    while the naive sum says two. Measured: 2, then 1, then 0 with the list burned out,
    then 1 after the redo — where the naive sum says 2.
    """
    a_series(client)
    assert estimate(client)["burns_left"] == 1, "nothing running is one press of Burn"

    assert client.post("/api/series/start", json={"row": 0}).status_code == 200
    assert estimate(client)["burns_left"] == 2

    assert client.post("/api/series/burn", json={}).status_code == 200
    assert client.post("/api/series/advance").status_code == 200
    assert estimate(client)["burns_left"] == 1

    # The second plate too. Nothing is due now, and the answer says nought rather than
    # keeping a plate on the clock the operator has already made.
    assert client.post("/api/series/burn", json={}).status_code == 200
    assert estimate(client)["burns_left"] == 0

    # The first plate came out spoiled, so it is due again — one plate and not two,
    # although the pointer is back at burn one of two.
    assert client.post("/api/series/redo", json={"row": 0}).status_code == 200
    assert client.get("/api/series").json()["current_burn"] == 1
    assert estimate(client)["burns_left"] == 1


def test_the_time_of_the_afternoon_is_the_plate_times_the_plates_left(client):
    """
    One multiplication, done once, where the seconds are.

    Catches two numbers on one screen that do not multiply: `seconds_total` is the
    *rounded* `seconds` times `burns_left`, so a panel showing "9.5 s each, 2 to go,
    19.0 s" can be read straight down. Measured on the first plate of this run:
    31.5 s × 2 = 63.0 s.

    Without a series both fields still stand there, so the pre-flight has one field to
    draw and no branch of its own: `burns_left` 1 and `seconds_total` equal to `seconds`.
    """
    plain = estimate(client)
    assert plain["burns_left"] == 1
    assert plain["seconds_total"] == plain["seconds"]

    a_series(client)
    assert client.post("/api/series/start", json={"row": 0}).status_code == 200
    answer = estimate(client)

    assert answer["burns_left"] == 2
    assert answer["seconds_total"] == round(answer["seconds"] * 2, 1)


def test_a_plain_burn_is_estimated_as_the_plain_burn_now_is(client):
    """
    A list attached without a run is still a list, and both sides now say so.

    This test used to pin the opposite, and it was right to at the time: the plain Burn
    button composed only the print-and-cut pose, so on the last sheetful it really did
    engrave the nine characters `{name#+2}`, and an estimate that left them out would
    have been the same lie pointing the other way. What changed is the burn, not the
    clock — `/api/job/start` now composes `Series.plain_mutators()`, so the places this
    row has no names for are left out of the plate as well as out of the number.

    So what is worth holding here is the agreement, in both directions: the estimate
    counts the parts the plain burn will really make, and one press of Burn is all that
    is due. Three of the four shapes, with the pointer on the last sheetful — the place
    reading `{name#+2}` is gone because the list has no fifth name, and the jig frame
    stays, because with no run going there is no earlier plate it could already have
    been cut on.
    """
    a_series(client)
    assert client.post("/api/series/row", json={"row": 3}).status_code == 200

    answer = estimate(client)

    assert answer["parts"] == 3
    assert answer["burns_left"] == 1
    assert answer["seconds_total"] == answer["seconds"]


def test_a_design_with_no_list_takes_exactly_the_route_it_always_took(client):
    """
    Every job in the app passes this seam, so "nothing attached" has to mean "no change
    at all" — not a mutator that happens to remove nothing.

    Catches the tempting simplification of always installing the mutator and letting it
    decide per shape: it walks every node of every plan step, and a plain design would
    pay for a feature it is not using.
    """
    from openkerf_api.series import Series

    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    assert made.status_code == 201, made.text

    series = client.server.series
    assert isinstance(series, Series)
    assert series.plain_mutators() == []


def test_measuring_leaves_the_drawing_exactly_as_it_was(client):
    """
    A GET may not change the drawing, and hiding shapes to measure them is a change.

    Two ways this goes wrong. A shape hidden for the measurement and not put back is a
    shape gone from the canvas and from the next thing that saves — so every flag is
    restored in a `finally`. And a shape the *user* hid must stay hidden: it is not
    burned either way, so the pre-flight has no business switching it on. Catches a
    restore loop that sets every node visible instead of the ones it hid.
    """
    frame, overrun = a_series(client)
    to_the_last_sheetful(client)
    hidden_by_hand = client.post(
        "/api/design/elements",
        json={
            "type": "rect",
            "x_mm": 70.0,
            "y_mm": 5.0,
            "width_mm": 10.0,
            "height_mm": 10.0,
        },
    ).json()["ids"][0]
    by_hand = next(
        node
        for node in client.server.kernel.elements.elems()
        if getattr(node, "id", None) == hidden_by_hand
    )
    by_hand.hidden = True

    estimate(client)

    flags = {
        node.id: bool(getattr(node, "hidden", False))
        for node in client.server.kernel.elements.elems()
    }
    assert flags[frame] is False
    assert flags[overrun] is False
    assert flags[hidden_by_hand] is True


def path_of(client) -> dict:
    """The cut-path window's answer, waited out. It builds in a thread."""
    for _ in range(80):
        answer = client.get("/api/job/path")
        assert answer.status_code == 200, answer.text
        path = answer.json()
        if path.get("state") in ("ready", "empty", "failed", "too_big"):
            return path
        time.sleep(0.25)
    raise AssertionError("the cut path never finished building")


def test_the_cut_path_window_draws_the_plate_and_not_the_drawing(client):
    """
    "What does the machine do, and when" has to be about the job that is coming.

    The window builds through `CommandRunner.preview_plan`, which had no seam for the
    burn's own mutators, so on the last sheetful it drew the literal `{name#+2}` as nine
    characters of real path — in the order the machine would supposedly walk them — and
    the jig frame on every plate. The same lie the clock had, in the other room.

    Two things are held here, and the second is why this is not a brittle count.
    Nothing the window draws may fall inside the box of the place this plate has no name
    for; and the first plate must draw strictly more than the last one, because it has
    the third name and the frame on it. Measured on this design: 409 cutting steps as the
    window used to build the short plate, 172 as it builds it now.
    """
    frame, overrun = a_series(client)
    box = next(
        element["bounds"]
        for element in client.get("/api/design").json()["elements"]
        if element["id"] == overrun
    )

    assert client.post("/api/series/start", json={"row": 0}).status_code == 200
    first = path_of(client)
    assert first["state"] == "ready", first
    on_the_first_plate = len([step for step in first["steps"] if step["k"] != "travel"])

    burned = client.post("/api/series/burn", json={})
    assert burned.status_code == 200, burned.text
    assert client.post("/api/series/advance").status_code == 200
    last = path_of(client)
    assert last["state"] == "ready", last
    on_the_last_plate = [step for step in last["steps"] if step["k"] != "travel"]

    assert len(on_the_last_plate) < on_the_first_plate, (
        f"the short plate drew {len(on_the_last_plate)} steps and the full one "
        f"{on_the_first_plate}: the frame and the nameless place are still in it"
    )
    x0, y0, x1, y1 = box
    for step in on_the_last_plate:
        inside = (
            x0 - 1 <= step.get("x0", -1e9) <= x1 + 1
            and y0 - 1 <= step.get("y0", -1e9) <= y1 + 1
        )
        assert not inside, f"a step at {step.get('x0')},{step.get('y0')} is in the box of the place with no name"


def test_a_shape_with_no_geometry_does_not_take_the_estimate_down(client):
    """
    The pre-flight showed no time at all, twice per refresh, and said nothing.

    A text whose whole content is a placeholder has no geometry while no list is
    attached — the state this feature makes on every detach — and its bounds are
    (nan, nan, nan, nan). One of those poisons the nearest-neighbour travel sum, the
    answer leaves as `nan` seconds, and FastAPI cannot serialise that: measured
    `ValueError: Out of range float values are not JSON compliant: nan / when
    serializing dict item 'seconds'`, a 500 on the route the pre-flight reads. `exact=1`
    answered 200 all along, which is why it went unseen.
    """
    a_text(client, "{ghost}", 20.0)

    answer = client.get("/api/job/estimate")

    assert answer.status_code == 200, answer.text
    seconds = answer.json()["seconds"]
    assert seconds == seconds, "the estimate came back as nan"
