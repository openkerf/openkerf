"""
The cut path before burning (gap S1 / L1).

What is pinned here is the part that needs no machine: that the path comes out in
the order the plan holds, that every step carries the layer, the clock and the
geometry the window draws, that the answer is cached against the design and thrown
away as soon as anything moves it, that a heavy design is refused before it is
built rather than after, and — the one that matters on a Tuesday afternoon — that
starting a job never queues behind a preview.

What is *not* here is the machine. There is no laser on this computer, so nothing
below the line "the machine walks it" is proved. That check is a checklist for the
KH-5030, and it lives in **PREVIEW-CHECKLIST.md** at the root of the repository —
beside PREVIEW-CHECKLIST.md, because that is where somebody standing next to the
laser will look, and not in a test file. It also names, per line, which test here
pins the part that needs no machine.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api.commands import PlanYielded
from openkerf_api.cutpath import PLANNED_SEGMENT_LIMIT, CutPath
from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "path.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def a_layer(client, kind="cut", **fields):
    layer = client.post("/api/design/operations", json={"type": kind}).json()["id"]
    if fields:
        client.patch(f"/api/design/operations/{layer}", json=fields)
    return layer


def wipe_layers(client):
    """
    Empty the layer list before making our own.

    Not tidiness: the engine starts with the layer list of whatever session last
    shut down (CLAUDE.md, `operations.cfg`), and it classifies every fresh shape
    into it. Without this a rectangle lands in two layers and the path holds twice
    the steps — measured 32 where 8 belong, with an "E1" engrave layer nobody in
    this test ever made. And *after* drawing, because drawing is what conjures the
    layer up.
    """
    for operation in client.get("/api/design").json()["operations"]:
        client.delete(f"/api/design/operations/{operation['id']}")


def a_rect(client, x=10.0, y=10.0, w=20.0, h=20.0):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": y, "width_mm": w, "height_mm": h},
    ).json()["ids"][0]


def wait_for_path(client, timeout=30.0):
    """Poll the route as the window does; return the ready answer."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer = client.get("/api/job/path").json()
        if answer["state"] != "building":
            return answer
        time.sleep(0.02)
    raise AssertionError("the path never finished building")


def a_design(client, shapes=3, kind="cut", **layer_fields):
    ids = [a_rect(client, x=10 + i * 30) for i in range(shapes)]
    wipe_layers(client)
    layer = a_layer(client, kind, **layer_fields)
    client.post("/api/design/assign", json={"ids": ids, "operation_id": layer})
    return layer, ids


# ------------------------------------------------------------------ the answer


def test_an_empty_bed_has_no_path_and_says_so(client):
    """Not "0 steps": nothing to plan is a different answer from a plan of nothing."""
    assert client.get("/api/job/path").json()["state"] == "empty"


def test_the_path_carries_the_steps_the_window_draws(client):
    layer, _ = a_design(client, shapes=2)

    answer = wait_for_path(client)

    assert answer["state"] == "ready"
    # Two rectangles, four sides each: eight cut steps in the order the machine walks.
    assert answer["steps_total"] == 8
    steps = answer["steps"]
    assert [s["k"] for s in steps] == ["cut"] * 8
    assert {s["op"] for s in steps} == {layer}
    for step in steps:
        for field in ("x0", "y0", "x1", "y1", "t0", "t1", "t2"):
            assert field in step, field
    # Every step ends where the next one starts, or the head travelled: both are
    # information, and the window draws the difference.
    assert steps[0]["t0"] == 0
    assert answer["seconds"] == pytest.approx(steps[-1]["t2"], abs=0.05)
    assert answer["cut_mm"] > 0
    assert answer["layers"][0]["id"] == layer
    assert answer["layers"][0]["speed_mm_s"]


def test_the_clock_only_moves_forward(client):
    a_design(client, shapes=4)

    steps = wait_for_path(client)["steps"]

    for earlier, later in zip(steps, steps[1:]):
        assert earlier["t2"] <= later["t0"] + 1e-9
        assert earlier["t0"] <= earlier["t1"] <= earlier["t2"]


def test_a_travel_move_is_the_gap_between_two_steps(client):
    """
    Travel is not a step of its own; it is the hole between them.

    Two rectangles 30 mm apart: within a rectangle the head does not travel (t0 ==
    t1), and between them it does. That is the whole model the window draws its
    dashed lines from, so it is worth pinning.
    """
    a_design(client, shapes=2)

    steps = wait_for_path(client)["steps"]

    inside = [s for s in steps if abs(s["t1"] - s["t0"]) < 1e-9]
    travelled = [s for s in steps if s["t1"] - s["t0"] > 1e-9]
    assert len(travelled) == 1
    assert len(inside) == 7
    # And the jump really is a jump: it starts where the previous step ended.
    index = steps.index(travelled[0])
    assert (steps[index - 1]["x1"], steps[index - 1]["y1"]) != (
        travelled[0]["x0"],
        travelled[0]["y0"],
    )


def test_the_start_of_every_shape_is_marked(client):
    """The order is only visible if you can see where a contour begins."""
    a_design(client, shapes=3)

    steps = wait_for_path(client)["steps"]

    assert sum(1 for s in steps if s.get("f")) == 3


def test_the_order_is_the_order_the_plan_holds(server):
    """
    The path may not put the steps in an order of its own.

    Measured against the plan itself: the same pipeline, the same walk order
    (`CutCode.flat()`), the same start points. If the harvest ever sorted or
    grouped, this is where it shows.
    """
    from meerk40t.core.cutcode.cutcode import CutCode

    with TestClient(server.build_app()) as client:
        a_design(client, shapes=4)
        answer = wait_for_path(client)

        server.commands.run("plan clear copy preprocess validate blob preopt optimize")
        merged = CutCode()
        for chunk in server.kernel.planner.default_plan.plan:
            if isinstance(chunk, CutCode):
                merged.extend(chunk)
        from meerk40t.core.units import UNITS_PER_MM

        plan_order = [
            (round(item.start[0] / UNITS_PER_MM, 2), round(item.start[1] / UNITS_PER_MM, 2))
            for item in CutCode(merged.flat()).flat()
        ]
        server.commands.run("plan clear")

    assert [(s["x0"], s["y0"]) for s in answer["steps"]] == plan_order


def test_a_curve_keeps_its_control_points(client):
    """A circle drawn as four chords is a lie you can see."""
    circle = client.post(
        "/api/design/elements", json={"type": "circle", "cx_mm": 50, "cy_mm": 50, "r_mm": 10}
    ).json()["ids"][0]
    wipe_layers(client)
    layer = a_layer(client, "cut")
    client.post("/api/design/assign", json={"ids": [circle], "operation_id": layer})

    steps = wait_for_path(client)["steps"]

    assert steps, "a circle should produce steps"
    assert all("c" in step for step in steps), "a circle is cubics, not lines"
    assert all(len(step["c"]) == 4 for step in steps)


def test_the_layer_name_is_the_one_the_layer_list_shows(client):
    layer, _ = a_design(client, shapes=1, kind="engrave")
    client.patch(f"/api/design/operations/{layer}", json={"label": "Inlay outline"})

    answer = wait_for_path(client)

    assert [l["label"] for l in answer["layers"]] == ["Inlay outline"]


def test_a_second_pass_is_in_the_path_twice(client):
    """
    The plan is not the design: two passes means walking it twice.

    This is the route our own workaround takes (`_with_passes` plus
    `_share_pass_settings`), so it is also the check that the preview shows what
    the machine does and not what the tree says.
    """
    layer, _ = a_design(client, shapes=1, passes=1)
    one = wait_for_path(client)["steps_total"]

    client.patch(f"/api/design/operations/{layer}", json={"passes": 3})
    three = wait_for_path(client)

    assert one == 4
    assert three["steps_total"] == 12
    assert three["seconds"] > 2.9 * 0.9  # three times the work, give or take travel


def _lihuiyu_kernel():
    """
    A kernel with a K40 device, because the dummy hides the mistake.

    The dummy's view matrix is the identity, so on it the plan comes out in scene
    units and everything looks right. A lihuiyu counts in 1,000 steps to the inch:
    a rectangle drawn at 15 mm comes out of the plan at 587 native units, and if
    nobody undoes that matrix it reaches the window as 0.23 mm. Measured on the live
    server before the fix — a plausible-looking little drawing 65 times too small.
    """
    from meerk40t.kernel import Kernel

    kernel = Kernel("MeerK40t", "0.0.0-testing", "OpenKerf_UNITS", ansi=False, ignore_settings=True)
    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import coolant
    from meerk40t.fill import fills
    from meerk40t.image import imagetools
    from meerk40t.lihuiyu import plugin as lihuiyu
    from meerk40t.network import kernelserver

    for module in (kernelserver, basedevice, dummydevice, core, imagetools, fills,
                   coolant, svg_io, lihuiyu):
        kernel.add_plugin(module.plugin)
    kernel(partial=True)
    kernel.console("service device start lhystudios -i\n")
    return kernel


def test_the_path_is_in_millimetres_whatever_the_machine_counts_in(tmp_path):
    """
    The one mistake that would look like a picture of your work.

    `plan preprocess` converts the scene into *device* coordinates, so what comes
    out of the plan is in the machine's own units. The path has to undo that — the
    same inverse the engine's own simulation uses — or the drawing is a scale model
    and the distances are nonsense.
    """
    kernel = _lihuiyu_kernel()
    try:
        server = ApiServer(kernel, library_path=tmp_path / "u.db")
        with TestClient(server.build_app()) as client:
            ids = [a_rect(client, x=15, y=15, w=120, h=80)]
            wipe_layers(client)
            layer = a_layer(client, "cut", speed=12)
            client.post("/api/design/assign", json={"ids": ids, "operation_id": layer})

            answer = wait_for_path(client)

        assert answer["state"] == "ready"
        xs = [s["x0"] for s in answer["steps"]] + [s["x1"] for s in answer["steps"]]
        ys = [s["y0"] for s in answer["steps"]] + [s["y1"] for s in answer["steps"]]
        assert min(xs) == pytest.approx(15, abs=0.1)
        assert max(xs) == pytest.approx(135, abs=0.1)
        assert min(ys) == pytest.approx(15, abs=0.1)
        assert max(ys) == pytest.approx(95, abs=0.1)
        # And the distances with it: the perimeter is 400 mm, not 6 mm.
        assert answer["cut_mm"] == pytest.approx(400, rel=0.02)
    finally:
        kernel()


# ------------------------------------------------------------------ the cache


def test_the_answer_is_kept_against_the_design(client, server):
    a_design(client, shapes=3)
    first = wait_for_path(client)

    before = server.commands.plan_claims
    again = client.get("/api/job/path").json()

    assert again["state"] == "ready"
    assert again["fingerprint"] == first["fingerprint"]
    assert again is not None and again["built_in_s"] == first["built_in_s"]
    # And nothing was rebuilt: no plan was touched for the second answer.
    assert server.commands.plan_claims == before


def test_moving_a_shape_invalidates_the_answer(client):
    _, ids = a_design(client, shapes=2)
    first = wait_for_path(client)

    client.post("/api/design/move", json={"ids": [ids[0]], "dx_mm": 25, "dy_mm": 40})
    second = wait_for_path(client)

    assert second["fingerprint"] != first["fingerprint"]
    assert second["state"] == "ready"


def test_a_faster_layer_invalidates_the_answer(client):
    """The path is the same lines; the clock along it is not."""
    layer, _ = a_design(client, shapes=2, speed=10)
    slow = wait_for_path(client)

    client.patch(f"/api/design/operations/{layer}", json={"speed": 40})
    fast = wait_for_path(client)

    assert fast["fingerprint"] != slow["fingerprint"]
    assert fast["seconds"] < slow["seconds"]


def test_switching_inner_first_off_invalidates_the_answer(client, server):
    """An optimisation setting changes the order without touching a single shape."""
    a_design(client, shapes=2)
    first = wait_for_path(client)["fingerprint"]

    root = server.kernel.root
    root.setting(bool, "opt_inner_first", True)
    root.opt_inner_first = not root.opt_inner_first

    assert client.get("/api/job/path").json()["fingerprint"] != first


def test_a_layer_that_does_not_burn_is_not_in_the_path(client):
    """
    "Burn along" off is the one switch that empties the machine's day.

    The path has to say so and not draw the lines anyway: a preview showing work
    that will not happen is worse than no preview, because you go and stand beside
    the machine waiting for it.
    """
    layer, _ = a_design(client, shapes=2)
    assert wait_for_path(client)["steps_total"] == 8

    client.patch(f"/api/design/operations/{layer}", json={"output": False})

    assert client.get("/api/job/path").json()["state"] == "empty"


# ------------------------------------------------------------------ the limits


def test_a_design_too_heavy_to_plan_is_refused_before_it_is_built(kernel, tmp_path):
    """
    The refusal comes from the geometry, not from the plan.

    That is the point: the plan is what costs the time (measured 2.5 s at 960
    shapes and quadratic above it), so a ceiling checked afterwards has already
    paid the bill. The numbers ride along, because "too big" without a size is not
    an answer.
    """
    server = ApiServer(kernel, library_path=tmp_path / "big.db")
    with TestClient(server.build_app()) as client:
        # Four segments each, so this is over the ceiling on segments alone.
        ids = [a_rect(client, x=5 + (i % 30) * 9, y=5 + (i // 30) * 9, w=6, h=6)
               for i in range(600)]
        wipe_layers(client)
        layer = a_layer(client, "cut", passes=6)
        client.post("/api/design/assign", json={"ids": ids, "operation_id": layer})

        before = server.commands.plan_claims
        answer = client.get("/api/job/path").json()

        assert answer["state"] == "too_big"
        assert answer["planned_segments"] > PLANNED_SEGMENT_LIMIT
        assert answer["limit"] == PLANNED_SEGMENT_LIMIT
        # Nothing was planned: that is the whole difference from finding out later.
        assert server.commands.plan_claims == before


def test_the_weight_counts_the_passes(kernel, tmp_path):
    """Six passes over a hundred shapes is six hundred shapes of work."""
    server = ApiServer(kernel, library_path=tmp_path / "w.db")
    with TestClient(server.build_app()) as client:
        layer, _ = a_design(client, shapes=4)
        _, one = server.cutpath.signature(None)
        client.patch(f"/api/design/operations/{layer}", json={"passes": 5})
        _, five = server.cutpath.signature(None)

    assert one == 16
    assert five == 80


# --------------------------------------------------- burning always comes first


def test_a_job_never_waits_for_a_whole_preview_build(server):
    """
    The reason `preview_plan` is cut into phases.

    A build claims the kernel-global plan; so does a job. Whoever is burning wins:
    the build gives the plan up at the next phase boundary and says so with
    `PlanYielded`. Driven deterministically — the claim is made from another thread
    *during* a phase, and this thread waits until the counter has moved — because a
    race left to chance is a test that passes for the wrong reason.
    """
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=2)
        runner = server.commands
        original = runner.run
        claimer_done = threading.Event()

        def claim():
            with runner.claim_plan():
                pass
            claimer_done.set()

        def run(command):
            output = original(command)
            if command == "plan validate":
                # A job wants the plan, right now. It bumps the counter and then
                # waits for the lock we are holding, so the next phase sees it.
                before = runner.plan_claims
                threading.Thread(target=claim, daemon=True).start()
                deadline = time.monotonic() + 5
                while runner.plan_claims == before and time.monotonic() < deadline:
                    time.sleep(0.005)
            return output

        runner.run = run
        try:
            with pytest.raises(PlanYielded):
                runner.preview_plan(lambda plan: pytest.fail("harvest ran anyway"))
        finally:
            runner.run = original
        assert claimer_done.wait(5)


def test_starting_a_job_is_not_blocked_while_a_preview_is_cached(server):
    """The cached answer must not hold on to anything the job needs."""
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=2)
        wait_for_path(client)

        started = time.monotonic()
        response = client.post("/api/job/start")
        took = time.monotonic() - started

        assert response.status_code == 200
        assert took < 5.0, f"starting took {took:.2f}s"


def test_a_preview_that_gave_way_recovers_by_itself(server, monkeypatch):
    """
    "Busy" is a moment, not a verdict.

    Without this the window would sit on "the machine has the plan" for as long as
    the design stayed the same, because the fingerprint — rightly — did not change.
    """
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=2)
        path = server.cutpath
        key, _ = path.signature(None)
        path._blocked = (key, time.monotonic())

        assert client.get("/api/job/path").json()["state"] == "busy"

        monkeypatch.setattr("openkerf_api.cutpath.BLOCKED_SECONDS", 0.0)
        assert wait_for_path(client)["state"] == "ready"


def test_a_broken_build_is_reported_once_and_not_retried_forever(server, monkeypatch):
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=1)

        def explode(plan):
            raise RuntimeError("the engine said no")

        monkeypatch.setattr(server.cutpath, "harvest", explode)
        answer = wait_for_path(client)

        assert answer["state"] == "failed"
        assert "the engine said no" in answer["message"]
        # And it stays said: a second poll does not start a second doomed build.
        assert client.get("/api/job/path").json()["state"] == "failed"


def test_the_zero_point_moves_the_path_with_the_work(server):
    """
    Gap J12: what you draw at 0,0 burns at the zero point.

    A preview that ignores it draws the path 40 mm away from where the head goes,
    and that is the one mistake this window exists to catch.
    """
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=1)
        home = wait_for_path(client)

        client.post("/api/machine/origin", json={"x_mm": 40, "y_mm": 25})
        moved = wait_for_path(client)

    assert min(s["x0"] for s in moved["steps"]) == pytest.approx(
        min(s["x0"] for s in home["steps"]) + 40, abs=0.05
    )
    assert min(s["y0"] for s in moved["steps"]) == pytest.approx(
        min(s["y0"] for s in home["steps"]) + 25, abs=0.05
    )


def test_the_previewed_path_is_the_job_the_spooler_gets(server):
    """
    The one comparison that matters: the picture against what the machine is handed.

    Every other test here checks the harvest against a plan built along the same
    route. This one starts a real job and reads the cutcode out of the spooler's
    `LaserJob` — the object the driver walks — and asks whether it is step for step
    what the window drew. If a phase, a mutator or an optimisation setting ever
    differs between the two routes, this is where it shows, and nowhere else.
    """
    from meerk40t.core.cutcode.cutcode import CutCode
    from meerk40t.core.units import UNITS_PER_MM

    with TestClient(server.build_app()) as client:
        a_design(client, shapes=3)
        answer = wait_for_path(client)

        assert client.post("/api/job/start").status_code == 200
        job = server.kernel.device.spooler.queue[0]
        merged = CutCode()
        for chunk in job.items:
            if isinstance(chunk, CutCode):
                merged.extend(chunk)
        spooled = [
            (
                round(item.start[0] / UNITS_PER_MM, 2),
                round(item.start[1] / UNITS_PER_MM, 2),
                round(item.end[0] / UNITS_PER_MM, 2),
                round(item.end[1] / UNITS_PER_MM, 2),
            )
            for item in CutCode(merged.flat()).flat()
        ]
        client.post("/api/spooler/clear")

    assert spooled == [
        (s["x0"], s["y0"], s["x1"], s["y1"]) for s in answer["steps"]
    ]


def test_a_rotary_that_changes_nothing_keeps_the_answer(server):
    """
    Switching the rotary off has to give the key it had before it was ever on.

    Measured before this fix on a Ruida: off, on and off again gave three different
    keys — 476d59ce…, 18a09653…, 1e5138d1… — because the key carried the *stored*
    factor rather than the one that would be installed. The third key cost a rebuild
    (2.25 s at the ceiling) for an answer that could not differ by one coordinate.
    """
    with TestClient(server.build_app()) as client:
        a_design(client, shapes=1)
        before, _ = server.cutpath.signature(None)

        client.post(
            "/api/machine/rotary",
            json={
                "active": True,
                "kind": "chuck",
                "diameter_mm": 80,
                "scale_source": "manual",
                "manual_scale_y": 1.05,
            },
        )
        during, _ = server.cutpath.signature(None)

        # Only the switch. The factor stays stored, which is exactly the state that
        # used to produce a third key.
        client.post("/api/machine/rotary", json={"active": False})
        after, _ = server.cutpath.signature(None)

    assert during != before, "a rotary that scales Y has to move the path"
    assert after == before
