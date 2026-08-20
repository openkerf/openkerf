"""Nesten en de pen: vormen dicht op elkaar, en vrij tekenen."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "n.db").build_app()) as c:
        yield c


def a_rect(client, x, y, w=20, h=10):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": y, "width_mm": w, "height_mm": h},
    ).json()["ids"][0]


def boxes(client):
    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    return {
        e["id"]: [v / per_mm for v in e["bounds"]]
        for e in design["elements"]
        if e["bounds"]
    }


# ------------------------------------------------------------------- nesten


def test_nesting_pulls_scattered_shapes_together(client):
    ids = [a_rect(client, 10, 10), a_rect(client, 200, 150), a_rect(client, 90, 240)]

    response = client.post("/api/design/nest", json={"ids": ids, "margin_mm": 3})

    assert response.status_code == 200
    placed = boxes(client)
    spread = max(b[2] for b in placed.values()) - min(b[0] for b in placed.values())
    assert spread < 80, "de vormen liggen nog steeds ver uit elkaar"


def test_nested_shapes_do_not_touch(client):
    """
    Twee sneden die elkaar raken zijn één snede. De marge staat er om de
    snijbreedte en het brandrandje heen, dus die moet echt overblijven.
    """
    ids = [a_rect(client, 10, 10, 30, 20), a_rect(client, 100, 100, 25, 40)]
    margin = 4

    client.post("/api/design/nest", json={"ids": ids, "margin_mm": margin})

    first, second = (boxes(client)[i] for i in ids)
    apart_x = second[0] - first[2] >= margin - 0.1 or first[0] - second[2] >= margin - 0.1
    apart_y = second[1] - first[3] >= margin - 0.1 or first[1] - second[3] >= margin - 0.1
    assert apart_x or apart_y


def test_nesting_wraps_to_a_new_row_beyond_the_bed(client):
    ids = [a_rect(client, 0, 0, 200, 10) for _ in range(6)]

    client.post("/api/design/nest", json={"ids": ids, "margin_mm": 5})

    placed = boxes(client)
    tops = {round(b[1], 1) for b in placed.values()}
    assert len(tops) > 1, "alles staat op één regel, breder dan het bed"


def test_nesting_one_shape_is_refused(client):
    response = client.post("/api/design/nest", json={"ids": [a_rect(client, 5, 5)]})
    assert response.status_code == 409


def test_a_negative_margin_is_refused(client):
    ids = [a_rect(client, 5, 5), a_rect(client, 60, 5)]
    response = client.post("/api/design/nest", json={"ids": ids, "margin_mm": -2})
    assert response.status_code == 409


# ---------------------------------------------------------------------- pen


def test_the_pen_draws_a_path_at_the_size_asked_for(client):
    response = client.post(
        "/api/design/path",
        json={"points": [[10, 10], [60, 10], [60, 40]], "closed": False},
    )

    assert response.status_code == 201
    element = boxes(client)[response.json()["ids"][0]]
    assert element[2] - element[0] == pytest.approx(50, abs=0.5)
    assert element[3] - element[1] == pytest.approx(30, abs=0.5)


def test_a_closed_path_returns_to_its_start(client):
    open_path = client.post(
        "/api/design/path", json={"points": [[0, 0], [40, 0], [40, 30]]}
    ).json()["ids"][0]
    closed = client.post(
        "/api/design/path",
        json={"points": [[0, 100], [40, 100], [40, 130]], "closed": True},
    ).json()["ids"][0]

    design = client.get("/api/design").json()["elements"]
    lengths = {e["id"]: len(e["path"]) for e in design}
    assert lengths[closed] > lengths[open_path]


def test_a_control_point_bends_the_line(client):
    """Een punt van vier getallen trekt de lijn ernaartoe krom."""
    straight = client.post(
        "/api/design/path", json={"points": [[0, 0], [40, 0]]}
    ).json()["ids"][0]
    curved = client.post(
        "/api/design/path", json={"points": [[0, 50], [40, 50, 20, 30]]}
    ).json()["ids"][0]

    placed = boxes(client)
    assert placed[curved][3] - placed[curved][1] > placed[straight][3] - placed[straight][1]


def test_a_path_of_one_point_is_refused(client):
    response = client.post("/api/design/path", json={"points": [[10, 10]]})
    assert response.status_code == 409


def test_a_malformed_point_is_refused(client):
    response = client.post("/api/design/path", json={"points": [[10, 10], [1, 2, 3]]})
    assert response.status_code == 409


# ------------------------------------------------------- een groep is één ding


def test_nesting_moves_a_group_as_one_thing(client):
    """
    Wat gegroepeerd is, houdt onderling exact zijn plek.

    Het nestte élk element los, dus een tandwiel van vier vormen — of een
    testbord van negen vakjes — kwam er als losse onderdelen in nette rijen uit.
    """
    links = a_rect(client, 5, 5, 20, 10)
    rechts = a_rect(client, 40, 5, 20, 10)
    client.post("/api/design/group", json={"ids": [links, rechts]})
    los = a_rect(client, 5, 200, 30, 30)

    voor = boxes(client)
    onderling = [
        voor[rechts][0] - voor[links][0],
        voor[rechts][1] - voor[links][1],
    ]

    antwoord = client.post(
        "/api/design/nest", json={"ids": [links, rechts, los], "margin_mm": 3}
    )
    assert antwoord.status_code == 200

    na = boxes(client)
    assert [na[rechts][0] - na[links][0], na[rechts][1] - na[links][1]] == pytest.approx(
        onderling
    )
    # De groep is als geheel verhuisd — dat is wat nesten hoort te doen.
    assert na[los][1] == pytest.approx(na[links][1], abs=0.1) or na[los] != voor[los]


def test_one_group_and_one_shape_are_two_units(client):
    """
    Twee vormen die samen één groep zijn, tellen als één ding.

    Anders zou "nest deze twee" op een gegroepeerd paar zeggen dat het er twee
    zijn en het paar alsnog uit elkaar trekken.
    """
    a = a_rect(client, 5, 5)
    b = a_rect(client, 40, 5)
    client.post("/api/design/group", json={"ids": [a, b]})

    antwoord = client.post("/api/design/nest", json={"ids": [a, b], "margin_mm": 3})

    assert antwoord.status_code == 409
    assert "at least two" in antwoord.json()["detail"]
