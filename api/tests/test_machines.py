"""Machine catalogue, creation and settings — the setup flow's engine side."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.machines import MachineError, MachineManager
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as c:
        yield c


@pytest.fixture
def manager(kernel):
    return MachineManager(kernel)


# ---------------------------------------------------------------- catalogue

def test_catalog_is_grouped_by_family(client):
    catalog = client.get("/api/machines/catalog").json()

    assert catalog, "MeerK40t ships a dev_info catalogue"
    for family in catalog:
        assert family["family"]
        assert family["machines"]
        for machine in family["machines"]:
            assert machine["key"]
            assert machine["friendly_name"]
            assert isinstance(machine["defaults"], dict)


def test_catalog_contains_the_ruida_entry(client):
    keys = {
        machine["key"]
        for family in client.get("/api/machines/catalog").json()
        for machine in family["machines"]
    }
    assert "ruida-beta" in keys


# ----------------------------------------------------------------- creation

def test_create_adds_and_activates_a_machine(kernel, manager):
    before = len(list(kernel.services("device")))

    created = manager.create("ruida-beta")

    assert len(list(kernel.services("device"))) == before + 1
    assert created["active"] is True
    assert kernel.device.path == created["path"]


def test_create_applies_a_custom_label(kernel, manager):
    """
    Upstream `device add -l` mangles the choices list and crashes, so the
    manager sets the label itself. This test fails if that workaround is
    dropped before upstream is fixed.
    """
    created = manager.create("ruida-beta", label="5030 CO2")

    assert created["label"] == "5030 CO2"
    assert kernel.device.label == "5030 CO2"


def test_create_rejects_an_unknown_type(manager):
    with pytest.raises(MachineError):
        manager.create("geen-bestaand-type")


def test_create_over_http_returns_201(client):
    response = client.post("/api/machines", json={"info": "ruida-beta", "label": "Test"})

    assert response.status_code == 201
    assert response.json()["label"] == "Test"


def test_create_without_info_is_a_422(client):
    assert client.post("/api/machines", json={}).status_code == 422


# ------------------------------------------------------- activate / rename

def test_list_marks_the_active_machine(kernel, manager):
    manager.create("ruida-beta", label="Nieuw")
    machines = manager.list()

    active = [m for m in machines if m["active"]]
    assert len(active) == 1
    assert active[0]["label"] == "Nieuw"


def test_activate_switches_device(kernel, manager):
    original = kernel.device.path
    manager.create("ruida-beta")
    assert kernel.device.path != original

    manager.activate(original)

    assert kernel.device.path == original


def test_rename_changes_the_label(kernel, manager):
    created = manager.create("ruida-beta")
    manager.rename(created["path"], "Werkplaats")
    assert kernel.device.label == "Werkplaats"


def test_active_machine_cannot_be_removed(kernel, manager):
    created = manager.create("ruida-beta")
    with pytest.raises(MachineError):
        manager.remove(created["path"])


def test_remove_deletes_an_inactive_machine(kernel, manager):
    original = kernel.device.path
    created = manager.create("ruida-beta")
    manager.activate(original)

    manager.remove(created["path"])

    assert created["path"] not in {m["path"] for m in manager.list()}


def test_unknown_machine_is_a_409(client):
    assert client.post("/api/machines/nietbestaand/activate").status_code == 409


# ------------------------------------------------------------------ settings

def test_settings_describe_type_label_and_value(kernel, manager):
    path = kernel.device.path
    sheets = manager.settings(path)

    assert sheets
    fields = [field for sheet in sheets for field in sheet["fields"]]
    by_attr = {field["attr"]: field for field in fields}
    assert "bedwidth" in by_attr
    assert by_attr["bedwidth"]["label"]
    assert by_attr["bedwidth"]["type"] == "str"
    assert by_attr["bedwidth"]["value"]


def test_values_are_json_safe(kernel, manager):
    """Ruida types bedwidth as Length; the raw object would dump its internals."""
    created = manager.create("ruida-beta", label="Ruida")
    fields = [f for s in manager.settings(created["path"]) for f in s["fields"]]
    by_attr = {f["attr"]: f for f in fields}

    value = by_attr["bedwidth"]["value"]
    assert by_attr["bedwidth"]["type"] == "str"
    assert isinstance(value, str)
    # A readable unit string ("24.0in", "500mm") — not an object dump.
    assert value[-1].isalpha() and "{" not in value


def test_connection_settings_appear_even_without_a_choices_sheet(kernel, manager):
    """Ruida creates `interface` with a bare setting(), so no sheet lists it."""
    created = manager.create("ruida-beta", label="Ruida")
    fields = [f for s in manager.settings(created["path"], True) for f in s["fields"]]
    by_attr = {f["attr"]: f for f in fields}

    assert "interface" in by_attr
    assert by_attr["interface"]["options"] == ["usb", "udp"]

    manager.update_settings(created["path"], {"interface": "udp"})
    assert kernel.device.interface == "udp"


def test_essential_filter_narrows_the_list(kernel, manager):
    path = kernel.device.path
    everything = sum(len(s["fields"]) for s in manager.settings(path))
    essential = sum(len(s["fields"]) for s in manager.settings(path, essential_only=True))

    assert 0 < essential < everything


def test_update_settings_applies_and_coerces(kernel, manager):
    path = kernel.device.path

    applied = manager.update_settings(path, {"bedwidth": "500mm", "bedheight": "300mm"})

    assert applied["bedwidth"] == "500mm"
    assert kernel.device.bedwidth == "500mm"
    assert kernel.device.bedheight == "300mm"


def test_update_rejects_an_unknown_setting(kernel, manager):
    with pytest.raises(MachineError):
        manager.update_settings(kernel.device.path, {"verzonnen_instelling": 1})


def test_update_over_http(kernel, client):
    path = kernel.device.path

    response = client.patch(f"/api/machines/{path}/settings", json={"bedwidth": "420mm"})

    assert response.status_code == 200
    assert kernel.device.bedwidth == "420mm"


def test_bed_change_is_visible_in_the_status_snapshot(kernel, client):
    path = kernel.device.path
    client.patch(f"/api/machines/{path}/settings", json={"bedwidth": "500mm"})

    device = client.get("/api/status").json()["devices"][0]

    assert device["bed"]["width_mm"] == pytest.approx(500.0, abs=0.5)
