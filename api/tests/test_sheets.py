"""
Vellen: meerdere stukken materiaal in één project.

Elk vel is een eigen document. De kern van deze tests is dan ook: blijft de
inhoud van een vel staan als je wegwisselt en terugkomt, en komt er nooit iets
van het ene vel op het andere terecht.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "v.db").build_app()) as c:
        yield c


def a_rect(client, x=10, y=10, w=20, h=10):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": y, "width_mm": w, "height_mm": h},
    ).json()["ids"][0]


def count(client):
    return len(client.get("/api/design").json()["elements"])


def test_a_project_always_has_one_sheet(client):
    """Een project zonder vel bestaat niet, net zomin als een laser zonder bed."""
    state = client.get("/api/sheets").json()

    assert len(state["sheets"]) == 1
    assert state["sheets"][0]["active"] is True
    assert state["sheets"][0]["width_mm"] > 0


def test_a_new_sheet_takes_the_bed_size_by_default(client):
    bed = client.get("/api/devices").json()[0]["bed"]

    added = client.post("/api/sheets", json={}).json()

    assert len(added["sheets"]) == 2
    assert added["sheets"][1]["width_mm"] == pytest.approx(bed["width_mm"], abs=0.2)


def test_a_sheet_can_be_smaller_than_the_bed(client):
    """Een vel is een stuk materiaal, geen kopie van het bed."""
    added = client.post(
        "/api/sheets", json={"name": "Restje acryl", "width_mm": 120, "height_mm": 80}
    ).json()

    assert added["sheets"][1]["name"] == "Restje acryl"
    assert added["sheets"][1]["width_mm"] == 120


def test_switching_sheets_keeps_each_ones_content(client):
    """
    Dit is waar het om draait: elk vel is een eigen document, dus wat je op het
    ene tekent hoort niet op het andere te staan — en moet er nog zijn als je
    terugkomt.
    """
    a_rect(client, x=10)
    a_rect(client, x=50)
    assert count(client) == 2

    second = client.post("/api/sheets", json={"name": "Tweede"}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")

    assert count(client) == 0, "het tweede vel begint leeg"
    a_rect(client, x=30)
    assert count(client) == 1

    client.post("/api/sheets/vel-1/activate")
    assert count(client) == 2, "het eerste vel is zijn inhoud kwijt"

    client.post(f"/api/sheets/{second['id']}/activate")
    assert count(client) == 1


def test_the_selection_can_move_to_another_sheet(client):
    keep = a_rect(client, x=10)
    goes = a_rect(client, x=60)
    second = client.post("/api/sheets", json={}).json()["sheets"][1]

    response = client.post(f"/api/sheets/{second['id']}/move", json={"ids": [goes]})

    assert response.status_code == 200
    # We staan nu op het tweede vel, met alleen het verplaatste element.
    assert response.json()["active"] == second["id"]
    assert count(client) == 1

    client.post("/api/sheets/vel-1/activate")
    elements = client.get("/api/design").json()["elements"]
    assert len(elements) == 1
    assert elements[0]["id"] == keep


def test_moving_to_the_sheet_you_are_on_is_refused(client):
    rect = a_rect(client)

    response = client.post("/api/sheets/vel-1/move", json={"ids": [rect]})

    assert response.status_code == 409


def test_moving_nothing_is_refused(client):
    client.post("/api/sheets", json={})

    assert client.post("/api/sheets/vel-2/move", json={"ids": []}).status_code == 409


def test_a_sheet_can_be_renamed_and_resized(client):
    client.patch("/api/sheets/vel-1", json={"name": "Berken 3mm", "width_mm": 300})

    sheet = client.get("/api/sheets").json()["sheets"][0]
    assert sheet["name"] == "Berken 3mm"
    assert sheet["width_mm"] == 300


def test_a_sheet_carries_one_material(client):
    """Daarmee kloppen de presets en de tijdschatting per vel."""
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()

    client.patch("/api/sheets/vel-1", json={"material_id": material["id"]})

    assert client.get("/api/sheets").json()["sheets"][0]["material_id"] == material["id"]


def test_deleting_a_sheet_removes_its_content_too(client):
    second = client.post("/api/sheets", json={}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    a_rect(client)

    client.delete(f"/api/sheets/{second['id']}")

    state = client.get("/api/sheets").json()
    assert [s["id"] for s in state["sheets"]] == ["vel-1"]
    # En we staan niet meer op het vel dat weg is.
    assert state["active"] == "vel-1"
    assert count(client) == 0


def test_the_last_sheet_cannot_be_deleted(client):
    assert client.delete("/api/sheets/vel-1").status_code == 409


def test_an_absurd_sheet_size_is_refused(client):
    for size in ({"width_mm": 1}, {"height_mm": 9000}, {"width_mm": -50}):
        assert client.post("/api/sheets", json=size).status_code == 409


def test_sheets_survive_a_project_file(client, tmp_path):
    """
    Anders is het projectbestand een halve waarheid: je krijgt één vel terug en
    de rest van je werk is weg.
    """
    a_rect(client, x=10)
    second = client.post(
        "/api/sheets", json={"name": "Acryl", "width_mm": 120, "height_mm": 80}
    ).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    a_rect(client, x=30)
    a_rect(client, x=70)

    saved = client.get("/api/project/export.openkerf")
    assert saved.status_code == 200
    bundle = tmp_path / "project.openkerf"
    bundle.write_bytes(saved.content)

    # Alles weggooien en het project weer openen.
    client.delete(f"/api/sheets/{second['id']}")
    client.post("/api/design/clear")

    with bundle.open("rb") as handle:
        opened = client.post(
            "/api/project/open", files={"file": ("project.openkerf", handle)}
        )
    assert opened.status_code == 200

    state = client.get("/api/sheets").json()
    assert [s["name"] for s in state["sheets"]] == ["Vel 1", "Acryl"]
    assert state["sheets"][1]["width_mm"] == 120

    client.post("/api/sheets/vel-1/activate")
    assert count(client) == 1
    client.post(f"/api/sheets/{second['id']}/activate")
    assert count(client) == 2


def test_sheet_names_stay_unique(client):
    """
    Twee dozen achter elkaar leverden anders twee vellen die allebei "Doos 2"
    heten, en dan weet je niet welke welke is.
    """
    client.post("/api/sheets", json={"name": "Doos 2"})
    client.post("/api/sheets", json={"name": "Doos 2"})

    names = [s["name"] for s in client.get("/api/sheets").json()["sheets"]]

    assert names == ["Vel 1", "Doos 2", "Doos 2 (2)"]


# -------------------------------------------------------------- jobnaam (P4)


def _job_labels(kernel):
    return [str(getattr(job, "label", "")) for job in kernel.device.spooler.queue]


def _burnable_rect(client, x=10):
    """Een rechthoek in een eigen laag: genoeg om een job te mogen starten."""
    rect = a_rect(client, x=x)
    layer = client.post(
        "/api/design/operations", json={"type": "cut", "label": "Snijden"}
    ).json()["id"]
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": layer})
    return rect


def test_a_job_carries_the_sheet_name_after_switching_sheets(kernel, client):
    """
    Elke job heette ooit `herstel.svg`. Dezelfde fout zit één deur verder: het
    wisselen van vel laadt `vel-1.svg` terug, en die interne bestandsnaam ging
    als jobnaam de wachtrij in. Bij de machine staan dan jobs die `vel-1.svg`
    heten, terwijl de gebruiker "Vel 1" en "Proefstuk" op zijn tabbladen ziet.
    """
    _burnable_rect(client)
    second = client.post("/api/sheets", json={"name": "Proefstuk"}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    _burnable_rect(client, x=30)

    assert client.post("/api/job/start").status_code == 200
    assert _job_labels(kernel)[-1] == "Proefstuk"

    client.post("/api/spooler/clear")
    # Terug naar een vel dat wél een bewaard bestand heeft: dat is het pad waar
    # de bestandsnaam de naam van het vel overschreef.
    client.post("/api/sheets/vel-1/activate")
    assert client.post("/api/job/start").status_code == 200
    assert _job_labels(kernel)[-1] == "Vel 1"


# ------------------------------------------------------------------ herstart


def test_a_restart_comes_back_to_the_sheet_you_left(kernel, tmp_path):
    """
    Na een herstart stond de vellenbalk op "Vel 1" terwijl het canvas leeg was:
    het vel was nooit ingeladen. Wie dan één keer van vel wisselde, verloor
    alles — wegwisselen ziet een lege boom en gooit `vel-1.svg` weg.
    """
    library = tmp_path / "v.db"
    with TestClient(ApiServer(kernel, library_path=library).build_app()) as first:
        a_rect(first)
        first.post("/api/sheets", json={"name": "Tweede"})
        first.post("/api/sheets/vel-2/activate")
        first.post("/api/sheets/vel-1/activate")
        assert count(first) == 1

    # De herstart: verse server, lege elementenboom, dezelfde map op schijf.
    kernel.elements.clear_all()
    with TestClient(ApiServer(kernel, library_path=library).build_app()) as second:
        # De vellenbalk vraagt dit bij het openen van de pagina.
        second.get("/api/sheets")
        assert count(second) == 1, "het actieve vel hoort weer op tafel te liggen"

        second.post("/api/sheets/vel-2/activate")

    bewaard = tmp_path / "openkerf-vellen" / "vel-1.svg"
    assert bewaard.is_file(), "wisselen na een herstart gooide het vel weg"


# ----------------------------------------------------------------- materiaal

def test_a_sheet_carries_a_material_and_a_thickness(client):
    """
    Besluit B1: materiaal en dikte hangen aan het vel.

    Zonder dat weet niets stroomafwaarts waarin je brandt — de bibliotheek niet,
    het testraster niet, en de pre-flight al helemaal niet.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()

    state = client.patch(
        "/api/sheets/vel-1", json={"material_id": material["id"], "thickness_mm": 3}
    ).json()

    sheet = state["sheets"][0]
    assert sheet["material_id"] == material["id"]
    assert sheet["thickness_mm"] == 3


def test_a_sheet_without_a_material_stays_empty(client):
    """Een restje van onbekende dikte hoeft geen verzonnen getal te krijgen."""
    sheet = client.get("/api/sheets").json()["sheets"][0]

    assert sheet["material_id"] is None
    assert sheet["thickness_mm"] is None


def test_the_thickness_can_be_cleared_again(client):
    client.patch("/api/sheets/vel-1", json={"thickness_mm": 3})

    state = client.patch("/api/sheets/vel-1", json={"thickness_mm": None}).json()

    assert state["sheets"][0]["thickness_mm"] is None


def test_an_impossible_thickness_is_refused(client):
    assert client.patch("/api/sheets/vel-1", json={"thickness_mm": -2}).status_code == 409
    assert client.patch("/api/sheets/vel-1", json={"thickness_mm": 900}).status_code == 409


def test_each_sheet_keeps_its_own_material(client):
    """Dun en dik in één project: dat is de reden dat dit per vel gaat."""
    berken = client.post("/api/library/materials", json={"name": "Berken"}).json()
    acryl = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    client.post("/api/sheets", json={"material_id": acryl["id"], "thickness_mm": 5})

    sheets = client.get("/api/sheets").json()["sheets"]

    assert [s["material_id"] for s in sheets] == [berken["id"], acryl["id"]]
    assert [s["thickness_mm"] for s in sheets] == [3, 5]
