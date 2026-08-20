"""Machine catalogue, creation and settings — the setup flow's engine side."""

import json
import socket

import pytest
from fastapi.testclient import TestClient

from openkerf_api.machines import (
    RUIDA_LISTEN_PORT,
    MachineError,
    MachineManager,
    MachineScanner,
    ruida_probe_packet,
)
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


# ===================================================== detectie (besluit B6) ==
#
# De belofte van B6 is niet "hij vindt machines" maar "zoeken is lezen". Die
# belofte is een gedragsafspraak, en gedragsafspraken die niemand test slijten.


class FakeSerialPort:
    def __init__(self, device, vid, pid, description=""):
        self.device = device
        self.vid = vid
        self.pid = pid
        self.description = description


class FakeUsbDevice:
    def __init__(self, vid, pid, bus=1, address=2):
        self.idVendor = vid
        self.idProduct = pid
        self.bus = bus
        self.address = address


@pytest.fixture
def scanner(manager):
    return MachineScanner(manager.catalog())


def _no_usb(monkeypatch, scanner):
    monkeypatch.setattr(scanner, "_scan_usb", lambda notes, searched: [])


def _no_serial(monkeypatch, scanner):
    monkeypatch.setattr(scanner, "_scan_serial", lambda notes, searched: [])


def _no_network(monkeypatch, scanner):
    monkeypatch.setattr(scanner, "_scan_network", lambda notes, searched, s: [])


# ------------------------------------------------------- zoeken is lezen

def test_scanning_creates_no_machine(kernel, client):
    """De harde randvoorwaarde uit B6, en de reden dat dit een GET is."""
    before = {device.path for device in kernel.services("device")}
    active = kernel.device.path

    response = client.get("/api/machines/scan?network=false")

    assert response.status_code == 200
    assert {device.path for device in kernel.services("device")} == before
    assert kernel.device.path == active
    # En niets is stiekem als "door een mens ingesteld" gestempeld.
    assert not any(m["configured"] for m in client.get("/api/machines").json())


def test_scan_route_carries_no_write_guard_because_it_only_reads(client):
    """
    Een scan die zou kunnen schrijven, hoort achter het slot. Deze test legt
    de andere kant vast: hij staat er niet achter, dus hij mag ook nooit iets
    veranderen. Verandert dat, dan verandert deze test mee — bewust.
    """
    routes = [r for r in client.app.routes if getattr(r, "path", "") == "/api/machines/scan"]
    assert routes, "de scanroute bestaat"
    route = routes[0]
    assert route.methods == {"GET"}
    names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
    assert "require_write" not in names


def test_scanner_does_not_need_a_kernel_at_all(manager):
    """
    De scanner krijgt de catalogus als data mee en heeft geen kernel. Daarmee
    is 'hij kan niets aanmaken' geen belofte in een comment maar een feit van
    de constructie.
    """
    scanner = MachineScanner(manager.catalog())
    assert not hasattr(scanner, "kernel")


# --------------------------------------------------------------- herkenning

def test_serial_signature_becomes_a_candidate_with_its_port(monkeypatch, scanner):
    _no_usb(monkeypatch, scanner)
    _no_network(monkeypatch, scanner)
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [FakeSerialPort("/dev/cu.usbserial-1420", 0x0403, 0x6001, "FT232R")],
    )

    result = scanner.scan(network=False)

    assert len(result["candidates"]) == 1
    found = result["candidates"][0]
    assert found["transport"] == "serieel"
    assert found["where"] == "/dev/cu.usbserial-1420"
    assert found["settings"]["serial_port"] == "/dev/cu.usbserial-1420"
    assert "ruida-beta" in [s["key"] for s in found["suggestions"]]
    # Een FTDI-chip is geen bewijs van een Ruida; dat moet het scherm ook zeggen.
    assert found["confidence"] == "onzeker"


def test_unknown_serial_adapter_is_not_proposed(monkeypatch, scanner):
    """Een bluetoothpoort is geen laser. Raden waar we niets weten is erger dan zwijgen."""
    _no_usb(monkeypatch, scanner)
    _no_network(monkeypatch, scanner)
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [FakeSerialPort("/dev/cu.Bluetooth-Incoming-Port", None, None)],
    )

    assert scanner.scan(network=False)["candidates"] == []


def test_usb_signature_is_recognised(monkeypatch, scanner):
    _no_serial(monkeypatch, scanner)
    _no_network(monkeypatch, scanner)
    monkeypatch.setattr("usb.core.find", lambda **kw: iter([FakeUsbDevice(0x1A86, 0x5512)]))

    found = scanner.scan(network=False)["candidates"]

    assert len(found) == 1
    assert found[0]["kind"] == "co2-k40"
    assert found[0]["transport"] == "usb"


def test_a_suggestion_for_a_missing_plugin_is_dropped(monkeypatch):
    """
    De testkernel laadt geen GRBL. Een voorstel voor `grbl-generic` zou dan een
    knop opleveren die met een 409 eindigt; die filteren we eruit.
    """
    scanner = MachineScanner([])  # lege catalogus: niets is bekend
    _no_usb(monkeypatch, scanner)
    _no_network(monkeypatch, scanner)
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [FakeSerialPort("/dev/ttyUSB0", 0x1A86, 0x7523)],
    )

    found = scanner.scan(network=False)["candidates"][0]

    assert found["suggestions"] == []
    assert found["confidence"] == "onzeker"


def test_usb_without_permission_is_a_note_not_a_crash(monkeypatch, scanner):
    _no_serial(monkeypatch, scanner)
    _no_network(monkeypatch, scanner)

    def boom(**kw):
        raise OSError("access denied")

    monkeypatch.setattr("usb.core.find", boom)

    result = scanner.scan(network=False)

    assert result["candidates"] == []
    assert any("USB" in note for note in result["notes"])


# ------------------------------------------------------------------ netwerk

def test_the_ruida_probe_is_the_engines_own_enquiry():
    """
    We verzinnen geen eigen pakket voor een machine die kan bewegen. Dit is
    ENQ met de swizzle en checksum van de engine: dezelfde vraag die de driver
    bij elk verbinden stelt.
    """
    from meerk40t.ruida.rdjob import ENQ, encode_bytes

    packet = ruida_probe_packet()
    swizzled = encode_bytes(ENQ, magic=0x88)

    assert packet[2:] == swizzled
    assert int.from_bytes(packet[:2], "big") == sum(swizzled) & 0xFFFF
    assert len(packet) == 3  # één enkel byte vraag, geen opdracht


def test_network_scan_reports_a_host_that_answers(monkeypatch, scanner):
    """Een antwoordend adres komt terug als voorstel, met adres en interface ingevuld."""
    import ipaddress

    monkeypatch.setattr(
        MachineScanner, "_local_subnet", staticmethod(lambda: ipaddress.ip_network("10.0.0.0/30"))
    )

    class FakeSocket:
        def __init__(self, *a, **kw):
            self._left = 1

        def setsockopt(self, *a):
            pass

        def bind(self, *a):
            pass

        def settimeout(self, *a):
            pass

        def sendto(self, *a):
            pass

        def recvfrom(self, n):
            if self._left:
                self._left -= 1
                return b"\xcc", ("10.0.0.2", 40200)
            raise socket.timeout()

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", FakeSocket)

    result = scanner._scan_network([], [], seconds=0.5)

    assert len(result) == 1
    assert result[0]["settings"] == {"interface": "udp", "address": "10.0.0.2"}
    assert result[0]["transport"] == "netwerk"


def test_a_busy_listen_port_becomes_a_readable_note(monkeypatch, scanner):
    """
    Poort 40200 is niet configureerbaar. Is hij bezet, dan is dat een uitleg
    aan de gebruiker, geen stacktrace.
    """
    import ipaddress

    monkeypatch.setattr(
        MachineScanner, "_local_subnet", staticmethod(lambda: ipaddress.ip_network("10.0.0.0/30"))
    )
    notes = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
        try:
            blocker.bind(("", RUIDA_LISTEN_PORT))
        except OSError:
            # Er draait al een OpenKerf met een verbonden Ruida: die houdt deze
            # poort vast. Dan is de toestand die deze test nabouwt gewoon echt,
            # en hoeft hij niet als eigen fout te verschijnen.
            pytest.skip(f"poort {RUIDA_LISTEN_PORT} is al bezet buiten deze test")
        original = socket.socket

        class Exclusive(original):
            def setsockopt(self, *a):
                pass  # zonder SO_REUSEADDR botst de bind écht

        monkeypatch.setattr(socket, "socket", Exclusive)
        result = scanner._scan_network(notes, [], seconds=0.5)

    assert result == []
    assert any(str(RUIDA_LISTEN_PORT) in note for note in notes)


def test_network_scan_is_time_boxed():
    """Een scan die minuten hangt, is in de praktijk de scan die je afbreekt."""
    assert MachineScanner.MAX_SECONDS <= 6.0


def test_nothing_found_still_says_where_it_looked(monkeypatch, client):
    """
    De vaakst voorkomende uitkomst. Het antwoord moet dan nog steeds vertellen
    waar gekeken is — anders is 'niets gevonden' niet te vertrouwen.
    """
    result = client.get("/api/machines/scan?network=false").json()

    assert "candidates" in result
    assert result["searched"], "er is ergens gekeken"
    assert isinstance(result["duration_ms"], int)


# --------------------------- een machineprofiel uitwisselen (gat E5)


def _ruida(client):
    """Een Ruida, want die heeft een interface en een adres om mee te nemen."""
    return client.post(
        "/api/machines", json={"info": "ruida-beta", "label": "5030 Ruida"}
    ).json()


def test_a_profile_carries_the_type_and_the_settings(client):
    machine = _ruida(client)
    client.patch(
        f"/api/machines/{machine['path']}/settings",
        json={"bedwidth": "600mm", "bedheight": "400mm"},
    )

    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()

    assert profiel["format"] == "openkerf-machine"
    assert profiel["machine"]["info"] == "ruida-beta"
    assert profiel["machine"]["label"] == "5030 Ruida"
    assert profiel["machine"]["settings"]["bedwidth"] == "600mm"


def test_the_export_is_offered_as_a_file(client):
    machine = _ruida(client)

    response = client.get(f"/api/machines/{machine['path']}/export.openkerf-machine")

    assert response.status_code == 200
    assert ".openkerf-machine" in response.headers["content-disposition"]


def test_a_profile_recreates_the_machine_elsewhere(client, kernel):
    """
    Wie een tweede computer inricht, typt nu niets over. Dat is de hele reden
    van E5: LightBurn levert `.lbdev`, wij dit.
    """
    machine = _ruida(client)
    client.patch(
        f"/api/machines/{machine['path']}/settings",
        json={"bedwidth": "600mm", "bedheight": "400mm"},
    )
    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()
    client.delete(f"/api/machines/{machine['path']}")

    binnen = client.post(
        "/api/machines/import/upload",
        files={"file": ("5030.openkerf-machine", json.dumps(profiel), "application/json")},
    ).json()

    assert binnen["known"] is True
    assert binnen["essential"]["bedwidth"] == "600mm"

    gemaakt = client.post(
        "/api/machines/import", json={"profile": binnen["profile"]}
    ).json()

    settings = client.get(f"/api/machines/{gemaakt['path']}/settings").json()
    waarden = {
        veld["attr"]: veld["value"] for blad in settings for veld in blad["fields"]
    }
    assert waarden["bedwidth"] == "600mm"
    assert waarden["bedheight"] == "400mm"
    assert gemaakt["applied"] > 0


def test_the_preview_names_what_is_local_to_this_bench(client):
    """
    Het IP-adres van déze controller is het eerste dat elders niet klopt. Het
    gaat mee, maar het voorbeeld noemt het apart.
    """
    machine = _ruida(client)
    client.patch(
        f"/api/machines/{machine['path']}/settings", json={"address": "192.168.1.55"}
    )
    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()

    voorbeeld = client.post(
        "/api/machines/import/upload",
        files={"file": ("x.openkerf-machine", json.dumps(profiel), "application/json")},
    ).json()

    assert voorbeeld["local"]["address"] == "192.168.1.55"


def test_importing_creates_nothing_before_you_say_so(client):
    """Uploaden is kijken. Een profiel dat je nog niet accepteerde, bestaat niet."""
    machine = _ruida(client)
    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()
    voor = len(client.get("/api/machines").json())

    client.post(
        "/api/machines/import/upload",
        files={"file": ("x.openkerf-machine", json.dumps(profiel), "application/json")},
    )

    assert len(client.get("/api/machines").json()) == voor


def test_something_that_is_not_a_profile_is_refused(client):
    response = client.post(
        "/api/machines/import/upload",
        files={"file": ("x.openkerf-machine", '{"format": "iets anders"}', "application/json")},
    )

    assert response.status_code == 409
    assert "OpenKerf" in response.json()["detail"]


def test_a_profile_from_the_future_is_refused(manager):
    with pytest.raises(MachineError):
        manager.read_profile({"format": "openkerf-machine", "version": 99, "machine": {"info": "x"}})


def test_settings_this_engine_does_not_know_are_skipped_not_fatal(client):
    """
    Een profiel uit een nieuwere MeerK40t hoort je inrichting niet te blokkeren
    om één instelling die hier niet bestaat.
    """
    machine = _ruida(client)
    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()
    profiel["machine"]["settings"]["iets_van_later"] = 1
    client.delete(f"/api/machines/{machine['path']}")

    binnen = client.post(
        "/api/machines/import/upload",
        files={"file": ("x.openkerf-machine", json.dumps(profiel), "application/json")},
    ).json()
    gemaakt = client.post(
        "/api/machines/import", json={"profile": binnen["profile"]}
    ).json()

    assert gemaakt["skipped"] == ["iets_van_later"]
    assert gemaakt["path"]


def test_an_imported_machine_can_be_exported_again(client):
    """De rondgang: wat eruit komt, gaat er ook weer in."""
    machine = _ruida(client)
    profiel = client.get(
        f"/api/machines/{machine['path']}/export.openkerf-machine"
    ).json()
    binnen = client.post(
        "/api/machines/import/upload",
        files={"file": ("x.openkerf-machine", json.dumps(profiel), "application/json")},
    ).json()
    gemaakt = client.post(
        "/api/machines/import", json={"profile": binnen["profile"], "label": "Kopie"}
    ).json()

    opnieuw = client.get(
        f"/api/machines/{gemaakt['path']}/export.openkerf-machine"
    ).json()

    assert opnieuw["machine"]["info"] == profiel["machine"]["info"]
    assert opnieuw["machine"]["label"] == "Kopie"


def test_a_setting_also_emits_the_signals_it_declares(kernel):
    """
    Een instelling mag zeggen welke signalen erbij horen, en die horen mee.

    De engine kent daar een afspraak voor: een keuze draagt een `signals`-sleutel
    met de extra signalen die bij een wijziging horen. Wij seinden alleen de
    naam van de instelling zelf, en dat is precies één signaal te weinig — de
    grbl-controller luistert bijvoorbeeld op `update_interface` om zijn
    verbinding opnieuw op te bouwen (`grbl/controller.py:523`), niet op
    `interface`. Wie in OpenKerf de interface op `mock` zette, kreeg zijn
    instelling wél opgeslagen maar bleef op de oude verbinding zitten.

    Zeven-en-dertig van die declaraties staan in de engine, in elke driver:
    `coolant_changed`, `pwm_mode_changed`, `newly_autoplay`, `restart`. Ze
    vielen allemaal stil.
    """
    manager = MachineManager(kernel)
    device = kernel.device
    device.proefstand = "aan"
    device.register_choices(
        "proefstand",
        [
            {
                "attr": "proefstand",
                "object": device,
                "default": "aan",
                "type": str,
                "label": "Proefstand",
                "signals": ("bouw_opnieuw", "en_deze_ook"),
            }
        ],
    )

    gezien = []
    codes = ("proefstand", "bouw_opnieuw", "en_deze_ook")
    luisteraars = {
        code: (lambda origin, *args, code=code: gezien.append(code)) for code in codes
    }
    for code, luisteraar in luisteraars.items():
        kernel.listen(code, luisteraar)
    try:
        manager.update_settings(device.path, {"proefstand": "uit"})
        kernel.process_queue()
    finally:
        for code, luisteraar in luisteraars.items():
            kernel.unlisten(code, luisteraar)

    assert device.proefstand == "uit"
    assert "proefstand" in gezien
    assert "bouw_opnieuw" in gezien and "en_deze_ook" in gezien
