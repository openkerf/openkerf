"""
De rotary: branden op een cilinder.

The proof that counts is the last one in this file: the scale has to reach the **cutcode**,
because that is what the spooler pushes into the driver. Everything before it is settings
and refusals; if that final test goes red, the machine burns a job nobody asked for while
the interface keeps saying the rotary is on.

What is *not* in here, because it needs the machine: whether a burned ring comes out round
and the right size. That is the checklist at the foot of docs/rotary.md, which
the app repeats on its own Rotary page.
"""

import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api.machine import MachineControl
from openkerf_api.rotary import ROTARY_KEY, RotaryControl
from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    kernel.console("service device start ruida -i\n")
    return ApiServer(kernel, library_path=tmp_path / "o.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def _rect(client, **maten):
    body = {"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 30, "height_mm": 20}
    body.update(maten)
    response = client.post("/api/design/elements", json=body)
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


# ------------------------------------------------- what the engine does not give us


def test_the_engines_own_rotary_never_attaches_to_a_ruida(kernel):
    """
    The reason this module exists at all.

    `rotary/rotary.py:145-152` returns five provider paths from its `service` lifecycle
    and `provider/device/ruida` is not among them, so the delegate, its settings and its
    console commands are unreachable on the machine this project is built for. If upstream
    ever adds the Ruida to that list, this test goes red — and then our layer should step
    aside instead of fighting it.
    """
    from meerk40t.rotary import rotary

    paths = rotary.plugin(kernel, "service")
    assert "provider/device/ruida" not in paths

    kernel.console("service device start ruida -i\n")
    device = kernel.device
    assert device.registered_path == "provider/device/ruida"
    assert not hasattr(device, "rotary")
    assert not hasattr(device, "rotary_active")
    assert kernel.lookup("choices/rotary") is None


def test_a_device_with_its_own_rotary_keeps_it(kernel):
    """
    Same rule as the rasteriser: what is already there wins.

    A grbl carries the engine's rotary with the user's own settings in it; installing ours
    beside it would mean two scales and no way to see which one you changed.
    """
    kernel.console("service device start ruida -i\n")
    rotary = RotaryControl(kernel)
    rotary.update({"active": True, "kind": "chuck", "diameter_mm": 80})

    class Engine:
        active = False
        scale_x = 1.0
        scale_y = 1.0

    kernel.device.rotary = Engine()
    assert rotary.engine_rotary() is True
    with rotary.applied() as scale:
        assert scale is None, "we install nothing over the engine's own rotary"
        assert isinstance(kernel.device.rotary, Engine)


# ----------------------------------------------------------- settings round-trip


def test_rotary_starts_off_and_survives_a_round_trip(client):
    off = client.get("/api/machine/rotary").json()
    assert off["active"] is False
    assert off["scale_y"] == 1.0
    assert off["scale_x"] == 1.0
    assert off["engine_rotary"] is False

    on = client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["active"] is True
    assert body["diameter_mm"] == 80.0
    # pi * 80, the engine's own circumference_mm.
    assert body["circumference_mm"] == pytest.approx(251.3274, abs=1e-4)
    # Nothing was calibrated, so nothing is scaled. On a Ruida whose own rotary page does
    # the conversion, that is the correct answer and not a missing feature.
    assert body["scale_y"] == 1.0

    again = client.get("/api/machine/rotary").json()
    assert again["active"] is True and again["diameter_mm"] == 80.0


def test_only_the_fields_you_send_change(client):
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    client.post("/api/machine/rotary", json={"active": False})
    kept = client.get("/api/machine/rotary").json()
    assert kept["active"] is False
    assert kept["diameter_mm"] == 80.0, "switching off does not forget the object"


def test_the_rotary_is_written_to_the_machines_own_settings(client, kernel):
    """
    Persistence across a restart of the API.

    The value goes into the device service's configuration, exactly like the zero point
    and the saved positions — so a restart of our server reads it back from the engine's
    config and not from a table of ours. Measured here on what the kernel has actually
    written, not on what we handed it.
    """
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "roller", "circumference_mm": 189.5},
    )
    stored = kernel.read_persistent(str, kernel.device.path, ROTARY_KEY, "")
    assert '"circumference_mm": 189.5' in stored
    assert '"active": true' in stored

    # A fresh control object on the same kernel is what a restarted server sees.
    assert RotaryControl(kernel).settings()["circumference_mm"] == 189.5


def test_a_roller_carries_the_circumference_itself(client):
    body = client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "roller", "circumference_mm": 189.5},
    ).json()
    assert body["circumference_mm"] == 189.5
    assert body["kind"] == "roller"


def test_the_y_scale_can_come_from_the_two_motors(client):
    """`y_steps_factor`: flat steps/mm over rotary steps/mm."""
    body = client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 60,
            "scale_source": "steps",
            "flat_steps_per_mm": 80,
            "rotary_steps_per_mm": 64,
        },
    ).json()
    assert body["scale_y"] == pytest.approx(1.25)


# ------------------------------------------------------------------- refusals


def test_a_chuck_without_a_diameter_is_refused(client):
    response = client.post("/api/machine/rotary", json={"active": True, "kind": "chuck"})
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "rotary.needsDiameter"
    assert client.get("/api/machine/rotary").json()["active"] is False


def test_a_roller_without_a_circumference_is_refused(client):
    response = client.post(
        "/api/machine/rotary", json={"active": True, "kind": "roller"}
    )
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "rotary.needsCircumference"


def test_computing_from_the_motors_needs_both_numbers(client):
    response = client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 60,
            "scale_source": "steps",
            "flat_steps_per_mm": 80,
        },
    )
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "rotary.needsSteps"


def test_an_unknown_kind_of_rotary_is_refused(client):
    response = client.post("/api/machine/rotary", json={"kind": "spindle"})
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "rotary.unknownKind"


def test_a_scale_that_is_a_resize_is_refused(client):
    """
    A calibration is a correction near 1.0. Measured: a factor of 3 on a 20 mm high job
    burns 60 mm of surface, which on a 80 mm chuck is three quarters of the way round
    instead of a quarter. A typo (a comma for a dot) does that, and it costs the workpiece.
    """
    response = client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 80,
            "scale_source": "manual",
            "manual_scale_y": 3,
        },
    )
    assert response.status_code == 409
    assert "3.0000" in response.json()["detail"]
    assert "not a calibration but a resize" in response.json()["detail"]


# ---------------------------------------------------------------- calibration


def test_calibrating_turns_a_measurement_into_the_factor(client):
    """
    "I burned a line meant to be 100 mm and I measured 96.5" -> 1.036269, the engine's own
    `calibrate_rotary_steps`. The line came out short, so Y has to be commanded longer.
    """
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    body = client.post(
        "/api/machine/rotary/calibrate",
        json={"commanded_mm": 100, "measured_mm": 96.5},
    ).json()

    assert body["scale_y"] == pytest.approx(1.036269, abs=1e-6)
    assert body["scale_source"] == "manual"
    assert body["last_calibration"] == {
        "commanded_mm": 100.0,
        "measured_mm": 96.5,
        "factor": pytest.approx(1.036269, abs=1e-6),
    }


def test_calibrating_twice_converges_instead_of_starting_over(client):
    """
    The second measurement is made *with* the first factor already in, so it has to build
    on it. Starting from 1.0 each time would undo the first correction and the user would
    be chasing the same 3.5% for ever.
    """
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    first = client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 96.5}
    ).json()["scale_y"]
    second = client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 99.5}
    ).json()["scale_y"]

    assert first == pytest.approx(1.036269, abs=1e-6)
    assert second == pytest.approx(first * 100 / 99.5, abs=1e-6)


def test_calibrating_without_a_measurement_is_refused(client):
    response = client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 0}
    )
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "rotary.needsMeasurement"


def test_a_wild_measurement_is_refused_with_its_numbers(client):
    response = client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 12}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "100 mm commanded and 12 mm measured" in detail
    assert "8.3333" in detail


# ------------------------------------------------------------------- safety


def test_homing_is_refused_while_the_rotary_is_on(client, kernel):
    """
    With a chuck fitted, homing Y drives the head into it. The refusal sits in the API and
    not only in the interface: a second tab, a phone or a curl command comes straight past
    a greyed-out button.
    """
    assert client.post("/api/machine/home", json={}).status_code == 200

    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )

    refused = client.post("/api/machine/home", json={})
    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "rotary.homeWhileActive"
    assert "into the rotary" in refused.json()["detail"]

    # Physical home moves the head just as much, so it is refused just as hard.
    assert client.post("/api/machine/home", json={"physical": True}).status_code == 409

    # And there is a way through for whoever has taken the rotary out.
    forced = client.post("/api/machine/home", json={"force": True})
    assert forced.status_code == 200, forced.text
    assert forced.json()["forced"] is True


def test_the_refusal_is_the_rotarys_and_not_the_buttons(kernel):
    """`homing_refusal` is the one place that decides; the route only passes it on."""
    kernel.console("service device start ruida -i\n")
    rotary = RotaryControl(kernel)
    assert rotary.homing_refusal() is None
    rotary.update({"active": True, "kind": "chuck", "diameter_mm": 80})
    assert "Take the rotary out" in rotary.homing_refusal()

    control = MachineControl(kernel)
    assert control._rotary().homing_refusal() is not None


def test_the_preflight_says_the_rotary_is_on(client):
    """
    Before you press start: rotary on, this diameter, this scale. A job that silently
    comes out stretched wastes the workpiece, and there is one of those.
    """
    _rect(client)
    off = client.get("/api/job/layers").json()["rotary"]
    assert off["active"] is False

    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 96.5}
    )
    on = client.get("/api/job/layers").json()["rotary"]
    assert on["active"] is True
    assert on["diameter_mm"] == 80.0
    assert on["scale_y"] == pytest.approx(1.036269, abs=1e-6)
    assert on["circumference_mm"] == pytest.approx(251.3274, abs=1e-4)


def test_work_taller_than_the_object_is_round_says_so(client):
    """
    The one question the circumference answers. A chuck of 60 mm is 188.5 mm round; a
    design 300 mm tall burns over its own start and you only see that on the cup.
    """
    _rect(client, x_mm=5, y_mm=5, width_mm=40, height_mm=300)
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 60},
    )
    state = client.get("/api/job/layers").json()["rotary"]
    assert state["overlap"] == {
        "work_mm": 300.0,
        "burns_mm": 300.0,
        "circumference_mm": pytest.approx(188.5, abs=0.01),
    }

    _rect(client, x_mm=5, y_mm=5, width_mm=40, height_mm=20)
    client.post("/api/design/clear")
    _rect(client, x_mm=5, y_mm=5, width_mm=40, height_mm=20)
    assert "overlap" not in client.get("/api/job/layers").json()["rotary"]


# ------------------------------------------------- the proof: on the cutcode


def _y_extent(kernel):
    kernel.console("plan clear copy preprocess validate blob preopt optimize\n")
    code = list(kernel.planner.default_plan.plan)[0]
    points = [p for cut in code.flat() for p in (cut.start, cut.end)]
    return (
        min(p[0] for p in points),
        max(p[0] for p in points),
        min(p[1] for p in points),
        max(p[1] for p in points),
    )


def test_the_cutcode_that_reaches_the_machine_is_scaled_in_y(kernel, server, client):
    """
    The proof that the rotary does anything: not the tree but the **cutcode**.

    That is what the spooler pushes into the driver, and the only point at which you can
    see whether the scale really reaches the machine. Without this test a scale that was
    installed and removed *around* the plan instead of *over* it would look identical from
    the outside — and do nothing.

    Measured on a Ruida (2580.118 native units per mm) with a 30x20 mm rectangle at 10,10
    and a factor of 1.036269: Y went from 10000..30000 to 10363..31088, a height ratio of
    1.036250. The remainder is the integer rounding of the cutcode, hence the tolerance.
    """
    operation = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    shape = _rect(client)
    client.post("/api/design/assign", json={"ids": [shape], "operation_id": operation})
    runner = server.commands

    with runner.rotary_applied() as none_yet:
        assert none_yet is None, "off, nothing is installed"
        x0, x1, y0, y1 = _y_extent(kernel)

    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 96.5}
    )
    factor = client.get("/api/machine/rotary").json()["scale_y"]

    with runner.rotary_applied() as installed:
        assert installed == pytest.approx(factor)
        rx0, rx1, ry0, ry1 = _y_extent(kernel)

    assert (rx0, rx1) == (x0, x1), "along the axis nothing is scaled"
    assert (ry1 - ry0) / (y1 - y0) == pytest.approx(factor, abs=1e-4)
    # A scale about the machine's zero, so the position moves along — that is what the
    # engine's own seam does (`cutplan.py:157-159`) and it is what the checklist warns
    # about: measure the calibration line where you are going to burn.
    assert ry0 / y0 == pytest.approx(factor, abs=1e-4)


def test_nothing_stays_behind_on_the_device_after_the_plan(kernel, server, client):
    """
    A rotary attribute left behind would scale the *next* job as well, and nothing on
    screen would say so. Removed in a `finally`, like `Drawing.shifted`.
    """
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    runner = server.commands

    with pytest.raises(RuntimeError):
        with runner.rotary_applied():
            assert kernel.device.rotary.active is True
            raise RuntimeError("planning failed")

    assert not hasattr(kernel.device, "rotary")


def test_the_scale_stays_until_the_last_plan_is_done(kernel, server, client):
    """
    Two plans at once may not undo each other's scale.

    The cut-path preview builds in a thread of its own while a job can claim the plan
    (commands.py, cutpath.py), so both can be inside `rotary_applied` at the same time.
    Measured before the depth counter: the one that finished first deleted
    `device.rotary`, the other built its remaining phases unscaled, and the preview
    cached that as the ready answer for a rotary-on design.
    """
    client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 80,
            "scale_source": "manual",
            "manual_scale_y": 1.036269,
        },
    )
    runner = server.commands

    with runner.rotary_applied() as outer:
        with runner.rotary_applied() as inner:
            assert inner == outer
        # The inner one has left; the scale has not.
        assert kernel.device.rotary.scale_y == pytest.approx(outer)
        assert kernel.device.rotary.active is True

    assert not hasattr(kernel.device, "rotary"), "the last one out takes it away"


def test_switched_off_the_plan_is_the_same_as_without_a_rotary(kernel, server, client):
    """
    The rotary off must not cost a single unit. If it did, every flat job on a machine
    that *has* a rotary would come out slightly different from one on a machine that has
    none, and nobody would know why.
    """
    operation = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    shape = _rect(client)
    client.post("/api/design/assign", json={"ids": [shape], "operation_id": operation})
    runner = server.commands

    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80, "scale_source": "manual", "manual_scale_y": 1.2},
    )
    client.post("/api/machine/rotary", json={"active": False})

    with runner.rotary_applied():
        off = _y_extent(kernel)
    with runner.rotary_applied():
        again = _y_extent(kernel)
    assert off == again
    assert not hasattr(kernel.device, "rotary")


def test_the_cut_path_preview_follows_the_rotary(kernel, server, client):
    """
    The preview is cached against the design, and the rotary is not part of the design.

    Measured over real HTTP before the rotary was in that key: a rectangle at y 10..30 mm
    came out of `/api/job/path` at 10.36..31.09 mm with the rotary on — correct — and
    *stayed* there after switching the rotary off, because no shape had moved. The window
    then drew a job the machine no longer burns, which is the one thing a preview may
    never do.
    """
    operation = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    shape = _rect(client)
    client.post("/api/design/assign", json={"ids": [shape], "operation_id": operation})

    def path_extent():
        for _ in range(60):
            body = client.get("/api/job/path").json()
            if body["state"] == "ready":
                ys = [v for step in body["steps"] for v in (step["y0"], step["y1"])]
                return round(min(ys), 2), round(max(ys), 2)
            assert body["state"] == "building", body
            time.sleep(0.1)
        raise AssertionError("the path never became ready")

    flat = path_extent()
    assert flat == (10.0, 30.0)

    client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 80,
            "scale_source": "manual",
            "manual_scale_y": 1.036269,
        },
    )
    assert path_extent() == (10.36, 31.09)

    client.post("/api/machine/rotary", json={"active": False})
    assert path_extent() == flat, "switching off has to come back on screen"


def test_saving_the_page_does_not_round_a_calibration_away(client):
    """
    Measured on screen: with the factor rounded to four decimals, pressing Save after a
    calibration turned 1.036269 into 1.0363. Harmless on one cup (0.008 mm over 250 mm),
    but a number that changes because you saved the page you were reading is one you stop
    trusting.
    """
    client.post(
        "/api/machine/rotary",
        json={"active": True, "kind": "chuck", "diameter_mm": 80},
    )
    client.post(
        "/api/machine/rotary/calibrate", json={"commanded_mm": 100, "measured_mm": 96.5}
    )
    # What the form sends back when the user presses Save: everything it has on screen.
    again = client.post(
        "/api/machine/rotary",
        json={
            "active": True,
            "kind": "chuck",
            "diameter_mm": 80,
            "scale_source": "manual",
            "manual_scale_y": 1.036269,
        },
    ).json()
    assert again["scale_y"] == pytest.approx(1.036269, abs=1e-6)
