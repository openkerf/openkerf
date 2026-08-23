"""
Whether a setting measured on one laser is offered to another.

Every number in this file was measured — on the live engine's `dev_info` registry
through `GET /api/machines/catalog` on :8091, and on the user's own 204 KB library.
"""

import pytest

from openkerf_api.library import Library
from openkerf_api.machines import MachineManager
from openkerf_api.matching import (
    BAND_HIGH,
    BAND_LOW,
    coverage,
    fits,
    laser_kind_for,
    power_match,
)

#: The whole live `dev_info` registry, as (source, family, how many) — captured from
#: `GET /api/machines/catalog` on :8091, 46 entries in nine distinct shapes. The test
#: kernel in `conftest.py` boots two plugins and offers two entries, so the registry
#: this rule actually meets cannot be reached from a test; this table is the registry,
#: written down. Its own shape is checked against the kernel below, so a change to the
#: `catalog()` contract still fails something.
LIVE_REGISTRY = [
    # (key prefix,          source,      family,                  count)
    ("g3v8", "Older CO2", "Newly CO2-Laser", 30),
    ("kseries", "co2", "K-Series CO2-Laser", 5),
    ("balor-co2", "co2", "Generic CO2-Laser", 1),
    ("diode", "diode", "Longer Diode-Laser", 3),
    ("balor-fiber", "fiber", "Generic Fibre-Laser", 2),
    ("balor-uv", "uv", "Generic UV-Laser", 1),
    # `generic` says nothing, so the family has to. One of these two sits in
    # `Generic Diode-Laser` and is a diode; the other is the bare word `Generic`.
    ("grbl-generic", "generic", "Generic Diode-Laser", 1),
    ("grbl-fluidnc", "generic", "Generic", 1),
    # Two entries carry no `source` key at all.
    ("moshi-co2", None, "Generic CO2-Laser", 1),
    ("g3v8-jinan-jinweik", None, "Newly CO2-Laser", 1),
]


@pytest.fixture
def registry():
    """The live registry rebuilt into the shape `MachineManager.catalog()` returns."""
    families: dict[str, list] = {}
    for prefix, source, family, count in LIVE_REGISTRY:
        for n in range(count):
            defaults = {"label": prefix}
            if source is not None:
                defaults["source"] = source
            families.setdefault(family, []).append(
                {
                    "key": prefix if count == 1 else f"{prefix}-{n}",
                    "family": family,
                    "defaults": defaults,
                }
            )
    return [{"family": f, "machines": m} for f, m in families.items()]


def test_the_laser_kind_comes_from_the_catalogue_entry_and_is_never_asked(registry):
    """
    Every entry in the live registry, sorted into a kind by the two tables alone.

    Measured on :8091, all 46: 38 co2-glass, 4 diode, 2 fiber, 1 uv, 1 unknown. (The
    plan predicted 36 co2-glass because it counted `KIND_BY_SOURCE` only and forgot
    that the two source-less entries reach `co2-glass` through their family name.)

    What this catches is the column default `'co2-glass'` at `library.py:24`, which
    today makes all seven live profiles claim to be CO2 glass tubes — including two
    Grbl rows. A machine that is told it is a CO2 tube is shown CO2 settings, and a
    CO2 setting on a diode is not a starting point.
    """
    kinds = [
        laser_kind_for(entry["key"], registry)
        for group in registry
        for entry in group["machines"]
    ]

    assert len(kinds) == 46
    assert kinds.count("co2-glass") == 38
    assert kinds.count("diode") == 4
    assert kinds.count("fiber") == 2
    assert kinds.count("uv") == 1
    assert kinds.count("unknown") == 1


def test_a_uv_laser_is_not_a_fibre_laser(registry):
    """
    `balor-uv` is `uv` and nothing else.

    An earlier design mapped `uv -> fiber` because both are Balor boards. They are
    not the same machine: a UV source is frequency-tripled solid state at 355 nm and a
    fibre marker is 1064 nm, and the materials that mark under one are not the
    materials that mark under the other. The alias would have handed every fibre
    preset in the catalogue to the one UV owner.
    """
    assert laser_kind_for("balor-uv", registry) == "uv"


def test_a_board_that_drives_anything_is_told_it_drives_anything(registry):
    """
    `grbl-fluidnc` — source `generic`, family `Generic` — is the one entry of 46 that
    lands on `unknown`, and that is the right answer rather than a gap: a FluidNC
    board drives whatever is bolted to it. Its neighbour `grbl-generic` sits in
    `Generic Diode-Laser` and the family name resolves it, which is the whole reason
    `KIND_BY_FAMILY` exists.
    """
    assert laser_kind_for("grbl-fluidnc", registry) == "unknown"
    assert laser_kind_for("grbl-generic", registry) == "diode"
    # Source-less, family says CO2. Both of these would be `unknown` on the source
    # table alone.
    assert laser_kind_for("moshi-co2", registry) == "co2-glass"
    assert laser_kind_for("g3v8-jinan-jinweik", registry) == "co2-glass"


def test_a_machine_the_registry_does_not_know_is_unknown_and_not_a_co2_tube(kernel):
    """
    Run against the real registry the test kernel offers, so the `catalog()` contract
    this rule reads through is exercised and not only the table above.

    The dummy device carries no `source` and sits in the family `Overig`, so it is
    `unknown` — where the database column default would call it a CO2 glass tube. A
    machine we cannot identify must match nothing, because `fits` treats `unknown` as
    a miss in both directions.
    """
    catalog = MachineManager(kernel).catalog()
    keys = {entry["key"] for group in catalog for entry in group["machines"]}
    assert {"ruida-beta", "dummy_info"} <= keys

    assert laser_kind_for("ruida-beta", catalog) == "co2-glass"
    assert laser_kind_for("dummy_info", catalog) == "unknown"
    assert laser_kind_for("a-machine-that-was-removed", catalog) == "unknown"
    assert laser_kind_for(None, catalog) == "unknown"


def test_a_machine_without_a_wattage_is_offered_nothing_unless_it_asks():
    """
    Measured live before this: an 80 W catalogue showed **26 of 26** rows to the
    active `KH-5030`, whose `power_watt` is null. The guard was
    `if watt and mine:` (`presetariat.py:230`) — either side silent skipped the whole
    test — and that is the entire mechanism behind "the machines it names are not the
    machines I defined".

    Nothing now, unless the user says out loud that they do not know their tube, which
    is `kind_only` and a weaker promise that has to be labelled as one.
    """
    catalogue_row = {"laser_type": "co2-glass", "power_watt": 80}
    unspecified = {"laser_type": "co2-glass", "power_watt": None}

    assert fits(catalogue_row, unspecified) is False
    assert fits(catalogue_row, unspecified, kind_only=True) is True
    # And what the row must be labelled as: matched on kind, unmatched on power.
    assert power_match(catalogue_row, unspecified) is None
    # A diode is still refused; kind_only relaxes the wattage, never the kind.
    assert fits({"laser_type": "diode", "power_watt": 10}, unspecified, kind_only=True) is False


def test_an_unknown_kind_is_a_miss_and_not_a_pass():
    """
    Silence on the kind used to pass: the old `_fits` only compared laser types when
    *both* sides named one. So a profile that never said — every profile made before
    the wizard asked — was shown the whole catalogue.
    """
    eighty = {"laser_type": "co2-glass", "power_watt": 80}

    assert fits(eighty, {"laser_type": "unknown", "power_watt": 80}) is False
    assert fits({"laser_type": None, "power_watt": 80}, eighty) is False
    assert fits(None, eighty) is False
    assert fits(eighty, {}) is False


@pytest.mark.parametrize(
    "theirs, mine, shown, why",
    [
        (80, 60, True, "1.33 — a stronger laser's setting under-burns, and that is recoverable"),
        (80, 80, True, "the same laser"),
        (60, 80, True, "0.75 — just inside the floor"),
        (80, 40, False, "2.0 exactly: the far end of under-burning, and the plan's table hides it"),
        (200, 80, False, "2.5 — the plate is wasted, nothing is learned"),
        (40, 80, False, "0.5 — the same percentage into half the tube: char, burn-through, flame"),
    ],
)
def test_the_wattage_band_is_asymmetric(theirs, mine, shown, why):
    """
    The band is 0.7 to 2.0 and not 0.5 to 2.0, because the two directions are not the
    same mistake. Above 1 the setting comes off a stronger laser and under-burns — you
    lose a plate. Below 1 it comes off a weaker one and the same percentage goes into
    a stronger tube, which is char, burn-through and flame.

    The old floor of 0.5 (`presetariat.py:234`) therefore offered a 40 W setting to an
    80 W machine, which is the dangerous half of the range.

    Note the ceiling is exclusive. The plan's prose says "upper bound stays 2.0" and
    its own band table says 80 W on 40 W is hidden; both are only true if 2.0 is the
    first value outside. `BAND_HIGH` is where that is written down.
    """
    origin = {"laser_type": "co2-glass", "power_watt": theirs}
    profile = {"laser_type": "co2-glass", "power_watt": mine}

    assert fits(origin, profile) is shown, why


def test_the_band_edges_are_where_the_constants_say():
    """
    Pin the two boundaries against the constants rather than against literals, so a
    change to the band shows up here as a decision and not as an arithmetic accident.
    """
    mine = {"laser_type": "co2-glass", "power_watt": 100}

    assert fits({"laser_type": "co2-glass", "power_watt": 100 * BAND_LOW}, mine) is True
    assert fits({"laser_type": "co2-glass", "power_watt": 100 * BAND_LOW - 1}, mine) is False
    assert fits({"laser_type": "co2-glass", "power_watt": 100 * BAND_HIGH - 1}, mine) is True
    assert fits({"laser_type": "co2-glass", "power_watt": 100 * BAND_HIGH}, mine) is False


def test_a_zero_watt_machine_is_a_machine_that_did_not_say():
    """
    An empty number field posts 0, not null. Treating that as a real wattage makes
    every ratio infinite and hides the whole catalogue with no explanation, where the
    honest answer is the same as for null: this machine has not said.
    """
    eighty = {"laser_type": "co2-glass", "power_watt": 80}

    assert power_match(eighty, {"laser_type": "co2-glass", "power_watt": 0}) is None
    assert fits(eighty, {"laser_type": "co2-glass", "power_watt": 0}, kind_only=True) is True


# ---------------------------------------------------------------------- coverage


@pytest.fixture
def live_shaped(tmp_path):
    """
    A library shaped like the user's own, in the proportions measured on it.

    Three profiles: the phantom `5030 CO2` with 27 presets and no device, the active
    `KH-5030` with 3, and a bare third one. Four presets and eleven test boards carry
    no machine at all — the fingerprint of the lhystudios-fallback state, measured
    live.
    """
    library = Library(tmp_path / "live.db")
    phantom = library.add_machine(name="5030 CO2", power_watt=60)["id"]
    active = library.add_machine(name="KH-5030", device_path="ruida")["id"]
    bare = library.add_machine(name="A third laser", device_path="grbl")["id"]

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
    for _ in range(3):
        preset(active, materials[0], source="testraster")
    for _ in range(4):
        preset(None, materials[1])
    for _ in range(11):
        library.add_test_grid(
            {
                "machine_id": None,
                "material_id": materials[1],
                "operation": "snijden",
                "speed_min": 8, "speed_max": 20, "speed_steps": 4,
                "power_min": 40, "power_max": 100, "power_steps": 4,
                "cell_mm": 8, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
            },
            cells=[],
        )
    return library, phantom, active, bare


def test_coverage_counts_this_machine_and_neither_the_others_nor_the_strays(live_shaped):
    """
    Measured on the live 204 KB library for the active `KH-5030`: mine 3,
    mine_measured 3, materials_covered 1, materials_known 20, unattached 4,
    unattached_grids 11.

    Two things must not be counted, and both are what make a bare laser look supplied.
    The 27 presets on the phantom profile are somebody else's row; the 4 with
    `machine_id IS NULL` were measured on an unknown machine, and `Library.presets()`
    would hand them over because its WHERE is `(p.machine_id = ? OR p.machine_id IS
    NULL)` (`library.py:518`). That view is why this is raw SQL.
    """
    library, phantom, active, bare = live_shaped

    mine = coverage(library, active)

    assert mine["mine"] == 3
    assert mine["mine_measured"] == 3
    assert mine["materials_covered"] == 1
    assert mine["materials_known"] == 20
    assert mine["unattached"] == 4
    assert mine["unattached_grids"] == 11


def test_a_bare_machine_beside_a_full_library_still_reports_nothing(live_shaped):
    """
    The third profile has nothing of its own while 34 presets sit in the same file.
    If the count leaked across profiles this would read as supplied and the offer of
    starting values would never be made to the machine that needs it.
    """
    library, phantom, active, bare = live_shaped

    assert coverage(library, bare)["mine"] == 0
    # And with no machine active at all — `= NULL` matches nothing, which is the
    # right answer rather than a crash.
    assert coverage(library, None)["mine"] == 0
    assert coverage(library, None)["materials_known"] == 20


def test_settings_taken_from_the_catalogue_do_not_count_as_measured(live_shaped):
    """
    The phantom profile's 27 rows are all `source='geimporteerd'`. They are settings —
    they show in lists and they burn — but nobody burned them here, so the offer must
    still be able to say "starting values, nothing burned" rather than treating the
    profile as covered. That distinction is the `unburned` state on the offer card.
    """
    library, phantom, active, bare = live_shaped

    supplied = coverage(library, phantom)

    assert supplied["mine"] == 27
    assert supplied["mine_measured"] == 0
