"""The shared catalogue: fetching, filtering, importing and offering back."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import Library, LibraryError
from openkerf_api.presetariat import CACHE_STALE_AFTER, Presetariat
from openkerf_api.server import ApiServer

CATALOGUE = {
    "schema_version": 1,
    "version": "abc123",
    "count": 3,
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
            "note": "Startwaarde",
            "source": {"kind": "handmatig"},
            "verified": False,
        },
        {
            "id": "mdf-3mm-snijden-co2-80w",
            "material": "MDF",
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 10,
            "power_percent": 70,
            "source": {"kind": "testraster", "by": "iemand"},
            "verified": True,
        },
        {
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
def shop(tmp_path, catalogue_file):
    library = Library(tmp_path / "lib.db")
    return Presetariat(
        library, tmp_path / "cache.json", url=catalogue_file.as_uri()
    )


@pytest.fixture
def co2(shop):
    return shop.library.add_machine(
        name="5030", laser_type="co2-glass", power_watt=80
    )["id"]


def test_browsing_returns_everything_without_a_machine(shop):
    result = shop.browse()

    assert result["count"] == 3
    assert result["version"] == "abc123"
    assert result["stale"] is False


def test_a_diode_preset_is_hidden_from_a_co2_machine(shop, co2):
    """
    Letting the settings of a 10 W diode loose on an 80 W CO2 gives nonsense, so
    filtering is not cosmetic.
    """
    ids = [p["id"] for p in shop.browse(machine_id=co2)["presets"]]

    assert "acryl-3mm-snijden-diode-10w" not in ids
    assert "mdf-3mm-snijden-co2-80w" in ids


def test_measured_and_verified_presets_come_first(shop):
    presets = shop.browse()["presets"]

    assert presets[0]["id"] == "mdf-3mm-snijden-co2-80w"


def test_searching_matches_synonyms(shop):
    result = shop.browse(material="birch")

    assert [p["id"] for p in result["presets"]] == ["berken-3mm-snijden-co2-80w"]


def test_importing_creates_a_preset_and_its_material(shop, co2):
    result = shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    assert len(result["imported"]) == 1
    preset = shop.library.presets()[0]
    assert preset["material_name"] == "MDF"
    # Never as a test grid: nothing was measured on this machine.
    assert preset["source"] == "geimporteerd"
    assert preset["origin_id"] == "mdf-3mm-snijden-co2-80w"
    assert "testraster" in preset["note"]


def test_importing_twice_does_not_duplicate(shop, co2):
    shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    again = shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    assert again["imported"] == []
    assert again["skipped"] == ["mdf-3mm-snijden-co2-80w"]
    assert len(shop.library.presets()) == 1


def test_browsing_marks_what_is_already_imported(shop, co2):
    shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    presets = {p["id"]: p for p in shop.browse()["presets"]}

    assert presets["mdf-3mm-snijden-co2-80w"]["imported"] is True
    assert presets["berken-3mm-snijden-co2-80w"]["imported"] is False


def test_an_unknown_id_is_reported_not_silently_dropped(shop):
    result = shop.import_presets(["bestaat-niet"])

    assert result["missing"] == ["bestaat-niet"]


def test_a_dead_network_falls_back_to_the_cache(shop, tmp_path):
    shop.browse()  # fills the cache
    shop.url = (tmp_path / "gone.json").as_uri()

    result = shop.browse(refresh=True)

    assert result["count"] == 3
    assert result["stale"] is True
    assert result["error"]


def test_without_cache_a_dead_network_falls_back_on_the_seed(tmp_path, monkeypatch):
    """
    This test used to demand a refusal, and it was right until the app shipped starting
    points of its own. What changed is not the honesty but the floor: with no cache and no
    network there are still the 26 entries inside the package, and answering "no" to "your
    machine has no settings, shall I fetch some?" on a fresh install was the worse lie.

    The refusal is still there for the case that really has nothing — measured by taking
    the seed away.
    """
    shop = Presetariat(
        Library(tmp_path / "l.db"),
        tmp_path / "c.json",
        url=(tmp_path / "gone.json").as_uri(),
    )

    fallen_back = shop.browse()
    assert fallen_back["from_seed"] is True
    assert fallen_back["presets"]

    monkeypatch.setattr(Presetariat, "_seed", lambda self: None)
    with pytest.raises(LibraryError):
        shop.browse()


def test_sharing_produces_a_catalogue_entry(shop, co2):
    material = shop.library.add_material("Berkentriplex")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=co2,
        thickness_mm=3,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
    )
    shop.remember_handle("somebody")

    shared = shop.as_contribution(preset["id"])

    assert shared["preset"]["id"] == "berkentriplex-3mm-snijden-co2-80w"
    assert shared["preset"]["machine"]["power_watt"] == 80
    assert shared["preset"]["source"]["kind"] == "testraster"
    # Contributing is not verifying; a second person does that.
    assert shared["preset"]["verified"] is False
    assert shared["filename"] == "berkentriplex-3mm-snijden-co2-80w.json"
    assert shared["issue_url"].startswith("https://github.com/openkerf/presetariat/issues/new?")


def test_sharing_without_a_machine_profile_is_refused(shop):
    """Without knowing what machine it was measured on, it is useless."""
    material = shop.library.add_material("Cardboard")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        operation="snijden",
        speed_mm_s=30,
        power_percent=35,
    )

    with pytest.raises(LibraryError):
        shop.as_contribution(preset["id"])


def test_the_routes_work_end_to_end(kernel, tmp_path, catalogue_file):
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    server.presetariat.url = catalogue_file.as_uri()
    with TestClient(server.build_app()) as client:
        # `stage` fetches for the machine that is active, and asks what kind of laser it
        # is: a CO2 preset on a diode is not a starting point but a scorch mark. The
        # route it replaced never asked, which is part of why it was replaced. So this
        # is a machine set up the way a user sets one up.
        made = client.post("/api/machines", json={"info": "ruida-beta", "label": "5030"})
        assert made.status_code == 201, made.text
        # Reading the library through a route creates the profile for the active
        # machine; that is `_active_profile`, and it is deliberately not created by a
        # write.
        client.get("/api/library/presets")
        profiles = client.get("/api/library/machines").json()
        assert profiles, "no profile for the machine that was just set up"
        profile = profiles[0]
        client.patch(
            f"/api/library/machines/{profile['id']}",
            json={"laser_type": "co2-glass", "power_watt": 80},
        )
        listing = client.get("/api/presetariat")
        assert listing.status_code == 200
        assert listing.json()["count"] == 3

        # The catalogue has no importer of its own: `stage` writes a library file and
        # says what it would do, and `/api/library/import` is the transaction that does
        # it. `POST /api/presetariat/import` was the old way round and is gone — it
        # created the material before it could refuse, so a half-good batch left
        # materials behind and raised.
        staged = client.post(
            "/api/presetariat/stage", json={"ids": ["mdf-3mm-snijden-co2-80w"]}
        )
        assert staged.status_code == 200, staged.text
        body = staged.json()
        done = client.post(
            "/api/library/import",
            json={"bundle": body["bundle"], "import_batch": body.get("import_batch", "")},
        )
        assert done.status_code == 200, done.text
        assert len(client.get("/api/library/presets").json()) == 1


# ------------------------------------------- what comes off the network is a stranger


BAD_CATALOGUE = {
    "schema_version": 2,
    "version": "mixed",
    "count": 5,
    "presets": [
        # The measured crash: `.get` on a bare string, `presetariat.py:114`.
        "berken-3mm-snijden-co2-80w",
        {
            "id": "good-one",
            "material": "MDF",
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 10,
            "power_percent": 70,
            "source": {"kind": "handmatig"},
        },
        # A percentage no controller accepts. Reaches `add_preset`, which refuses it —
        # after `_material_id` has already written the material.
        {
            "id": "shouting",
            "material": "Acrylaat",
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 10,
            "power_percent": 5000,
            "source": {"kind": "handmatig"},
        },
        # A hand-written machine block. Every caller does `machine.get(...)`.
        {
            "id": "shorthand-machine",
            "material": "Berkentriplex",
            "operation": "snijden",
            "machine": "80W",
            "speed_mm_s": 12,
            "power_percent": 65,
            "source": {"kind": "handmatig"},
        },
        {
            "id": "good-two",
            "material": "Karton",
            "operation": "graveren-raster",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 200,
            "power_percent": 20,
            "source": {"kind": "testraster"},
        },
    ],
}


def _shop_on(tmp_path, payload, name="mixed.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return Presetariat(
        Library(tmp_path / f"{name}.db"), tmp_path / f"{name}.cache", url=path.as_uri()
    )


def test_one_bad_entry_does_not_take_the_catalogue_down(tmp_path):
    """
    Three broken rows beside two good ones give two presets and a count of three
    skipped.

    Measured before `catalogue_schema` existed, on exactly this payload:
    `AttributeError: 'str' object has no attribute 'get'` at `presetariat.py:114`,
    which the route answers as a 500. So one malformed row from a repository anybody
    may open a pull request against took the whole feature down — including the good
    rows beside it, which is the opposite of what a catalogue of starting points is
    for.
    """
    shop = _shop_on(tmp_path, BAD_CATALOGUE)

    result = shop.browse()

    assert [p["id"] for p in result["presets"]] == ["good-two", "good-one"]
    assert result["count"] == 2
    assert result["skipped"] == 3
    # The reasons travel too: "2" is not a bug report, "power_percent 5000 is above
    # 100" is.
    reasons = " | ".join(shop.catalogue()["skipped_reasons"])
    assert "not an object but str" in reasons
    assert "5000" in reasons
    assert "machine is str" in reasons


def test_a_bad_row_is_never_offered_for_import_either(tmp_path):
    """
    Skipping has to happen in `catalogue()` and not in `browse()`, or the row is
    invisible in the list and importable by id — and `power_percent: 5000` then
    reaches `add_preset`, which refuses it *after* `_material_id` has written the
    material. That half-write is unrecoverable today, because there is no way to
    remove a material.
    """
    shop = _shop_on(tmp_path, BAD_CATALOGUE)

    result = shop.import_presets(["shouting", "shorthand-machine"])

    assert result["missing"] == ["shouting", "shorthand-machine"]
    assert result["imported"] == []
    assert shop.library.materials() == []


def test_a_catalogue_from_a_newer_openkerf_is_refused_whole(tmp_path):
    """
    `schema_version: 3` is refused with a code, rather than read as far as we
    understand it.

    This is the first thing that has ever read that field. It has been written into
    the cache since the feature shipped and into `test_presetariat.py`'s own fixture,
    and no line of code looked at it. Reading half a newer catalogue is how a field we
    did not know about — "this preset needs two passes" — becomes one pass on
    somebody's plate.
    """
    shop = _shop_on(tmp_path, {**CATALOGUE, "schema_version": 3}, name="future.json")

    with pytest.raises(LibraryError) as refused:
        shop.browse()

    assert refused.value.code == "presetariat.tooNew"


def test_a_file_that_is_not_a_catalogue_is_refused_with_a_code(tmp_path):
    """A shape problem is the one thing that is refused rather than skipped."""
    shop = _shop_on(tmp_path, {"schema_version": 2, "presets": {}}, name="wrong.json")

    with pytest.raises(LibraryError) as refused:
        shop.browse()

    assert refused.value.code == "presetariat.badShape"


def test_nothing_at_all_is_a_sentence_with_a_code_and_the_reason_beside_it(
    tmp_path, monkeypatch
):
    """
    No catalogue and no earlier copy is the state every fresh install is in today,
    because the repository is private and the URL answers 404.

    What the user saw was `<urlopen error [Errno 8] nodename nor servname
    provided…>` verbatim, with no code — an untranslatable string naming a DNS failure
    where the news is "there is nothing here yet". The socket error moves into
    `values` so a log still has it.
    """
    shop = _shop_on(tmp_path, {"presets": []}, name="present.json")
    shop.url = (tmp_path / "does-not-exist.json").as_uri()
    # With the seed in the package this state is no longer reachable on a real install —
    # which is the point of the seed. The refusal still has to be right for the case that
    # genuinely has nothing left, so the seed is taken away here rather than the test.
    monkeypatch.setattr(Presetariat, "_seed", lambda self: None)

    with pytest.raises(LibraryError) as refused:
        shop.browse()

    assert refused.value.code == "presetariat.unreachable"
    assert "no earlier copy" in str(refused.value)
    assert refused.value.values["reason"]


def test_a_copy_a_month_old_says_so_and_not_merely_stale(shop, tmp_path):
    """
    `stale` is set whenever one fetch fails, which is a normal thing on a laptop, so
    it cannot carry "this is from 13 August". Measured on the live install: the cache
    was written on 13 August, the repository has answered 404 ever since, and nothing
    anywhere told the user either fact.

    The flag is what lets the interface name the date through `Intl` instead.
    """
    fresh = shop.catalogue()
    assert fresh["very_stale"] is False
    assert fresh["fetched_at"] > 0

    cached = json.loads((shop.cache_path).read_text())
    cached["fetched_at"] = time.time() - CACHE_STALE_AFTER - 1
    shop.cache_path.write_text(json.dumps(cached))
    shop.url = (tmp_path / "gone.json").as_uri()

    old = shop.catalogue()

    assert old["very_stale"] is True
    assert old["count"] == 3


def test_a_cache_that_is_not_a_catalogue_is_ignored_rather_than_crashed_on(shop):
    """
    A cache file is an ordinary file: a full disk truncates it, a kill half-writes it,
    a curious owner edits it. A bare list in it would reach `cached.get(...)` on the
    one path whose whole job is to survive things going wrong.
    """
    shop.catalogue()
    shop.cache_path.write_text("[]")

    assert shop.catalogue()["count"] == 3


def test_a_machine_that_never_said_how_strong_it_is_sees_nothing(shop):
    """
    Measured live: an 80 W catalogue showed **26 of 26** rows to the active KH-5030,
    whose `power_watt` is null, because `if watt and mine:` (`presetariat.py:230`)
    skipped the whole test when either side was silent.

    Nothing now. That will look like a regression on the day it ships, and it is the
    fix: a machine nobody described cannot be matched to anything.
    """
    nameless = shop.library.add_machine(name="A machine nobody described")["id"]

    assert shop.browse(machine_id=nameless)["count"] == 0


def test_a_machine_that_says_it_does_not_know_sees_the_kind_and_is_told_so(
    shop, monkeypatch
):
    """
    "I don't know what my tube is" is a legitimate answer — `dev_info` carries no
    wattage anywhere, so there is nothing to default from. It matches on the kind and
    every row comes back flagged, because that is a weaker promise than a match on
    both and the interface has to be able to say which one it is making.
    """
    unsure = shop.library.add_machine(name="Not sure", laser_type="co2-glass")
    # `starter_state` is added to the schema by the machine-identity work; this reads
    # the field the way `browse` does, so the test stands before and after that lands.
    rows = [{**unsure, "starter_state": "power_unknown"}]
    monkeypatch.setattr(shop.library, "machines", lambda: rows)

    result = shop.browse(machine_id=unsure["id"])

    assert result["matched_on"] == "kind"
    assert [p["id"] for p in result["presets"]] == [
        "mdf-3mm-snijden-co2-80w",
        "berken-3mm-snijden-co2-80w",
    ]
    assert all(p["power_unmatched"] for p in result["presets"])


def test_a_matched_row_is_not_flagged_as_unmatched(shop, co2):
    """The other half of the flag: an 80 W row on an 80 W machine matched on both."""
    presets = shop.browse(machine_id=co2)["presets"]

    assert presets
    assert not any(p["power_unmatched"] for p in presets)


def test_ticking_nothing_says_what_to_do_and_carries_a_code(shop):
    """`Choose a preset first.` had no code, so it could only ever be English."""
    with pytest.raises(LibraryError) as refused:
        shop.import_presets([])

    assert refused.value.code == "presetariat.pickOne"


def test_the_share_refusal_is_english_and_coded(shop):
    """
    Half of this sentence was Dutch — "…it is niemand anders bruikbaar." — and
    `MaterialLibrary.svelte:318` printed it to the screen verbatim, in an English
    interface, for all three of the user's own KH-5030 presets (that profile's
    `power_watt` is null).
    """
    machine = shop.library.add_machine(name="No wattage recorded")["id"]
    material = shop.library.add_material("Berkentriplex")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=machine,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
    )

    with pytest.raises(LibraryError) as refused:
        shop.as_contribution(preset["id"])

    assert refused.value.code == "presetariat.share.noWatt"
    assert "niemand" not in str(refused.value)


def test_the_note_on_an_imported_preset_is_english(shop, co2):
    """
    Live in 26 rows of the user's library: `Uit Presetariat (handmatig) — door
    presetariat-prefill`, shown in an English material library. The kind in brackets
    stays as the catalogue writes it: `handmatig` and `testraster` are stored values,
    the same carve-out as `preset.source` in the database.
    """
    shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    note = shop.library.presets()[0]["note"]

    assert note.startswith("From the Presetariat (testraster)")
    assert "by iemand" in note
    assert "Uit" not in note and "door" not in note


def test_the_offer_works_with_no_network_and_no_release(tmp_path):
    """
    The catalogue makes the starting points better; it does not make them possible.

    Measured on the day this shipped: the repository went public and
    `releases/latest/download/presets.json` still answered **404**, because a maintainer
    has to merge and tag before a release exists. If a dead URL and an empty cache meant
    a refusal, the one question this whole feature is for — "your machine has no settings,
    shall I fetch some?" — would answer "no" on a fresh install.

    What it must not do is pretend: the answer says `from_seed`, so every surface can say
    which of the two it is offering from.
    """
    from openkerf_api.library import Library
    from openkerf_api.presetariat import Presetariat

    library = Library(tmp_path / "lib.db")
    catalogue = Presetariat(
        library, tmp_path / "cache.json", url="http://127.0.0.1:9/nothing-here.json"
    )

    answer = catalogue.catalogue()

    assert answer["from_seed"] is True
    assert answer["count"] == 26, answer["count"]
    assert answer["stale"] is True and answer["error"]
    # And the licence travels with it, because CC-BY without the credit is not CC-BY.
    assert answer["license"] == "CC-BY-4.0"
    assert answer["attribution"]
    assert all(row.get("by") for row in answer["presets"]), "an entry with no credit"
    # No date, because it was never fetched: an age the app invented would be a lie about
    # how fresh the set is.
    assert answer["fetched_at"] == 0
    assert answer["very_stale"] is False


def test_a_cached_catalogue_still_wins_over_the_seed(tmp_path):
    """
    The seed is the floor, not a preference. Somebody who has fetched the real catalogue
    keeps it when the network goes — otherwise a laptop on a train would silently fall
    back to the values the app shipped with and lose every entry added since.
    """
    import json

    from openkerf_api.library import Library
    from openkerf_api.presetariat import Presetariat

    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "fetched_at": 0,
                "presets": [
                    {
                        "id": "only-one",
                        "material": "Birch plywood",
                        "operation": "snijden",
                        "machine": {"laser_type": "co2-glass", "power_watt": 80},
                        "speed_mm_s": 12,
                        "power_percent": 65,
                    }
                ],
            }
        )
    )
    catalogue = Presetariat(
        Library(tmp_path / "lib.db"), cache, url="http://127.0.0.1:9/nothing.json"
    )

    answer = catalogue.catalogue()

    assert answer["from_seed"] is False
    assert [row["id"] for row in answer["presets"]] == ["only-one"]


# ------------------------------------------------------- what the catalogue demands
#
# Everything in this section is measured against the repository's own schema, fetched
# on 23 August 2026 from
# https://raw.githubusercontent.com/openkerf/presetariat/main/schema/preset.schema.json
# and validated with `jsonschema` 4.26 (installed outside this venv on purpose: the
# engine's install already asks for numpy, Pillow and pyusb, and one wheel for one
# assertion is a wheel every user carries). What that measurement found, on a
# contribution the app wrote that same day:
#
#     <root>: 'by' is a required property
#     <root>: 'tier' is a required property
#
# So every contribution file the app had ever written failed the repository's CI. The
# two sets below are that schema's `required` and its `properties`, and they are here
# rather than in the module because they are somebody else's rules: a copy that is
# allowed to drift is the whole reason this section exists.

REQUIRED = {
    "id",
    "material",
    "operation",
    "machine",
    "speed_mm_s",
    "power_percent",
    "tier",
    "by",
}

#: The schema is `additionalProperties: false`, so this is a ceiling and not a wish
#: list: one key of ours that is not in here fails as hard as one field of theirs that
#: is missing.
ALLOWED = REQUIRED | {
    "synonyms",
    "thickness_mm",
    "passes",
    "air_assist",
    "focus_offset_mm",
    "note",
    "source",
    "verified",
    "board",
    "measured_at",
    "catalogued_at",
    "result",
    "derived_from",
    "verified_by",
}


def _grid_plan(material_id, machine_id, **extra):
    """A board of four squares, the smallest thing `add_test_grid` accepts."""
    return {
        "material_id": material_id,
        "machine_id": machine_id,
        "thickness_mm": 3,
        "operation": "snijden",
        "speed_min": 8, "speed_max": 20, "speed_steps": 2,
        "power_min": 40, "power_max": 100, "power_steps": 2,
        "cell_mm": 8, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
        **extra,
    }


@pytest.fixture
def measured(shop, co2):
    """
    A setting read off a board, the way the photo route makes one.

    Board first, then the preset that points at it with `origin_id`, then the cell
    marked — `server.presets_from_cells` does exactly these three things, and it is the
    only way a `testraster` row is ever created.
    """
    material = shop.library.add_material("Berkentriplex", ["birch plywood"])["id"]
    grid = shop.library.add_test_grid(
        _grid_plan(material, co2),
        [{"row": 0, "column": 0, "speed_mm_s": 12, "power_percent": 65}],
    )
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=co2,
        thickness_mm=3,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
        origin_id=f"testgrid:{grid['id']}",
    )
    shop.library.mark_cell(grid["id"], 0, 0, preset["id"])
    return grid, preset


def test_a_contribution_carries_everything_the_catalogue_requires(shop, measured):
    """
    The gap this round closes, from the other side.

    Measured before it was closed: the body held fourteen keys and neither `by` nor
    `tier` was one of them, so the repository's CI refused every file the app had ever
    written. Both sets are the schema's own; see the note above this section.
    """
    grid, preset = measured
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "light", "cut_through": True})

    body = shop.as_contribution(preset["id"])["preset"]

    assert REQUIRED <= set(body), f"missing required: {sorted(REQUIRED - set(body))}"
    assert set(body) <= ALLOWED, f"the schema would refuse: {sorted(set(body) - ALLOWED)}"
    assert body["by"] == "Jelle-T"
    assert body["tier"] == "measured"
    assert body["board"] == f"OK1{grid['uid']}"
    assert body["result"] == {"charring": "light", "cut_through": True, "kerf_mm": None}
    assert body["synonyms"] == ["birch plywood"]
    # The maintainer's field, and empty because it has not happened.
    assert body["catalogued_at"] is None


def test_nothing_about_the_offer_travels_inside_the_preset(shop, measured):
    """
    `additionalProperties: false` is the trap here.

    Whether a contribution is ready, what it still needs and why it is not measured are
    all facts about the *offer* and would each be a refused key inside the body. So the
    envelope carries them and the body never does — which is also why a new field on the
    envelope cannot break CI.
    """
    _, preset = measured
    shop.remember_handle("Jelle-T")

    report = shop.as_contribution(preset["id"])

    assert {"ready", "needs", "tier_reason", "by"} <= set(report)
    assert not {"ready", "needs", "tier_reason"} & set(report["preset"])


def test_without_a_handle_there_is_nothing_to_offer(shop, measured):
    """
    Better said before the work than by CI afterwards.

    `by` is a GitHub handle and the app had never asked for one, so there is no honest
    body to build: the report says what is missing and hands back no preset and no tab
    to open.
    """
    _, preset = measured

    report = shop.as_contribution(preset["id"])

    assert report["ready"] is False
    assert report["needs"] == ["handle"]
    assert report["preset"] is None
    assert report["issue_url"] is None
    # And it can still say what the offer *would* be, which is what the panel shows.
    assert report["tier"] == "starting_point"
    assert report["tier_reason"] == "noOutcome"


def test_the_handle_is_asked_once(shop, measured, tmp_path):
    """Remembered beside the library, so the second offer of anything never asks."""
    _, preset = measured

    shop.offer(preset["id"], by="Jelle-T")

    assert shop.handle() == "Jelle-T"
    assert (tmp_path / "openkerf-contributor.json").exists()
    assert shop.as_contribution(preset["id"])["ready"] is True


def test_a_pasted_profile_link_is_the_same_person(shop):
    """All three of these are what a reader hands over when asked for a handle."""
    for typed in ("@Jelle-T", "https://github.com/Jelle-T", "  Jelle-T  "):
        assert shop.remember_handle(typed) == "Jelle-T"


def test_a_handle_that_is_not_a_handle_is_refused(shop):
    """
    A handle is an address, so it is refused rather than trimmed into something
    plausible: the attribution CC BY asks for is worthless pointing at somebody else.
    """
    with pytest.raises(LibraryError) as refused:
        shop.remember_handle("Jelle Tigchelaar")

    assert refused.value.code == "presetariat.share.badHandle"
    assert shop.handle() is None


def test_a_handle_of_nothing_but_hyphens_is_not_a_person(shop):
    """
    The catalogue's own pattern is not tight enough to keep this out, so we are.

    `by` in the schema is `^[A-Za-z0-9-]{1,39}$`, which passes `-`, `-me` and `a--b`.
    Measured before this: `remember_handle("-")` returned `'-'` and wrote it to disk, and
    a body carrying it validates against the fetched schema — CI would merge it. It still
    fails the only thing `by` is for, because GitHub has no such account and CC BY 4.0
    attribution that points nowhere cannot be given. GitHub's own rule is the one applied
    here: single hyphens, never at either end.
    """
    for typed in ("-", "-jelle", "jelle-", "a--b", "-" * 5):
        with pytest.raises(LibraryError) as refused:
            shop.remember_handle(typed)
        assert refused.value.code == "presetariat.share.badHandle", typed
    assert shop.handle() is None
    # And the ordinary handle with a hyphen in the middle is untouched.
    assert shop.remember_handle("jelle-t") == "jelle-t"


def test_a_lens_of_zero_goes_over_as_no_lens_at_all(shop, measured):
    """
    A blank field may not become a claim about optics.

    The machine form takes `lens_mm = 0` — `library.update_machine` puts it through
    `_number(..., optional=True)`, which bounds nothing — and the catalogue's schema
    refuses it: measured against the schema as fetched, a body with that value answers
    `machine/lens_mm: 0.0 is less than or equal to the minimum of 0`. Its type is
    `[number, null]` and null is what it calls "not recorded", which is what a zero in
    that field means.
    """
    _, preset = measured
    shop.library.update_machine(preset["machine_id"], {"lens_mm": 0})
    assert shop.library.machines()[0]["lens_mm"] == 0, "the library still takes a zero"

    body = shop.offer(preset["id"], by="jelle-t")["preset"]

    assert body["machine"]["lens_mm"] is None
    # A real lens is passed on as it stands.
    shop.library.update_machine(preset["machine_id"], {"lens_mm": 63.5})
    assert shop.as_contribution(preset["id"])["preset"]["machine"]["lens_mm"] == 63.5


def test_a_material_name_too_short_to_search_on_is_refused_here(shop, co2):
    """
    The schema's one string bound, checked on this side of the network.

    `material` carries `minLength: 2` over there and nothing at all over here: the
    library refuses only an empty name. Measured against the schema as fetched, a
    material called "A" produced `material: 'A' is too short` — a CI failure a reader
    cannot act on, for a reason nobody had told them. `SCHEMA_BOUNDS` beside this covers
    the numbers; this is the string.

    Asked without a handle on purpose: this is a fact about the row, so it is said when
    the panel opens rather than after somebody has typed their handle and pressed.
    """
    material = shop.library.add_material("A")["id"]
    preset = shop.library.add_preset(
        material_id=material, machine_id=co2, thickness_mm=3,
        operation="snijden", speed_mm_s=12, power_percent=65,
    )
    assert shop.handle() is None

    with pytest.raises(LibraryError) as refused:
        shop.as_contribution(preset["id"])

    assert refused.value.code == "presetariat.share.materialNameTooShort"
    assert refused.value.values["material"] == "A"


def test_the_handle_file_is_not_trusted_when_it_is_read_back(shop, tmp_path):
    """
    An ordinary file in a directory the owner can open, so it may hold anything.

    Rubbish in it is the same situation as no handle: ask again, rather than offer
    somebody's work under whatever is in there.
    """
    (tmp_path / "openkerf-contributor.json").write_text('{"by": "not a handle"}')

    assert shop.handle() is None


# ------------------------------------------------- nothing washes back in as evidence


def test_a_setting_that_came_out_of_the_catalogue_says_so(shop, co2):
    """
    The laundering, reproduced and then closed.

    Measured on a throwaway library before this: an imported 80 W starting point,
    re-parented to a 60 W profile, came out as a brand-new
    `berkentriplex-3mm-graveren-raster-co2-60w` with `source: {"kind": "handmatig"}` —
    somebody else's guess, laundered into a fresh entry for a machine nobody had
    measured. The row knew (`source = 'geimporteerd'`, `origin_id`); the contribution
    now says so too.
    """
    sixty = shop.library.add_machine(
        name="Ours", laser_type="co2-glass", power_watt=60
    )["id"]
    shop.import_presets(["berken-3mm-snijden-co2-80w"], machine_id=co2)
    row = shop.library.presets()[0]
    shop.library.update_preset(row["id"], machine_id=sixty)
    shop.remember_handle("Jelle-T")

    report = shop.as_contribution(row["id"])

    assert report["tier"] == "starting_point"
    assert report["tier_reason"] == "derived"
    assert report["preset"]["derived_from"] == "berken-3mm-snijden-co2-80w"
    # The id still names the machine it is filed under, which is the whole point of
    # saying where it came from: 60 W is what this row now claims to be about.
    assert report["preset"]["id"] == "berkentriplex-3mm-snijden-co2-60w"
    assert report["preset"]["board"] is None


def test_an_import_cannot_be_dressed_up_as_a_measurement(shop, co2):
    """
    Not even by recording an outcome for it.

    `derived` is asked before anything else, because a value that came out of the
    catalogue does not become measurable by somebody looking at a piece of wood next to
    it. Reproduced with the outcome written straight onto the row, which is the only way
    to get there at all.
    """
    shop.import_presets(["berken-3mm-snijden-co2-80w"], machine_id=co2)
    row = shop.library.presets()[0]
    shop.library.update_preset(row["id"], result_charring="none", result_cut_through=True)
    shop.remember_handle("Jelle-T")

    report = shop.as_contribution(row["id"])

    assert report["tier"] == "starting_point"
    assert report["tier_reason"] == "derived"
    assert report["preset"]["result"] is None


def test_a_measurement_filed_under_another_laser_is_no_longer_a_measurement(shop, measured):
    """
    The same move as the laundering, one PATCH long.

    `machine_id` is in `library.PRESET_FIELDS`, so re-parenting a measured row is one
    call: the numbers stay and the laser underneath them changes. A measurement belongs
    to the machine it was burned on, so from there it is a starting point.
    """
    _, preset = measured
    other = shop.library.add_machine(
        name="A different one", laser_type="co2-glass", power_watt=60
    )["id"]
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "light"})
    assert shop.as_contribution(preset["id"])["tier"] == "measured"

    shop.library.update_preset(preset["id"], machine_id=other)
    report = shop.as_contribution(preset["id"])

    assert report["tier"] == "starting_point"
    assert report["tier_reason"] == "otherMachine"
    assert report["preset"]["board"] is None


# ------------------------------------------------------- the evidence, and its absence


def test_a_measurement_without_an_outcome_is_offered_as_a_starting_point(shop, measured):
    """
    Silently downgrading it would be the same lie the other way round.

    The board is real, the numbers were read off it, and still nobody wrote down what
    came out of the material — which is the one thing the app cannot work out for
    itself. So the report says which of the two labels it is using and why, and the
    panel can offer to fill the gap.
    """
    _, preset = measured
    shop.remember_handle("Jelle-T")

    report = shop.as_contribution(preset["id"])

    assert report["tier_reason"] == "noOutcome"
    assert report["preset"]["tier"] == "starting_point"
    assert report["preset"]["result"] is None
    assert report["preset"]["measured_at"] is None


def test_the_outcome_is_kept_on_the_row_it_came_out_of(shop, measured):
    """
    Asked once, like the handle — and it travels in a bundle with the board.

    Without keeping it, every offer of the same setting would ask again, and a library
    handed to a colleague would arrive with its boards and photographs and none of the
    judgements read off them.
    """
    _, preset = measured

    shop.offer(
        preset["id"],
        by="Jelle-T",
        result={"charring": "heavy", "cut_through": False, "kerf_mm": 0.22},
    )
    stored = shop.library.preset(preset["id"])

    assert stored["result_charring"] == "heavy"
    assert stored["result_cut_through"] == 0
    assert stored["result_kerf_mm"] == 0.22
    body = shop.as_contribution(preset["id"])["preset"]
    assert body["result"] == {"charring": "heavy", "cut_through": False, "kerf_mm": 0.22}


def test_an_outcome_without_a_word_about_the_edge_is_refused(shop, measured):
    """The schema's own reason: a number with no outcome beside it is unjudgeable."""
    _, preset = measured

    with pytest.raises(LibraryError) as refused:
        shop.offer(preset["id"], by="Jelle-T", result={"kerf_mm": 0.2})

    assert refused.value.code == "presetariat.share.needsCharring"


def test_a_word_the_catalogue_does_not_know_is_refused(shop, measured):
    """`charring` is an enum over there, so it is an enum here."""
    _, preset = measured

    with pytest.raises(LibraryError) as refused:
        shop.offer(preset["id"], by="Jelle-T", result={"charring": "quite a bit"})

    assert refused.value.code == "library.preset.charring"


def test_a_measurement_whose_board_is_gone_is_a_starting_point(shop, measured):
    """
    The state the library already calls "the evidence is lost".

    `board` is the name a maintainer follows to the photograph, so a row that can no
    longer name one has nothing to show — whatever its source column still says.
    """
    grid, preset = measured
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "light"})
    shop.library.remove_test_grid(grid["id"])

    report = shop.as_contribution(preset["id"])

    assert report["tier_reason"] == "boardGone"
    assert report["preset"]["board"] is None


def test_the_board_name_we_offer_is_the_one_the_board_carries(shop, measured):
    """
    `presetariat` spells the prefix out rather than importing `boardcode`, which pulls
    the whole drawing layer in for three characters. This is what keeps the two the
    same, from both ends: the constant, and the pattern the catalogue matches on.
    """
    from openkerf_api.boardcode import UID_PREFIX
    from openkerf_api.catalogue_schema import BOARD_UID

    grid, preset = measured
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "none"})

    board = shop.as_contribution(preset["id"])["preset"]["board"]

    assert board == f"{UID_PREFIX}{grid['uid']}"
    assert BOARD_UID.match(board)


def test_the_day_on_the_offer_is_the_day_of_the_board(shop, measured):
    """
    Not today's date, which is what an offer would otherwise stamp on somebody's burn
    from last month. The board's row is the only date the library keeps about it.
    """
    grid, preset = measured
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "light"})

    body = shop.as_contribution(preset["id"])["preset"]

    assert body["measured_at"] == str(grid["created_at"])[:10]


# ------------------------------------------------------------- the machine underneath


def test_a_machine_of_no_known_kind_cannot_be_shared(shop):
    """
    `unknown` is the column's default, from the moment a device is activated and before
    anybody is asked anything. Before this refusal the file name said `co2` regardless —
    `_slug` fell back to it — so an undescribed machine's contribution made a claim
    about somebody's optics that nobody had made.
    """
    machine = shop.library.add_machine(name="Nobody asked", power_watt=80)["id"]
    material = shop.library.add_material("Berkentriplex")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=machine,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
    )
    shop.remember_handle("Jelle-T")

    with pytest.raises(LibraryError) as refused:
        shop.as_contribution(preset["id"])

    assert refused.value.code == "presetariat.share.noKind"


def test_a_uv_machine_does_not_get_a_co2_file_name(shop):
    """
    The other half of the same bug: `uv` was not in the map, so it fell through to the
    default and one file said `uv` in its machine block and `co2` in its name.
    """
    machine = shop.library.add_machine(name="Marker", laser_type="uv", power_watt=5)["id"]
    material = shop.library.add_material("Anodised aluminium")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=machine,
        operation="markeren",
        speed_mm_s=800,
        power_percent=40,
    )
    shop.remember_handle("Jelle-T")

    body = shop.as_contribution(preset["id"])["preset"]

    assert body["id"] == "anodised-aluminium-markeren-uv-5w"
    assert body["machine"]["laser_type"] == "uv"


def test_a_speed_the_catalogue_will_not_take_is_refused_here(shop):
    """
    `add_preset` bounds `power_percent` and nothing else, so a galvo marker at
    5000 mm/s is an ordinary row in this library and a CI failure over there. The
    schema's ceiling is 2000, and "the repository refused your proposal" is not
    something a reader can act on.
    """
    machine = shop.library.add_machine(
        name="Galvo", laser_type="fiber", power_watt=30
    )["id"]
    material = shop.library.add_material("Stainless steel")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=machine,
        operation="markeren",
        speed_mm_s=5000,
        power_percent=60,
    )
    shop.remember_handle("Jelle-T")

    with pytest.raises(LibraryError) as refused:
        shop.as_contribution(preset["id"])

    assert refused.value.code == "presetariat.share.outOfRange"
    assert refused.value.values["high"] == 2000


def test_the_two_answers_go_over_http_and_the_report_comes_back(kernel, tmp_path, catalogue_file):
    """The panel's two calls, end to end: what is missing, and then the offer."""
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    server.presetariat.url = catalogue_file.as_uri()
    with TestClient(server.build_app()) as client:
        machine = server.library.add_machine(
            name="KH-5030", laser_type="co2-glass", power_watt=80
        )["id"]
        material = client.post(
            "/api/library/materials", json={"name": "Berkentriplex"}
        ).json()["id"]
        preset = client.post(
            "/api/library/presets",
            json={
                "material_id": material,
                "machine_id": machine,
                "thickness_mm": 3,
                "operation": "snijden",
                "speed_mm_s": 12,
                "power_percent": 65,
            },
        ).json()

        before = client.get(f"/api/presetariat/contribution/{preset['id']}")
        assert before.status_code == 200
        assert before.json()["ready"] is False
        assert before.json()["needs"] == ["handle"]

        offered = client.post(
            f"/api/presetariat/contribution/{preset['id']}", json={"by": "@Jelle-T"}
        )
        assert offered.status_code == 200, offered.text
        body = offered.json()["preset"]
        assert body["by"] == "Jelle-T"
        assert body["tier"] == "starting_point"
        assert offered.json()["tier_reason"] == "notMeasured"
        assert REQUIRED <= set(body)


def test_the_outcome_travels_in_a_bundle(shop, measured, tmp_path):
    """
    A library is a file you hand to a colleague, and it carries the boards and the
    photographs. The judgements read off them travel with it, or a restored library can
    no longer offer its own measurements as measurements.
    """
    from openkerf_api.library import Library

    _, preset = measured
    shop.offer(preset["id"], by="Jelle-T", result={"charring": "light", "kerf_mm": 0.18})

    elsewhere = Library(tmp_path / "colleague" / "library.db")
    elsewhere.import_bundle(shop.library.export_bundle("mine"))

    landed = elsewhere.presets()[0]
    assert landed["result_charring"] == "light"
    assert landed["result_kerf_mm"] == 0.18
