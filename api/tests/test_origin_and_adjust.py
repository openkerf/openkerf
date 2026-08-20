"""
Het nulpunt (gat J12) en bijstellen tijdens een lopende job (gat J11).

Twee dingen die LightBurn wel heeft en de engine niet — het eerste bestaat
nergens in MeerK40t, het tweede alleen bij één driver. Deze tests pinnen vast
wat wij eromheen bouwden: dat het werk écht verschuift op weg naar de machine,
dat de tekening daar niets van merkt, en dat een machine die iets niet kan er
geen knop voor krijgt.
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
    """Een nulpunt waar de kop niet komt, is geen nulpunt maar een fout."""
    response = client.post("/api/machine/origin", json={"x_mm": 5000, "y_mm": 5})
    assert response.status_code == 409
    assert "outside the bed" in response.json()["detail"]


def test_shifting_moves_the_work_and_puts_it_back(kernel, client):
    """
    De kern van J12: het werk gaat verschoven de machine in, en de tekening
    staat daarna weer precies waar hij stond.

    Als dat laatste niet klopt, verplaatst één druk op starten je ontwerp — en
    de tweede druk nog een keer.
    """
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    voor = [tuple(node.bounds) for node in kernel.elements.elems()]

    with drawing.verschoven({"x_mm": 100, "y_mm": 50}) as verschoof:
        assert verschoof is True
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
    """Gaat het plannen stuk, dan mag het ontwerp niet verschoven blijven staan."""
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    voor = [tuple(node.bounds) for node in kernel.elements.elems()]

    with pytest.raises(RuntimeError):
        with drawing.verschoven({"x_mm": 100, "y_mm": 50}):
            raise RuntimeError("plannen mislukt")

    na = [tuple(node.bounds) for node in kernel.elements.elems()]
    for eerst, laatst in zip(voor, na):
        assert laatst == pytest.approx(eerst)


def test_shift_does_not_touch_the_undo_history(kernel, client):
    """
    Bewust niet via het console-commando `translate`: dat werkt in een eigen
    undoscope, en dan levert elke start twee stappen op die de gebruiker nooit
    heeft gemaakt.
    """
    from openkerf_api.drawing import Drawing

    _rect(client)
    drawing = Drawing(kernel)
    diep = len(kernel.elements.undo._undo_stack)

    with drawing.verschoven({"x_mm": 40, "y_mm": 40}):
        pass

    assert len(kernel.elements.undo._undo_stack) == diep


def test_bounds_report_measures_the_bed_from_the_origin(client):
    """
    Het nulpunt telt voor het bed en niet voor het vel.

    Een vel is een tekening en het bed is de machine (J5): het nulpunt
    verplaatst het werk op de máchine, dus dáár kan het buiten vallen, maar
    binnen de tekening blijft alles staan waar je het neerzette.
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

    assert buiten["outside_bed"] == 1, "verschoven valt de rechthoek van het bed"
    assert buiten["outside_sheet"] == binnen["outside_sheet"], "het vel beweegt niet mee"
    assert buiten["work"] == binnen["work"], "de tekening zelf verschuift niet"
    assert buiten["burns_at"]["x_mm"] == pytest.approx(
        binnen["work"]["x_mm"] + bed["width_mm"] - 20
    )


def test_the_cutcode_that_reaches_the_machine_carries_the_offset(kernel, client):
    """
    Het bewijs dat J12 iets doet: niet de boom maar de **cutcode** telt.

    Dat is wat de spooler de driver in duwt, en het is het enige punt waarop je
    kunt controleren of het nulpunt de machine ook echt bereikt. Zonder deze
    test zou een verschuiving die net ná het bouwen van de cutcode wordt
    teruggedraaid er van buiten precies hetzelfde uitzien — en niets doen.
    """
    from openkerf_api.drawing import Drawing

    operatie = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    vorm = _rect(client, x_mm=10, y_mm=10, width_mm=30, height_mm=20)
    client.post("/api/design/assign", json={"ids": [vorm], "operation_id": operatie})
    drawing = Drawing(kernel)

    def hoeken(oorsprong):
        with drawing.verschoven(oorsprong):
            kernel.console("plan clear copy preprocess validate blob preopt optimize\n")
            code = list(kernel.planner.default_plan.plan)[0]
            punten = [p for cut in code.flat() for p in (cut.start, cut.end)]
            return (
                min(p[0] for p in punten),
                min(p[1] for p in punten),
            )

    x0, y0 = hoeken(None)
    x1, y1 = hoeken({"x_mm": 100, "y_mm": 60})

    # De native eenheid van dit apparaat doet er niet toe; het verschil moet
    # exact de verschuiving zijn, omgerekend in diezelfde eenheid.
    schaal = (x1 - x0) / 100
    assert schaal > 0
    assert (y1 - y0) / 60 == pytest.approx(schaal, rel=1e-6)


# --------------------------------------------------- bijstellen tijdens de job


def test_ruida_cannot_adjust_and_says_so(kernel, client):
    """
    Gat J11. Alleen de grbl-driver heeft realtime overrides; de Ruida zet
    snelheid en vermogen per cut-segment uit de settings. Wat de machine niet
    kan, hoort geen knop te krijgen — en de route moet het weigeren, want de
    UI is een advies en curl trekt zich daar niets van aan.
    """
    caps = client.get("/api/capabilities").json()["adjust"]
    assert caps == {"power": False, "speed": False}

    stand = client.get("/api/job/adjust").json()
    assert stand["power"] is None and stand["speed"] is None

    geweigerd = client.post("/api/job/adjust", json={"power": 0.9})
    assert geweigerd.status_code == 409
    assert "during a job" in geweigerd.json()["detail"]


def test_adjustment_is_offered_when_the_driver_has_it(kernel):
    """Een driver die het wél kan, krijgt de knoppen — en de factor komt aan."""

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
    Gat L8. De engine kent drie coolant-methoden; twee zijn grbl-only en de
    derde ("popup") stuurt niets naar de laser maar roept `kernel.yesno` — en
    dat is buiten de wx-GUI een `input()` op stdin. Headless staat de
    spoolerthread dan te wachten op een toets die niemand indrukt.

    Een schakelaar die de job laat hangen is erger dan geen schakelaar.
    """
    from openkerf_api.drawing import Drawing

    kernel.console("service device start ruida -i\n")
    drawing = Drawing(kernel)
    assert drawing.air_assist_supported() is False

    kernel.device.device_coolant = "popup"
    kernel.root.coolant.claim_coolant(kernel.device, "popup")

    assert kernel.root.coolant.get_device_function(kernel.device) is not None, (
        "de engine claimt hem wel"
    )
    assert drawing.air_assist_supported() is False, (
        "maar hij schakelt niets, dus wij bieden hem niet aan"
    )
