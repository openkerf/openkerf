"""
Whether a setting measured on one laser is a starting point for another.

One module, because four places ask that question today and two of them answer it
wrongly. `Presetariat._fits` filtered the catalogue, the column default
`'co2-glass'` (`library.py:24`) answered it for every profile that never said,
`server.py`'s `orphaned` rule answered a neighbouring one, and the interface answered
it a fourth time by showing everything. Same rule as `actions.ts` and `jobFase` in the
frontend: where more than one surface has to know the same thing, it is written once.

## The kind is derived, never asked

Verified against the live `dev_info` registry on :8091, all 46 entries: `Older CO2`
×30, `co2` ×6, `diode` ×3, `generic` ×2, `fiber` ×2, `uv` ×1, and two entries with no
`source` at all (`moshi-co2`, `g3v8-jinan-jinweik`). There is **no wattage key
anywhere** in any `defaults` block — grepped for `watt` and `power` and got nothing —
which is why the tube power is the one thing the wizard has to ask and the kind is the
one thing it must not.

Running `laser_kind_for` over those 46 gives 38 `co2-glass`, 4 `diode`, 2 `fiber`,
1 `uv` and 1 `unknown`. (The plan predicted 36/4/2/1/1: it counted the source table
only and forgot that the two source-less entries land on `co2-glass` through their
family name. The distribution is pinned in `api/tests/test_matching.py` against the
registry itself, so a change upstream shows up as a failing count rather than as a
diode being told it is a CO2 tube.)

Exactly one entry ends on `unknown`: `grbl-fluidnc`, whose source is `generic` and
whose family is the bare word `Generic`. That is the honest answer — a FluidNC board
drives whatever is bolted to it — and `unknown` filters nothing and says so.

`co2-glass` versus `co2-rf` cannot be told apart from `dev_info` at all, so the
derivation writes `co2-glass` and the wizard shows it prefilled and changeable.

## The band is asymmetric because the consequence is

`ratio = their_watt / my_watt`.

Above 1 the values come off a *stronger* laser: the same percentage puts less energy
in, the cut does not go through, and you have wasted a plate. Below 1 they come off a
*weaker* one: the same percentage puts more energy in, and that is char, burn-through
and flame. The two are not the same mistake, so the band is not symmetric — `0.7` up
to `2.0`, where the old code (`presetariat.py:234`) had `0.5` to `2.0`.

And the old guard `if watt and mine:` skipped the test entirely whenever either side
was NULL, which is the whole mechanism behind the user's complaint that the catalogue
names machines they never defined: measured live, an 80 W catalogue showed 26 of 26
rows to a profile with `power_watt: null`. A machine that has not said how strong it
is now matches nothing — unless it says so on purpose, which is what `kind_only` is.
"""

from __future__ import annotations

#: The `source` value in a `dev_info` entry's defaults, to the laser kind it means.
#: `Older CO2` is upstream's own label for the thirty g3v8 brands and is a string with
#: a space in it, not a slug — copied verbatim rather than normalised, because
#: normalising is how a rename upstream turns into a silent `unknown`.
KIND_BY_SOURCE = {
    "co2": "co2-glass",
    "Older CO2": "co2-glass",
    "diode": "diode",
    "fiber": "fiber",
    "uv": "uv",
}

#: When the source says nothing usable, the family name does. Ordered, and matched as
#: a substring: the live families are `Generic Fibre-Laser`, `Generic Diode-Laser`,
#: `Generic UV-Laser`, `Generic CO2-Laser`, `Newly CO2-Laser`, `K-Series CO2-Laser`,
#: `Longer Diode-Laser`, `Ortur Diode-Laser` and the bare `Generic`. British and
#: American spellings of fibre both appear in the wild, so both are listed.
KIND_BY_FAMILY = (
    ("CO2", "co2-glass"),
    ("Diode", "diode"),
    ("Fibre", "fiber"),
    ("Fiber", "fiber"),
    ("UV", "uv"),
)

#: A setting off a laser this much stronger than yours is still a starting point: it
#: under-burns, which costs a plate. Below `BAND_LOW` it over-burns, which chars,
#: cuts through and catches fire, so the floor is tighter than the ceiling.
BAND_LOW = 0.7
BAND_HIGH = 2.0


def laser_kind_for(info_key: str | None, catalog) -> str:
    """
    Which kind of laser the catalogue entry a machine was created from describes.

    `catalog` is what `MachineManager.catalog()` returns — a list of family groups,
    each with a `machines` list. A flat list of entries is accepted too, because the
    caller that has one entry in hand should not have to wrap it in a fake family.

    Returns one of `catalogue_schema.LASER_KINDS`; `unknown` when the key is not in
    the registry or the registry does not say. `unknown` is a real answer, not a
    failure: `fits()` treats it as a miss in both directions rather than letting a
    CO2 setting through onto a diode on the strength of a shrug.
    """
    entry = _entry(info_key, catalog)
    if entry is None:
        return "unknown"
    source = (entry.get("defaults") or {}).get("source")
    if source in KIND_BY_SOURCE:
        return KIND_BY_SOURCE[source]
    family = str(entry.get("family") or "")
    for needle, kind in KIND_BY_FAMILY:
        if needle in family:
            return kind
    return "unknown"


def fits(origin, profile, kind_only: bool = False) -> bool:
    """
    Whether values measured on `origin` are a starting point for `profile`.

    Both sides are machine descriptions — a mapping with `laser_type` and
    `power_watt`. `origin` is the `machine` block of a catalogue entry, or the
    `origin_*` columns of a local preset; `profile` is a row of `machine_profile`.
    Neither is a preset: the values themselves say nothing about what may use them.

    `kind_only` is the "I don't know what my tube is" answer (`starter_state =
    'power_unknown'`). It matches on the kind and lets every wattage through, which is
    a weaker promise than the default and has to be labelled as one on screen — see
    `power_match` below, which is what tells a row apart from a matched one.
    """
    mine_kind = _kind(profile)
    their_kind = _kind(origin)
    if "unknown" in (mine_kind, their_kind) or mine_kind != their_kind:
        return False
    matched = power_match(origin, profile)
    if matched is None:
        # One of the two does not say. Silence used to pass — `if watt and mine:` at
        # presetariat.py:230 — and that is what showed 26 of 26 rows to a machine
        # nobody had described. It passes now only when the reader asked for it.
        return kind_only
    return matched


def power_match(origin, profile) -> bool | None:
    """
    True inside the band, False outside it, `None` when either side does not say.

    Three answers and not two, because "no" and "nobody knows" are different things
    to put on a row: the first hides it, the second shows it with a caveat.
    """
    theirs = _watt(origin)
    mine = _watt(profile)
    if theirs is None or mine is None:
        return None
    ratio = theirs / mine
    # The ceiling is exclusive. Exactly 2.0 is an 80 W setting on a 40 W machine, and
    # that is the far end of the under-burn side rather than a case worth offering;
    # the plan's own band table asks for it hidden.
    return BAND_LOW <= ratio < BAND_HIGH


#: The counting that decides whether a machine is offered starting values at all.
#: It is one statement rather than six calls so that the six numbers describe the same
#: instant, and it is raw SQL rather than `Library.presets()` because that view's
#: WHERE is `(p.machine_id = ? OR p.machine_id IS NULL)` (`library.py:518`) — it would
#: hand back the four presets measured on an unknown machine as if they were this
#: machine's, and a bare laser would look supplied.
_COVERAGE = """
SELECT (SELECT COUNT(*) FROM preset WHERE machine_id = :m)                    AS mine,
       (SELECT COUNT(*) FROM preset WHERE machine_id = :m
                                      AND source <> 'geimporteerd')           AS mine_measured,
       (SELECT COUNT(DISTINCT material_id) FROM preset WHERE machine_id = :m) AS materials_covered,
       (SELECT COUNT(*) FROM material)                                        AS materials_known,
       (SELECT COUNT(*) FROM preset    WHERE machine_id IS NULL)              AS unattached,
       (SELECT COUNT(*) FROM test_grid WHERE machine_id IS NULL)              AS unattached_grids
"""


def coverage(library, machine_id) -> dict:
    """
    How much of this library belongs to this machine.

    Measured on the live 204 KB file, for the active `KH-5030` (profile 5): mine 3,
    mine_measured 3, materials_covered 1, materials_known 20, unattached 4,
    unattached_grids 11. The 27 presets on the phantom `5030 CO2` profile are not
    counted and must not be — they are the reason the machine the engine is actually
    on looks supplied when it is not.

    `machine_id` may be None (no machine active); `= NULL` matches nothing in SQLite,
    so `mine` is then 0 and the two library-wide numbers still answer.

    `library._connect()` and not `sqlite3.connect(library.path)`: that one method is
    where `row_factory` and `PRAGMA foreign_keys = ON` are set (`library.py:294`), and
    a second connection with its own opinion about either is how two readers of one
    file start disagreeing.
    """
    with library._connect() as db:
        row = db.execute(_COVERAGE, {"m": machine_id}).fetchone()
    return dict(row)


# ------------------------------------------------------------------ the small print


def _entry(info_key: str | None, catalog) -> dict | None:
    if not info_key:
        return None
    for group in catalog or ():
        # A family group carries `machines`; a flat entry carries `key` itself.
        for entry in group.get("machines", (group,)) if isinstance(group, dict) else ():
            if isinstance(entry, dict) and entry.get("key") == info_key:
                return entry
    return None


def _kind(machine) -> str:
    if not isinstance(machine, dict):
        return "unknown"
    return str(machine.get("laser_type") or "unknown")


def _watt(machine) -> float | None:
    """
    The tube power as a number, or None when it is missing, zero or nonsense.

    Zero counts as missing on purpose: it is what an empty number field posts, and a
    zero-watt laser would make every ratio infinite.
    """
    if not isinstance(machine, dict):
        return None
    value = machine.get("power_watt")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
