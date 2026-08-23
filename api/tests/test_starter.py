"""
The offer a machine with no settings gets, and the staging that answers it.

Every number here is off the author's live 204 KB library, read on :8091: seven machine
profiles for two devices, the phantom `5030 CO2` carrying 27 presets with no device, the
active `KH-5030` carrying 3 with `power_watt: null`, 4 presets and 11 boards with
`machine_id IS NULL`, and 20 materials. That shape is what the fixture below rebuilds,
because every wrong answer this file catches is an answer that looks right on an empty
database.
"""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import Library, LibraryError
from openkerf_api.server import ApiServer
from openkerf_api.starter import Starter

CATALOGUE = {
    "schema_version": 2,
    "version": "starter-1",
    "presets": [
        {
            "id": "berken-3mm-snijden-co2-80w",
            "material": "Berkentriplex",
            "synonyms": ["birch plywood"],
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 12,
            "power_percent": 65,
            "passes": 1,
            "air_assist": True,
            "focus_offset_mm": 0,
            "note": "Starting value, not measured.",
            "source": {"kind": "handmatig", "by": "presetariat-prefill"},
            "verified": False,
        },
        {
            "id": "mdf-6mm-snijden-co2-80w",
            "material": "MDF",
            "thickness_mm": 6,
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 8,
            "power_percent": 80,
            "passes": 2,
            "source": {"kind": "handmatig", "by": "presetariat-prefill"},
        },
        {
            # A diode row, so that "everything for this kind of laser" can be told apart
            # from "everything". Live, all 26 rows are 80 W CO2 and a bug that showed
            # them all would look identical to a bug that filtered nothing.
            "id": "acryl-3mm-snijden-diode-10w",
            "material": "Acrylaat",
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "diode", "power_watt": 10},
            "speed_mm_s": 3,
            "power_percent": 100,
            "source": {"kind": "handmatig"},
        },
    ],
}


@pytest.fixture
def catalogue_file(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(CATALOGUE))
    return path


@pytest.fixture
def live_shaped(tmp_path):
    """
    A library the shape of the author's: a phantom profile with all the settings, a
    real machine with almost none, and a pile of rows that belong to no machine at all.
    """
    library = Library(tmp_path / "starter.db")
    phantom = library.add_machine(name="5030 CO2", power_watt=60)["id"]
    active = library.add_machine(
        name="KH-5030", device_path="ruida", laser_type="co2-glass", power_watt=80
    )["id"]
    bare = library.add_machine(
        name="A third laser", device_path="grbl", laser_type="co2-glass", power_watt=80
    )["id"]
    materials = [library.add_material(f"Material {n}")["id"] for n in range(20)]

    def preset(machine_id, material_id, source="handmatig"):
        library.add_preset(
            material_id=material_id,
            machine_id=machine_id,
            operation="snijden",
            speed_mm_s=12,
            power_percent=60,
            source=source,
        )

    for n in range(27):
        preset(phantom, materials[n % 20], source="geimporteerd")
    # The three the active machine really has, all off a test grid.
    for _ in range(3):
        preset(active, materials[0], source="testraster")
    for _ in range(4):
        preset(None, materials[1])
    return library, phantom, active, bare


@pytest.fixture
def starter(live_shaped, tmp_path, catalogue_file):
    from openkerf_api.presetariat import Presetariat

    library = live_shaped[0]
    shop = Presetariat(library, tmp_path / "cache.json", url=catalogue_file.as_uri())
    return Starter(library, shop)


def profile(library, machine_id):
    return next(m for m in library.machines() if m["id"] == machine_id)


# --------------------------------------------------------------- the detection


def test_a_fresh_machine_is_reported_as_having_nothing(starter, live_shaped):
    """
    Thirty-one presets in the file and none of them this machine's.

    Measured live: the bare machine's neighbours hold 27 presets on a profile with no
    device and 4 with no machine at all, and both were being counted by any detection
    that reused `Library.presets()` — its WHERE is `(p.machine_id = ? OR p.machine_id IS
    NULL)`. A machine that looks supplied is never offered anything, which is exactly the
    complaint: the app names machines the user never defined and says nothing about the
    one in front of them.
    """
    library, phantom, active, bare = live_shaped

    offer = starter.offer(profile(library, bare))

    assert offer["state"] == "nothing"
    assert offer["needed"] is True
    assert offer["coverage"]["mine"] == 0
    # The sentence still carries the library-wide numbers, because "one of your twenty
    # materials" is the fact the reader recognises. It just does not decide anything.
    assert offer["coverage"]["materials_known"] == 20
    assert offer["coverage"]["unattached"] == 4


def test_the_detection_does_not_reuse_the_preset_view(starter, live_shaped, monkeypatch):
    """
    `Library.presets()` must not be on this path, in any refactor.

    It admits `machine_id IS NULL` on purpose — a preset made before there were profiles
    holds everywhere — and that is precisely the four rows measured on an unknown machine
    that would make a bare laser look supplied. Blowing up in `presets()` is the only way
    to pin "does not go through there" rather than "happens to agree today".
    """
    library, phantom, active, bare = live_shaped

    def refuse(*args, **kwargs):
        raise AssertionError("the offer went through Library.presets()")

    monkeypatch.setattr(type(library), "presets", refuse)

    assert starter.offer(profile(library, bare))["coverage"]["mine"] == 0


def test_the_offer_costs_no_catalogue(starter, live_shaped, monkeypatch):
    """
    Opening the material library must not wait on the network.

    The catalogue URL answers 404 for everyone today (the repository is private), and
    the only reason the author's install looks alive is a 12.9 KB cache from 13 August.
    An offer that fetched would be a spinner on every open and an error on a fresh
    install, so the detection is six `COUNT(*)`s and nothing else.
    """
    library, phantom, active, bare = live_shaped
    monkeypatch.setattr(
        type(starter.presetariat),
        "catalogue",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched the catalogue")),
    )

    assert starter.offer(profile(library, bare))["needed"] is True


def test_the_offer_is_made_once_and_not_again(starter, live_shaped):
    """
    Waved away stays waved away, and one setting of your own ends it too.

    Without the first half the card returns on every open of the library — this is the
    state evidence's `materials_covered < 3` would sit in forever on this library (1 of
    20). Without the second, a machine that has been burned on still gets offered
    starting values for it.
    """
    library, phantom, active, bare = live_shaped
    assert starter.offer(profile(library, bare))["needed"] is True

    starter.dismiss(profile(library, bare))
    assert starter.offer(profile(library, bare))["needed"] is False

    # And the machine that has burned something is not offered a set either — the three
    # measured settings on the active profile are what "none" means.
    assert starter.offer(profile(library, active))["state"] == "none"
    assert starter.offer(profile(library, active))["needed"] is False


def test_settings_that_came_out_of_a_catalogue_ask_for_a_test_grid(starter, live_shaped):
    """
    Twenty-seven settings, nothing burned. That is not "covered".

    The phantom profile's rows are all `source='geimporteerd'` — starting values from
    the 26-row prefill — so the honest answer is not another fetch but a test grid on
    this laser. `unburned` is the state that says so.
    """
    library, phantom, active, bare = live_shaped

    offer = starter.offer(profile(library, phantom))

    assert offer["coverage"]["mine"] == 27
    assert offer["coverage"]["mine_measured"] == 0
    assert offer["state"] == "unburned"


def test_a_machine_with_no_tube_power_is_asked_before_anything_is_fetched(
    starter, live_shaped
):
    """
    All seven live profiles have `power_watt: null`, and the old code showed them 26 of
    26 rows (`if watt and mine:` skipped the test whenever either side was NULL). The
    fix is not a silent empty list: it is the card asking, once.
    """
    library, phantom, active, bare = live_shaped
    library.update_machine(bare, {"power_watt": None})

    assert starter.offer(profile(library, bare))["state"] == "askMachine"
    with pytest.raises(LibraryError) as refused:
        starter.stage(profile(library, bare), library.path.parent)
    assert refused.value.code == "library.starter.needsWatt"
    assert refused.value.values == {"machine": "A third laser"}


def test_not_knowing_the_tube_power_is_a_real_answer(starter, live_shaped, tmp_path):
    """
    `dev_info` carries no wattage anywhere — grepped every `defaults` block for `watt`
    and `power` — so there is nothing to default from and a refusal would be a dead end
    on the whole requirement. Saying so matches on the kind alone, and the diode row
    stays out even then: an unknown wattage is not an unknown laser.
    """
    library, phantom, active, bare = live_shaped
    library.update_machine(bare, {"power_watt": None, "starter_state": "power_unknown"})

    assert starter.offer(profile(library, bare))["state"] == "nothing"

    staged = starter.stage(profile(library, bare), tmp_path)

    assert staged["ids"] == [
        "berken-3mm-snijden-co2-80w",
        "mdf-6mm-snijden-co2-80w",
    ]


def test_a_laser_of_an_unknown_kind_is_asked_even_when_the_power_is_unknown(
    starter, live_shaped, tmp_path
):
    """
    The escape hatch is about the wattage, not about the kind.

    `matching.fits` treats `unknown` as a miss in both directions, so a fetch on an
    unknown kind returns nothing whatever the wattage says — the plan's table, read
    literally, would offer a button that answers with an empty list. A CO2 setting on a
    diode is not a starting point, so this asks instead.
    """
    library, phantom, active, bare = live_shaped
    library.update_machine(
        bare, {"laser_type": "unknown", "starter_state": "power_unknown"}
    )

    assert starter.offer(profile(library, bare))["state"] == "askMachine"
    with pytest.raises(LibraryError) as refused:
        starter.stage(profile(library, bare), tmp_path)
    assert refused.value.code == "library.starter.needsKind"


def test_a_machine_that_already_has_settings_is_not_handed_a_starter_set(
    starter, live_shaped, tmp_path
):
    """
    The offer is for a machine with nothing. A machine with three measured settings
    getting a set of guesses on top is how a library becomes a junk drawer — measured:
    one bulk tick-list produced 14 of the author's 20 materials, all bound to a machine
    he does not run.

    One row asked for by name is a different act and stays allowed: the per-material
    drawer has to work on a machine that already has settings, which is most machines.
    """
    library, phantom, active, bare = live_shaped

    with pytest.raises(LibraryError) as refused:
        starter.stage(profile(library, active), tmp_path)
    assert refused.value.code == "library.starter.notEmpty"

    staged = starter.stage(
        profile(library, active), tmp_path, ids=["mdf-6mm-snijden-co2-80w"]
    )
    assert staged["ids"] == ["mdf-6mm-snijden-co2-80w"]


def test_a_row_filed_under_another_laser_is_still_offered_to_this_one(
    starter, live_shaped, tmp_path
):
    """
    Measured on the live library: all 26 catalogue rows are already imported — every one
    of them onto the phantom `5030 CO2` — so a filter on "is this id anywhere in the
    library" leaves the machine the engine is actually on with nothing to be offered.
    That is the complaint restated, not the fix. A setting filed under another laser is
    not this laser's setting.

    The other half has to hold too, or the drawer offers the same row for ever.
    """
    library, phantom, active, bare = live_shaped
    library.add_preset(
        material_id=library.materials()[0]["id"],
        machine_id=phantom,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="geimporteerd",
        origin_id="berken-3mm-snijden-co2-80w",
    )

    assert "berken-3mm-snijden-co2-80w" in starter.stage(
        profile(library, bare), tmp_path
    )["ids"]

    library.add_preset(
        material_id=library.materials()[0]["id"],
        machine_id=bare,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="geimporteerd",
        origin_id="berken-3mm-snijden-co2-80w",
    )
    # And now that this machine has it, it is not offered again — nor is the machine
    # offered a whole set any more, because it has a setting of its own.
    with pytest.raises(LibraryError) as refused:
        starter.stage(profile(library, bare), tmp_path)
    assert refused.value.code == "library.starter.notEmpty"
    assert starter.stage(
        profile(library, bare), tmp_path, ids=["mdf-6mm-snijden-co2-80w"]
    )["ids"] == ["mdf-6mm-snijden-co2-80w"]

    # And asking again for the one it now has says so, rather than blaming the
    # catalogue: a drawer built from a listing a few seconds old is the normal case,
    # and "we already have that" is the sentence that tells the reader to look again.
    with pytest.raises(LibraryError) as again:
        starter.stage(
            profile(library, bare), tmp_path, ids=["berken-3mm-snijden-co2-80w"]
        )
    assert again.value.code == "library.starter.alreadyHere"


def test_a_row_that_does_not_suit_this_laser_is_never_staged(starter, live_shaped, tmp_path):
    """
    A diode row asked for by id on an 80 W CO2 comes back as missing, not as a preset.

    The drawer only shows what matched, but an id is a string in a request body and the
    old importer took any of them: `by_id` came straight off the whole catalogue.
    """
    library, phantom, active, bare = live_shaped

    with pytest.raises(LibraryError) as refused:
        starter.stage(
            profile(library, bare), tmp_path, ids=["acryl-3mm-snijden-diode-10w"]
        )

    assert refused.value.code == "library.starter.nothingSuits"


# ------------------------------------------------------------------ the routes


@pytest.fixture
def client(kernel, tmp_path, catalogue_file):
    server = ApiServer(kernel, library_path=tmp_path / "routes.db")
    server.presetariat.url = catalogue_file.as_uri()
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


@pytest.fixture
def ruida(client):
    """A machine out of the wizard, with the two things the match needs."""
    client.post("/api/machines", json={"info": "ruida-beta", "label": "KH-5030"})
    machine = client.get("/api/library/active-machine").json()
    client.patch(
        f"/api/library/machines/{machine['id']}",
        json={"laser_type": "co2-glass", "power_watt": 80},
    )
    return machine["id"]


def test_the_offer_rides_along_with_the_active_machine(client, ruida):
    """
    One call, not two. The material library asks for the active machine anyway, and a
    second round trip for the offer is a second chance to be out of step with it.
    """
    machine = client.get("/api/library/active-machine").json()

    assert machine["starter"]["state"] == "nothing"
    assert machine["starter"]["coverage"]["mine"] == 0
    assert client.get("/api/library/starter").json()["machine"]["name"] == "KH-5030"


def test_no_machine_active_is_an_answer_and_not_a_refusal(client):
    """
    A fresh install has MeerK40t's lhystudios stand-in and nothing else, and nobody
    chose that. The offer says "nothing to offer" rather than 409: the wizard is the
    surface that speaks up there, and a library window that shows an error on opening
    teaches the reader to ignore errors.
    """
    answer = client.get("/api/library/starter").json()

    assert answer["machine"] is None
    assert answer["needed"] is False


def test_taken_over_settings_land_on_the_machine_you_are_on(client, ruida):
    """
    The live outcome this replaces: 26 imported presets, every one of them on `5030
    CO2`, a profile with no device — because the old window's machine `<select>`
    defaulted to `library.machines[0]`, and `machines()` is `ORDER BY name`, so digits
    sorted first while the engine was on `KH-5030`.

    The staged bundle carries the active profile verbatim, so `import_bundle` matches it
    by name and there is nowhere else for the rows to go.
    """
    staged = client.post("/api/presetariat/stage", json={})
    assert staged.status_code == 200, staged.text
    body = staged.json()
    assert body["contains"]["presets"] == 2

    imported = client.post(
        "/api/library/import",
        json={"bundle": body["bundle"], "import_batch": body["import_batch"]},
    )
    assert imported.status_code == 200, imported.text

    presets = client.get("/api/library/presets").json()
    assert len(presets) == 2
    assert {p["machine_id"] for p in presets} == {ruida}
    # And no second profile was invented for the same laser, which is the other half of
    # the seven-profiles-for-two-devices state.
    assert len(client.get("/api/library/machines").json()) == 1


def test_a_staged_import_can_be_taken_back_in_one_call(client, ruida):
    """
    The state the author is stuck in, undone: 26 imports, 14 unwanted materials, no way
    back. The materials the batch created go with it; a material something else uses
    stays, and the answer names both lists so the reader can check it.
    """
    body = client.post("/api/presetariat/stage", json={}).json()
    client.post(
        "/api/library/import",
        json={"bundle": body["bundle"], "import_batch": body["import_batch"]},
    )
    assert len(client.get("/api/library/materials").json()) == 2

    undone = client.delete(f"/api/library/imports/{body['import_batch']}")

    assert undone.status_code == 200, undone.text
    assert undone.json()["presets"] == 2
    assert client.get("/api/library/presets").json() == []
    assert client.get("/api/library/materials").json() == []


def test_the_offer_goes_away_when_it_is_waved_away(client, ruida):
    """
    Through the route the card actually presses, so that the write and the read agree.
    A card that reappears after dismissal is the reason this column exists.
    """
    assert client.post("/api/library/starter/dismiss").json()["needed"] is False
    assert client.get("/api/library/starter").json()["needed"] is False
    assert (
        client.get("/api/library/active-machine").json()["starter_state"] == "dismissed"
    )


def test_not_sure_about_the_tube_power_goes_through_the_same_door(client, ruida):
    """
    "I don't know what my tube is" is a legitimate answer and it is not a dismissal:
    the offer stays, and the match drops to the kind alone. One route for both, because
    a second one is a second chance for the two to disagree.
    """
    client.patch(f"/api/library/machines/{ruida}", json={"power_watt": None})

    answer = client.post(
        "/api/library/starter/dismiss", json={"state": "power_unknown"}
    ).json()

    assert answer["needed"] is True
    assert answer["state"] == "nothing"
    listing = client.get(f"/api/presetariat?machine_id={ruida}").json()
    assert listing["matched_on"] == "kind"
    # Kind alone, so the 80 W CO2 rows come through and the 10 W diode does not: an
    # unknown wattage is not an unknown laser.
    assert listing["count"] == 2
    assert all(p["power_unmatched"] for p in listing["presets"])
