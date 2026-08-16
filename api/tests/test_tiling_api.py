"""
De tegelroutes, en de dekkingstest die het hele ontwerp waarmaakt.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "v.db").build_app()) as c:
        yield c


def wide_plate(client):
    """
    Een plaat die op het dummy-bed precies drie tegels wordt.

    Het dummy-apparaat meet 320 × 220 mm, dus het bruikbare venster is 300 mm
    breed en 800 mm plaat geeft drie tegels. Bij 900 worden het er vier.
    """
    vel = client.get("/api/sheets").json()["sheets"][0]
    client.patch(
        f"/api/sheets/{vel['id']}", json={"width_mm": 800.0, "height_mm": 150.0}
    )
    client.patch(f"/api/sheets/{vel['id']}", json={"tiling": {"enabled": True}})
    for x in (10, 300, 600):
        client.post(
            "/api/design/elements",
            json={
                "type": "rect",
                "x_mm": x,
                "y_mm": 40,
                "width_mm": 40,
                "height_mm": 40,
            },
        )
    _enable_output(client)
    return vel


def _enable_output(client) -> None:
    """
    De laag waar een verse rechthoek in valt, staat standaard uit ("meebranden"
    uit) — de fabrieksinstelling van een graveerlaag. Zonder dit zet
    `TileRun.burn` niets op de spooler en meldt hij "niets klaar om te
    branden", terwijl de geometrie er wel degelijk ligt.
    """
    for operation in client.get("/api/design").json()["operations"]:
        if not operation["output"] and operation["element_ids"]:
            client.patch(
                f"/api/design/operations/{operation['id']}", json={"output": True}
            )


def test_the_layout_is_readable_without_starting_anything(client):
    """Kijken wat het gaat worden hoort geen reeks te beginnen."""
    wide_plate(client)

    antwoord = client.get("/api/tiling")

    assert antwoord.status_code == 200
    assert len(antwoord.json()["tiles"]) == 3
    assert client.get("/api/status").json()["tiling"] is None


def test_burning_before_aligning_is_refused_in_a_sentence(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    antwoord = client.post("/api/tiling/burn")

    assert antwoord.status_code == 409
    # Zie de gelijknamige test in test_tilerun.py: "uitlijn" staat niet in
    # "uitgelijnd" — er zit "ge" tussen.
    assert "uitgelijnd" in antwoord.json()["detail"].lower()


def test_the_series_shows_up_in_the_status_payload(client):
    """
    Bovenbalk, canvas en telefoon lezen alle drie dezelfde stand; een eigen
    verzoek per scherm zou ze uit elkaar laten lopen.
    """
    wide_plate(client)
    client.post("/api/tiling/start")

    stand = client.get("/api/status").json()["tiling"]

    assert stand["current"] == 0
    assert stand["tiles"] == 3
    assert stand["aligned"] is False


def test_cancelling_leaves_no_series_behind(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    client.post("/api/tiling/cancel")

    assert client.get("/api/status").json()["tiling"] is None


def test_here_takes_the_position_the_machine_reports(client):
    """
    "Hier" is de knop waar élke uitlijning in het echt doorheen gaat: je jogt de
    kop naar het merk en drukt erop. Tot nu toe raakte geen enkele test dat pad —
    alle tests gaven hun punten als getallen mee, wat niemand ooit doet.
    """
    wide_plate(client)
    client.post("/api/tiling/start")

    antwoord = client.post(
        "/api/tiling/align",
        json={"reference": "plate_corner", "use_current": True},
    )

    assert antwoord.status_code == 200, antwoord.json()
    assert antwoord.json()["aligned"] is True


def test_three_tiles_together_burn_the_whole_design_exactly_once(client, kernel):
    """
    De kroon op dit ontwerp: de tegels samen branden precies het ontwerp.

    Niets dubbel (dan zou de laser twee keer over dezelfde lijn gaan, zichtbaar
    en op dun materiaal dodelijk), niets vergeten (dan valt er een stuk uit het
    werkstuk). Gemeten als totale geometrielengte, want dat is het enige getal
    dat beide fouten tegelijk vangt.
    """
    wide_plate(client)
    # Een vorm die pal over een naad heen ligt, want dat is het lastige geval.
    # De naden liggen rond 275 en 525 mm; deze rechthoek bedekt de hele
    # overlapzone van de tweede naad, dus hij kán niet ontweken worden en moet
    # dus echt doormidden.
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 480, "y_mm": 40, "width_mm": 90, "height_mm": 60},
    )

    origineel = _design_length_mm(kernel)

    client.post("/api/tiling/start")
    gebrand = 0.0
    for tegel in range(3):
        client.post(
            "/api/tiling/align",
            json=(
                {"reference": "plate_corner", "points": [{"x_mm": 0.0, "y_mm": 0.0}]}
                if tegel == 0
                else {"reference": "markers", "points": _marks_at(client, tegel - 1)}
            ),
        )
        antwoord = client.post("/api/tiling/burn")
        assert antwoord.status_code == 200, antwoord.json()
        gebrand += antwoord.json()["burned_length_mm"]
        client.post("/api/tiling/advance")

    assert gebrand == pytest.approx(origineel, rel=0.001)


def _design_length_mm(kernel) -> float:
    """De totale lengte van het ontwerp, in millimeters."""
    from meerk40t.core.units import UNITS_PER_MM

    totaal = 0.0
    for node in kernel.elements.elems():
        geom = node.as_geometry()
        totaal += sum(abs(geom.length(i)) for i in range(geom.index))
    return totaal / float(UNITS_PER_MM)


def _marks_at(client, boundary: int) -> list[dict]:
    """
    De merken van deze grens, aangetikt zonder fout.

    In het echt jog je ernaartoe; hier doen we alsof de plaat exact zo ver
    verschoven is als de opdeling zegt, zodat de test over de dekking gaat en
    niet over de tikprecisie.
    """
    opdeling = client.get("/api/tiling").json()
    merk = next(m for m in opdeling["marks"] if m["boundary"] == boundary)
    tegel = opdeling["tiles"][boundary + 1]
    dx = tegel["burn"]["x0_mm"]
    return [{"x_mm": p["x_mm"] - dx, "y_mm": p["y_mm"]} for p in merk["points"]]
