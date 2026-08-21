"""
Het nulpunt (gat J12) en bijstellen tijdens een lopende job (gat J11).

Two things LightBurn has and the engine does not — the first exists nowhere in MeerK40t, the
second only on one driver. These tests pin down what we built around them: that the work
really shifts on its way to the machine, that the drawing notices nothing of it, and that a
machine that cannot do something gets no button for it.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.machine import MachineControl
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    kernel.console("service device start ruida -i\n")
    with TestClient(ApiServer(kernel, library_path=tmp_path / "o.db").build_app()) as c:
        yield c


def _rect(client, **maten):
    body = {"type": "rect", "x_mm": 10, "y_mm": 20, "width_mm": 30, "height_mm": 40}
    body.update(maten)
    response = client.post("/api/design/elements", json=body)
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


# ------------------------------------------------------------------ nulpunt


def test_origin_starts_empty_and_survives_a_round_trip(client):
    assert client.get("/api/machine/origin").json()["origin"] is None

    gezet = client.post("/api/machine/origin", json={"x_mm": 120, "y_mm": 85})
    assert gezet.status_code == 200, gezet.text
    assert gezet.json() == {"x_mm": 120.0, "y_mm": 85.0}

    assert client.get("/api/machine/origin").json()["origin"] == {
        "x_mm": 120.0,
        "y_mm": 85.0,
    }

    client.delete("/api/machine/origin")
    assert client.get("/api/machine/origin").json()["origin"] is None


def test_origin_outside_the_bed_is_refused(client):
    """A zero point the head does not reach is not a zero point but a mistake."""
    response = client.post("/api/machine/origin", json={"x_mm": 5000, "y_mm": 5})
    assert response.status_code == 409
    assert "outside the bed" in response.json()["detail"]


def test_shifting_moves_the_work_and_puts_it_back(kernel, client):
    """
    The core of J12: the work goes into the machine shifted, and afterwards the drawing is
    back exactly where it was.

    If that last part does not hold, one press of start moves your design — and the second
    press moves it again.
    """
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    voor = [tuple(node.bounds) for node in kernel.elements.elems()]

    with drawing.shifted({"x_mm": 100, "y_mm": 50}) as shift:
        assert shift is True
        tijdens = [tuple(node.bounds) for node in kernel.elements.elems()]

    na = [tuple(node.bounds) for node in kernel.elements.elems()]

    units = drawing._units_per_mm()
    for (a, b, c, d), (e, f, g, h) in zip(voor, tijdens):
        assert e == pytest.approx(a + 100 * units)
        assert f == pytest.approx(b + 50 * units)
        assert g == pytest.approx(c + 100 * units)
        assert h == pytest.approx(d + 50 * units)
    for eerst, laatst in zip(voor, na):
        assert laatst == pytest.approx(eerst)


def test_shift_is_undone_even_when_the_body_raises(kernel, client):
    """If the planning breaks, the design must not be left shifted."""
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    voor = [tuple(node.bounds) for node in kernel.elements.elems()]

    with pytest.raises(RuntimeError):
        with drawing.shifted({"x_mm": 100, "y_mm": 50}):
            raise RuntimeError("plannen mislukt")

    na = [tuple(node.bounds) for node in kernel.elements.elems()]
    for eerst, laatst in zip(voor, na):
        assert laatst == pytest.approx(eerst)


def test_shift_does_not_touch_the_undo_history(kernel, client):
    """
    Deliberately not through the console command `translate`: that works in an undo scope of
    its own, and then every start produces two steps the user never made.
    """
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    diep = len(kernel.elements.undo._undo_stack)

    with drawing.shifted({"x_mm": 40, "y_mm": 40}):
        pass

    assert len(kernel.elements.undo._undo_stack) == diep


def test_bounds_report_measures_the_bed_from_the_origin(client):
    """
    The zero point counts for the bed and not for the sheet.

    A sheet is a drawing and the bed is the machine (J5): the zero point moves the work on the
    *machine*, so it can fall outside *there*, but within the drawing everything stays where
    you put it.
    """
    _rect(client, x_mm=10, y_mm=10, width_mm=60, height_mm=40)

    binnen = client.get("/api/job/layers").json()["bounds"]
    assert binnen["outside_bed"] == 0
    assert binnen["origin"] is None
    assert binnen["burns_at"] == binnen["work"]

    bed = binnen["bed"]
    client.post(
        "/api/machine/origin",
        json={"x_mm": bed["width_mm"] - 20, "y_mm": 10},
    )
    buiten = client.get("/api/job/layers").json()["bounds"]

    assert buiten["outside_bed"] == 1, "shifted, the rectangle falls off the bed"
    assert buiten["outside_sheet"] == binnen["outside_sheet"], "the sheet does not move along"
    assert buiten["work"] == binnen["work"], "the drawing itself does not shift"
    assert buiten["burns_at"]["x_mm"] == pytest.approx(
        binnen["work"]["x_mm"] + bed["width_mm"] - 20
    )


def test_the_cutcode_that_reaches_the_machine_carries_the_offset(kernel, client):
    """
    The proof that J12 does something: it is not the tree but the **cutcode** that
    counts.

    That is what the spooler pushes into the driver, and it is the only point at
    which you can check whether the origin really reaches the machine. Without this
    test a shift that is undone just *after* the cutcode is built would look exactly
    the same from the outside — and do nothing.
    """
    from openkerf_api.drawing import Drawing

    operation = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    shape = _rect(client, x_mm=10, y_mm=10, width_mm=30, height_mm=20)
    client.post("/api/design/assign", json={"ids": [shape], "operation_id": operation})
    drawing = Drawing(kernel)

    def corners(origin):
        with drawing.shifted(origin):
            kernel.console("plan clear copy preprocess validate blob preopt optimize\n")
            code = list(kernel.planner.default_plan.plan)[0]
            points = [p for cut in code.flat() for p in (cut.start, cut.end)]
            return (
                min(p[0] for p in points),
                min(p[1] for p in points),
            )

    x0, y0 = corners(None)
    x1, y1 = corners({"x_mm": 100, "y_mm": 60})

    # The native unit of this device does not matter; the difference has to be
    # exactly the shift, converted into that same unit.
    scale = (x1 - x0) / 100
    assert scale > 0
    assert (y1 - y0) / 60 == pytest.approx(scale, rel=1e-6)


# ------------------------------------------------- adjusting during the job


def test_ruida_cannot_adjust_and_says_so(kernel, client):
    """
    Gap J11. Only the grbl driver has realtime overrides; the Ruida sets speed and
    power per cut segment out of the settings. What the machine cannot do should
    not get a button — and the route has to refuse it, because the UI is advice and
    curl takes no notice of it.
    """
    caps = client.get("/api/capabilities").json()["adjust"]
    assert caps == {"power": False, "speed": False}

    stand = client.get("/api/job/adjust").json()
    assert stand["power"] is None and stand["speed"] is None

    geweigerd = client.post("/api/job/adjust", json={"power": 0.9})
    assert geweigerd.status_code == 409
    assert "during a job" in geweigerd.json()["detail"]


def test_adjustment_is_offered_when_the_driver_has_it(kernel):
    """A driver that *can* do it gets the buttons — and the factor arrives."""

    class Driver:
        power_scale = 1.0
        speed_scale = 1.0

        @staticmethod
        def has_adjustable_power():
            return True

        @staticmethod
        def has_adjustable_speed():
            return True

        def set_power_scale(self, factor):
            self.power_scale = factor

        def set_speed_scale(self, factor):
            self.speed_scale = factor

    kernel.console("service device start ruida -i\n")
    motion = MachineControl(kernel)
    kernel.device.driver = Driver()

    assert motion.adjust_capabilities() == {"power": True, "speed": True}

    uitslag = motion.adjust(power=0.9, speed=1.1)
    assert uitslag["applied"] == {"power": 0.9, "speed": 1.1}
    assert uitslag["power"] == pytest.approx(0.9)
    assert uitslag["speed"] == pytest.approx(1.1)

    with pytest.raises(DesignError, match="outside what the machine accepts"):
        motion.adjust(power=3.0)
    with pytest.raises(DesignError, match="speed or power"):
        motion.adjust()


# ---------------------------------------------------------------- air assist


def test_the_popup_coolant_method_does_not_count_as_air_assist(kernel):
    """
    Gap L8. The engine knows three coolant methods; two are grbl-only and the
    third ("popup") sends nothing to the laser but calls `kernel.yesno` — and
    outside the wx GUI that is an `input()` on stdin. Headless, the spooler thread
    then stands waiting for a key nobody presses.

    A switch that leaves the job hanging is worse than no switch.
    """
    from openkerf_api.drawing import Drawing

    kernel.console("service device start ruida -i\n")
    drawing = Drawing(kernel)
    assert drawing.air_assist_supported() is False

    kernel.device.device_coolant = "popup"
    kernel.root.coolant.claim_coolant(kernel.device, "popup")

    assert kernel.root.coolant.get_device_function(kernel.device) is not None, (
        "the engine does claim it"
    )
    assert drawing.air_assist_supported() is False, (
        "but it switches nothing, so we do not offer it"
    )
