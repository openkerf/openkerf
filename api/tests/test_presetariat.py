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
        listing = client.get("/api/presetariat")
        assert listing.status_code == 200
        assert listing.json()["count"] == 3

        response = client.post(
            "/api/presetariat/import", json={"ids": ["mdf-3mm-snijden-co2-80w"]}
        )
        assert response.status_code == 200
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
