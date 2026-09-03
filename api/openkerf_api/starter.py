"""
The one moment this whole feature exists for: a machine that has no settings yet.

Two things live here, and they are two halves of one sentence.

**How much of this library belongs to this machine** — `offer()`. It is the answer to
"does OpenKerf have anything to say to you right now", and it has to be truthful and
cheap at the same time, because the material library asks it every time it opens. Cheap
is easy: six `COUNT(*)`s over a 204 KB file (`matching.coverage`). Truthful is the part
that took the measuring. On the author's live library the active `KH-5030` has three
presets of its own — and *twenty-six* on a phantom profile beside it, four with
`machine_id IS NULL`, eleven boards likewise. Count any of those and a bare machine
looks supplied; `Library.presets()` cannot be reused for exactly that reason (its WHERE
is `p.machine_id = ? OR p.machine_id IS NULL`, `library.py:1073`).

**Getting the starting points in** — `stage()`. It does not write a single row. It
writes a real `.openkerf-lib` into the upload directory and hands it to the import
preview that already exists, which is how this round ends up with *one* importer instead
of two. The one it replaces (`Presetariat.import_presets`) created a material and then
let `add_preset` refuse, so `[good, bad]` left materials written and raised — a
half-import in a library with no way to remove a material. Going through
`import_bundle` inherits the transaction, the material mapping, `_preset_key` conflict
detection, merge-versus-replace and the sheet re-pointing, all of it already written and
tested.

## Why the bundle carries the active profile verbatim

`import_bundle` matches an incoming machine by name and then by device path
(`library.py:1919-1934`). Staging the profile the engine is on right now — its name
*and* its `device_path` — is therefore the mechanism that makes the rows land on the
machine you are working on and nowhere else. Measured on the live library: 26 imported
presets all sit on `5030 CO2`, a profile with no device, because the old importer took
its machine from a `<select>` that opened on whatever sorted first.

## Why every import gets a batch name

`import_batch` is what makes `DELETE /api/library/imports/{batch}` possible, and an
import you can take back in one press is the difference between a starting point and a
junk drawer. The name is minted here and travels back through the preview, so the client
hands it to `/api/library/import` unchanged.
"""

from __future__ import annotations

import json
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .library import (
    BUNDLE_FORMAT,
    BUNDLE_INDEX,
    BUNDLE_SUFFIX,
    BUNDLE_VERSION,
    LibraryError,
)
from .matching import coverage
from .presetariat import _note

#: The first word of every batch name this module hands out. A reader of
#: `DELETE /api/library/imports/presetariat-20260823-141512` can tell what it was
#: without a lookup, and `remove_import_batch` needs nothing but the string.
BATCH_PREFIX = "presetariat"


class Starter:
    def __init__(self, library, presetariat):
        self.library = library
        self.presetariat = presetariat

    # ------------------------------------------------------------- the offer

    def offer(self, profile: dict | None) -> dict:
        """
        Whether to offer this machine a set of starting points, and what to say.

        No catalogue is read and nothing goes over the network: this sits on a route the
        library window calls on opening, and an offer that waits on a 404 is worse than
        no offer. The numbers below are the whole basis for the decision, and they are
        also the sentence — "one of your twenty materials has a setting for this
        machine" is the fact the reader recognises, so it is handed out rather than
        boiled down to a boolean.

        `state` is computed here and not only in the interface, because the two
        refusals on `stage()` — no kind, no wattage — are the same question asked at the
        moment of writing. One rule, one place, as with `actions.ts` and `jobFase`.
        """
        if profile is None:
            # Nothing is active, so there is no machine to make an offer to. Not a
            # refusal: opening the library with no machine set up yet is normal, and the
            # setup flow is the surface that says so.
            return {
                "machine": None,
                "state": "none",
                "needed": False,
                "coverage": None,
            }

        numbers = coverage(self.library, profile["id"])
        state = self._state(profile, numbers)
        return {
            "machine": {
                "id": profile["id"],
                "name": profile.get("name"),
                "laser_type": profile.get("laser_type") or "unknown",
                "power_watt": profile.get("power_watt"),
                "starter_state": profile.get("starter_state") or "",
            },
            "state": state,
            "needed": state != "none",
            "coverage": numbers,
        }

    def _state(self, profile: dict, numbers: dict) -> str:
        """
        The offer's state, in the order the conditions are tested.

        Dismissal wins over everything. A card that comes back after you waved it away
        is a nag, and this one would come back on every open of the library — which is
        also why the trigger below is `mine == 0` and not a coverage ratio: `1 of 20
        materials covered` is true of the author's library and would be true of it
        forever.

        The plan's table reads "kind or watt unknown, and not `power_unknown`". Taken
        literally that lets a machine whose *kind* is unknown through to the fetch, and
        that fetch matches nothing whatever the wattage says — `unknown` is a miss in
        `matching.fits` on purpose. So the escape hatch covers the wattage, which is
        what it was asked for, and an unknown kind still asks.
        """
        if (profile.get("starter_state") or "") == "dismissed":
            return "none"
        kind = str(profile.get("laser_type") or "unknown")
        knows_watt = bool(profile.get("power_watt")) or (
            profile.get("starter_state") == "power_unknown"
        )
        if numbers["mine"] and not numbers["mine_measured"]:
            # Settings, but every one of them out of a catalogue. Tested *before* the two
            # questions about the machine, because the answer here does not need them: a
            # test grid on this laser is what turns a starting point into a measurement,
            # and asking what kind of tube it is first would be a form standing between
            # the user and the one thing worth doing. The column default used to hide this
            # — every profile claimed to be a CO2 glass tube, so nobody was ever asked —
            # and making that honest is what brought the ordering to light.
            return "unburned"
        if kind == "unknown" or not knows_watt:
            return "askMachine"
        if not numbers["mine"]:
            return "nothing"
        if not numbers["mine_measured"]:
            # Settings, but every one of them out of a catalogue. The answer to that is
            # not another catalogue: it is a test grid on this laser, which is the only
            # thing that turns a starting point into a measurement.
            return "unburned"
        return "none"

    def dismiss(self, profile: dict | None, state: str = "dismissed") -> dict:
        """
        Put the offer away, or record that the tube power is not known.

        Both are the same column, because both are the same fact: what the user has
        already told us about this machine's starting points. `power_unknown` is not a
        dismissal — it keeps the offer alive and drops the wattage half of the match —
        so it is written through the same door rather than through a second one.
        """
        if profile is None:
            # `dismissNoMachine` and not `noMachine`: `stage` refuses the same situation
            # with a different sentence ("nothing to fetch settings for"), and one code
            # answering to two sentences means the interface can only ever translate one
            # of them. Two situations, two codes, one sentence each.
            raise LibraryError(
                "There is no machine active, so there is no offer to put away.",
                code="library.starter.dismissNoMachine",
            )
        # `update_machine` hands the row back, so the offer below is computed on what is
        # now in the database rather than on the copy the caller happened to hold.
        return self.offer(
            self.library.update_machine(profile["id"], {"starter_state": state})
        )

    # ------------------------------------------------------------- the fetch

    def stage(
        self, profile: dict | None, directory, ids: list[str] | None = None
    ) -> dict:
        """
        Write the chosen starting points as a library file, for the import preview.

        Two callers, one rule. With `ids` it is the per-material drawer taking over one
        row; without them it is the offer fetching the set that suits this machine, and
        only then does `notEmpty` apply — the drawer has to keep working on a machine
        that already has settings of its own, which is most machines.

        Nothing is written to the database here. The answer names the file and the
        batch, and `/api/library/import` does the rest.
        """
        if profile is None:
            raise LibraryError(
                "There is no machine active, so there is nothing to fetch presets "
                "for.",
                code="library.starter.noMachine",
            )
        name = str(profile.get("name") or "this machine")
        kind = str(profile.get("laser_type") or "unknown")
        if kind == "unknown":
            raise LibraryError(
                f"OpenKerf does not know what kind of laser {name} is. A CO2 preset "
                "on a diode is not a starting point.",
                code="library.starter.needsKind",
                values={"machine": name},
            )
        if not profile.get("power_watt") and (
            profile.get("starter_state") != "power_unknown"
        ):
            raise LibraryError(
                f"OpenKerf does not know how powerful {name} is, so it cannot tell "
                "which presets would suit it. Fill in the tube power, or say you are "
                "not sure and see everything for this kind of laser.",
                code="library.starter.needsWatt",
                values={"machine": name},
            )

        wanted = [str(i) for i in (ids or []) if str(i)]
        if not wanted:
            mine = coverage(self.library, profile["id"])["mine"]
            if mine:
                raise LibraryError(
                    f"{name} already has {mine} setting(s) of its own. Starting values "
                    "are only offered to a machine that has none.",
                    code="library.starter.notEmpty",
                )

        rows, missing = self._rows(profile, wanted)
        if not rows and wanted and not missing:
            # Every row asked for is already filed under this machine. Its own code,
            # because the answer is "your library is ahead of your screen, look again"
            # and not "the catalogue has nothing for you"; the drawer refreshes on it.
            raise LibraryError(
                f"{name} already carries the setting(s) you picked.",
                code="library.starter.alreadyHere",
            )
        if not rows:
            watt = profile.get("power_watt")
            raise LibraryError(
                "The shared catalogue holds no starting point for "
                f"{f'a {watt:g} W ' if watt else 'a '}{kind} laser yet."
                + (f" Unknown setting(s): {', '.join(missing)}." if missing else ""),
                code="library.starter.nothingSuits",
            )

        # The date so a reader can tell which import it was, and four random characters
        # so two of them cannot share a name. A collision would not just overwrite a
        # file: both imports would carry one batch stamp, and taking back the one you
        # regret would take the other with it.
        batch = (
            f"{BATCH_PREFIX}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            f"-{secrets.token_hex(2)}"
        )
        target = Path(directory) / f"{batch}{BUNDLE_SUFFIX}"
        self._write_bundle(target, profile, rows)
        return {
            "bundle": target.name,
            "import_batch": batch,
            "ids": [row["id"] for row in rows],
            "missing": missing,
        }

    def _rows(self, profile: dict, wanted: list[str]) -> tuple[list[dict], list[str]]:
        """
        The catalogue rows that will go into the bundle.

        `browse` and not `catalogue`, so the match — kind, and wattage unless this
        machine has said it does not know — is the one rule in `matching.py` and not a
        second copy of it here. Rows already taken over are dropped rather than refused:
        the catalogue is a source, not a second library, and a user ticking a row that
        is already in should not get an error for it.

        "Already taken over" means *on this machine*, not anywhere in the library, and
        that difference is measured: all 26 rows of the live catalogue are imported
        already — onto the phantom `5030 CO2` — so `browse`'s library-wide `imported`
        flag would leave the machine the engine is actually on with nothing to be
        offered, which is the complaint rather than the fix. A setting filed under
        another laser is not this laser's setting.

        Without explicit ids the catalogue's own `starter` list decides, when it names
        anything this machine can use. That list is the one lever a maintainer has over
        what a fresh install receives — at most one id per material and operation — and
        ignoring it would hand over the whole catalogue the day it grows past 26 rows.
        """
        found = self.presetariat.browse(machine_id=profile["id"])
        here = self._origins(profile["id"])
        usable = [p for p in found["presets"] if str(p.get("id")) not in here]
        if wanted:
            by_id = {str(p.get("id")): p for p in usable}
            rows = [by_id[i] for i in wanted if i in by_id]
            missing = [i for i in wanted if i not in by_id and i not in here]
            return rows, missing
        curated = self.presetariat.catalogue().get("starter")
        if isinstance(curated, list) and curated:
            names = {str(i) for i in curated}
            pick = [p for p in usable if str(p.get("id")) in names]
            if pick:
                return pick, []
        return usable, []

    def _origins(self, machine_id) -> set[str]:
        """
        Which catalogue rows this machine already carries.

        Filtered on `machine_id` here rather than handed to `Library.presets()`,
        because that view answers `(p.machine_id = ? OR p.machine_id IS NULL)`: a preset
        measured on an unknown machine would otherwise count as this machine's, and a
        row would silently stop being offered.
        """
        return {
            str(preset["origin_id"])
            for preset in self.library.presets()
            if preset.get("machine_id") == machine_id and preset.get("origin_id")
        }

    def _write_bundle(self, target: Path, profile: dict, rows: list[dict]) -> None:
        """
        A real `.openkerf-lib`, built out of catalogue rows.

        The machine block is the active profile verbatim, name and device path, because
        that is what makes `import_bundle` land these rows on this machine (see the
        module docstring). `machine_name` on every preset is not decoration either:
        `_preset_key` (`library.py:2493`) compares by material, thickness, operation and
        *machine name*, so leaving it out would make every row look like a preset for a
        nameless machine and the conflict detection would stop seeing the clash.

        The origin machine travels in `origin_laser_type` and `origin_power_watt`. That
        is the row's honesty: an 80 W value filed under a 60 W laser is a starting point
        and not a measurement, and without those two columns nothing downstream can
        tell the difference — which is precisely how the 26 rows already in the library
        became unaccountable.

        And `origin_by` travels with them, which is not bookkeeping but the licence. The
        catalogue is CC BY 4.0: the credit is a condition of the copy, and a row that
        loses it here can never be passed on lawfully again — nor can anybody see that it
        was lost. Measured before this line existed: a staged bundle carried the origin
        machine and no handle at all.
        """
        materials: dict[str, int] = {}
        presets = []
        for row in rows:
            material = str(row.get("material") or "").strip()
            if material not in materials:
                materials[material] = len(materials) + 1
            origin = row.get("machine") or {}
            presets.append(
                {
                    "id": len(presets) + 1,
                    "material_id": materials[material],
                    "machine_id": 1,
                    "machine_name": profile.get("name"),
                    "thickness_mm": row.get("thickness_mm"),
                    "operation": row.get("operation"),
                    "speed_mm_s": row.get("speed_mm_s"),
                    "power_percent": row.get("power_percent"),
                    "passes": row.get("passes") or 1,
                    "interval_mm": row.get("interval_mm"),
                    "air_assist": row.get("air_assist", True),
                    "focus_offset_mm": row.get("focus_offset_mm") or 0,
                    "source": "geimporteerd",
                    "origin_id": row.get("id"),
                    "origin_laser_type": origin.get("laser_type"),
                    "origin_power_watt": origin.get("power_watt"),
                    "origin_by": row.get("by"),
                    "note": _note(row),
                }
            )
        synonyms = {}
        for row in rows:
            material = str(row.get("material") or "").strip()
            for word in row.get("synonyms") or ():
                synonyms.setdefault(material, []).append(str(word))

        payload = {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # Everything about the machine, including the fields that are empty: this is
            # the profile that is already there, so the import matches it and changes
            # none of them.
            "machines": [{**{k: v for k, v in profile.items() if k != "id"}, "id": 1}],
            "materials": [
                {"id": number, "name": name, "synonyms": synonyms.get(name, [])}
                for name, number in materials.items()
            ],
            "presets": presets,
            "test_grids": [],
            "grid_recipes": [],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                BUNDLE_INDEX,
                json.dumps(payload, indent=1, ensure_ascii=False, default=str),
            )
