"""
The shared preset catalogue (`openkerf/presetariat`).

Fetching, filtering on what your machine is, and importing into your own library. The
other way round you can offer a preset of your own.

Four things here are deliberate:

1. **A preset from the catalogue is a starting point, not a setting.** Machines
   differ; a two-year-old tube does not achieve what it achieved when new. So the
   provenance travels along (`testraster` weighs more than `handmatig`) and we always
   import with source `geimporteerd`, never as `testraster`.
2. **The network must not hold the app up.** The catalogue is stored locally; if the
   network is gone you work with what you had.
3. **The file is assumed to be wrong.** This is the one feature whose input comes from
   strangers, so every entry goes through `catalogue_schema` and a bad one is skipped
   and counted rather than raised. Measured before that existed: one bare string in
   the `presets` array was `AttributeError: 'str' object has no attribute 'get'` on
   the `preset["imported"] = …` line in `browse` below, and the route answered 500 for
   the twenty-five good rows beside it.
4. **Sharing goes through a pre-filled proposal on GitHub, not through a device
   flow.** That last one needs a registered OAuth app that does not exist yet;
   building a flow nobody can complete produces false certainty. This works today,
   without anybody having to arrange a token.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .catalogue_schema import SUPPORTED_SCHEMA, check_board, check_preset
from .library import LibraryError
from .matching import fits, power_match

#: The tagged release asset, not the branch tip.
#:
#: That is what "curated" means mechanically with no server and one maintainer: a
#: human merged it, and then a human decided it was worth shipping. A branch tip has
#: one gate; this has two. It also means the file a user gets is the one the
#: maintainer looked at, not whatever landed on `main` an hour ago.
CATALOGUE_URL = (
    "https://github.com/openkerf/presetariat/releases/latest/download/presets.json"
)
REPO_URL = "https://github.com/openkerf/presetariat"

#: How long a cached copy is used without asking the network again.
CACHE_MAX_AGE = 6 * 3600

#: Past this, the copy on disk is old enough that the interface should say when it is
#: from rather than merely that it is stale. Measured on the live install: the cache
#: was written on 13 August, the repository has answered 404 ever since, and nothing
#: anywhere told the user either fact. `stale` alone cannot carry that — it is set
#: whenever one fetch fails, which is a normal thing on a laptop with no network.
CACHE_STALE_AFTER = 30 * 24 * 3600


class Presetariat:
    def __init__(self, library, cache_path: Path | str, url: str = CATALOGUE_URL):
        self.library = library
        self.cache_path = Path(cache_path)
        self.url = url

    # ----------------------------------------------------------- the catalogue

    def catalogue(self, refresh: bool = False) -> dict:
        """
        The catalogue, from the cache unless that is old or a refresh is asked for.

        If the fetch fails we hand back the cache *with* the reason — an empty list
        would look as if no presets existed.

        Every return path goes through `_present`, including the one that reads the
        cache. That matters more than it looks: the copy on the user's disk was
        written by a client that validated nothing, so trusting it because we once
        wrote it is exactly the assumption this round removes. Validating on read also
        means the cache keeps the entries a *newer* client might understand, rather
        than being quietly pruned to what today's checks accept.
        """
        cached = self._read_cache()
        fresh_enough = (
            cached is not None
            and not refresh
            and time.time() - cached.get("fetched_at", 0) < CACHE_MAX_AGE
        )
        if fresh_enough:
            return self._present(cached, stale=False, error=None)

        try:
            with urllib.request.urlopen(self.url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            if cached is None:
                # The seed we ship, rather than a refusal. The offer this whole feature
                # exists for — "your machine has no settings, shall I fetch some?" — has
                # to work on a laptop with no network and on the day the catalogue has no
                # release yet. Measured while writing this: the repository went public and
                # `releases/latest/download/presets.json` still answered 404, because a
                # maintainer has to merge and tag first. So the catalogue makes the
                # starting points *better*; it does not make them *possible*.
                seed = self._seed()
                if seed is not None:
                    return self._present(seed, stale=True, error=str(error))
                raise _unreachable(error) from error
            return self._present(cached, stale=True, error=str(error))

        if not isinstance(payload, dict) or not isinstance(
            payload.get("presets"), list
        ):
            raise LibraryError(
                "That file does not look like a preset catalogue.",
                code="presetariat.badShape",
            )

        payload["fetched_at"] = time.time()
        self._write_cache(payload)
        return self._present(payload, stale=False, error=None)

    def _seed(self) -> dict | None:
        """
        The starting points that ship inside this package.

        The same 26 entries the catalogue holds today, compiled from the same source by
        the same tool, carrying the same licence and the same per-entry `by` — CC-BY means
        the credit travels or the copy is not licensed. `from_seed` is set so that every
        surface can say which of the two it is offering from: a starting point from the
        app is not a lie, but pretending it came from the shared set would be.
        """
        try:
            payload = json.loads(
                (Path(__file__).parent / "starter_seed.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):  # pragma: no cover - the file is in the package
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("presets"), list):
            return None
        payload["from_seed"] = True
        # No `fetched_at`: it was never fetched. `_present` reads that field for the age it
        # reports, and a seed has no age of its own — it is as old as the app.
        return payload

    def _present(self, payload: dict, *, stale: bool, error: str | None) -> dict:
        """
        One catalogue, checked entry by entry, with the two ages it has.

        A bad *entry* is skipped and counted; only a bad *envelope* is refused. The
        reasons travel back as well as the count, because "two entries were not
        understood" is a bug report a maintainer can act on and "2" is not.
        """
        schema = payload.get("schema_version", 1)
        if isinstance(schema, bool) or not isinstance(schema, (int, float)):
            raise LibraryError(
                "That file does not look like a preset catalogue.",
                code="presetariat.badShape",
            )
        if schema > SUPPORTED_SCHEMA:
            # Read half a catalogue and a field we skipped is a pass we did not burn.
            # This is the first thing that has ever read `schema_version`, which has
            # been written into the cache since the feature shipped.
            raise LibraryError(
                "This catalogue comes from a newer version of OpenKerf. Update first.",
                code="presetariat.tooNew",
            )

        presets, reasons = _keep(payload.get("presets"), check_preset)
        boards, board_reasons = _keep(payload.get("boards"), check_board)
        fetched_at = payload.get("fetched_at") or 0
        return {
            **payload,
            "schema_version": schema,
            "presets": presets,
            "boards": boards,
            # The file's own `count` describes what the maintainer shipped; this one
            # describes what this client can use, and those differ by exactly the
            # rows below.
            "count": len(presets),
            "skipped": len(reasons) + len(board_reasons),
            "skipped_reasons": reasons + board_reasons,
            "fetched_at": fetched_at,
            "very_stale": bool(fetched_at)
            and time.time() - fetched_at > CACHE_STALE_AFTER,
            "stale": stale,
            "error": error,
            # Which of the two this is: the shared catalogue, or the starting points that
            # ship inside the app. Every surface has to be able to say so — a seed is a
            # real answer and passing it off as the shared set is not.
            "from_seed": bool(payload.get("from_seed")),
            # CC-BY travels with the data or the copy is not licensed. The seed and the
            # release asset both carry these; a cache written by an older client may not,
            # and then they are simply absent rather than guessed at.
            "license": payload.get("license"),
            "license_url": payload.get("license_url"),
            "attribution": payload.get("attribution"),
        }

    def browse(
        self,
        machine_id=None,
        material: str | None = None,
        operation: str | None = None,
        refresh: bool = False,
    ) -> dict:
        """
        The catalogue as it is relevant for this machine.

        Filtering on the machine is not cosmetics: letting a 40 W diode's settings
        loose on a 100 W CO2 produces nonsense. The rule itself is in `matching.py`,
        because three other surfaces ask the same question and used to answer it
        differently.

        A profile that has said out loud that it does not know its tube power
        (`starter_state = 'power_unknown'`) matches on the kind alone. Every row then
        comes back with `power_unmatched: true` so the interface can say which promise
        it is making; a row that matched on both is the stronger claim and looks it.
        """
        catalogue = self.catalogue(refresh=refresh)
        presets = list(catalogue["presets"])
        profile = self._machine(machine_id) if machine_id is not None else None
        # `.get` and not `["starter_state"]`: the column arrives with the machine
        # identity work, and this module must open a library from before it.
        kind_only = bool(profile) and profile.get("starter_state") == "power_unknown"

        if profile is not None:
            presets = [
                p
                for p in presets
                if fits(p.get("machine"), profile, kind_only=kind_only)
            ]
        if material:
            needle = material.strip().lower()
            presets = [
                p
                for p in presets
                if needle in str(p.get("material", "")).lower()
                or any(needle in str(s).lower() for s in p.get("synonyms", []))
            ]
        if operation:
            presets = [p for p in presets if p.get("operation") == operation]

        known = self._imported_ids()
        for preset in presets:
            preset["imported"] = preset.get("id") in known
            preset["power_unmatched"] = (
                profile is not None
                and power_match(preset.get("machine"), profile) is None
            )

        presets.sort(key=_confidence, reverse=True)
        return {
            "version": catalogue.get("version"),
            "count": len(presets),
            "total": len(catalogue["presets"]),
            "stale": catalogue.get("stale", False),
            "very_stale": catalogue.get("very_stale", False),
            "fetched_at": catalogue.get("fetched_at") or None,
            "skipped": catalogue.get("skipped", 0),
            "error": catalogue.get("error"),
            # Which of the two this list came from, and under what terms. The window says
            # "the shared catalogue" or "the starting points this app ships with", and
            # CC-BY means the credit has to be able to travel with a row that is kept.
            "from_seed": catalogue.get("from_seed", False),
            "license": catalogue.get("license"),
            "attribution": catalogue.get("attribution"),
            "machine_id": profile["id"] if profile else None,
            # A token for the interface to branch on, not a sentence to print: what
            # promise this list is making, once, rather than inferred from the rows.
            "matched_on": "kind" if kind_only else "kind+power",
            "presets": presets,
        }

    def import_presets(self, ids: list[str], machine_id=None) -> dict:
        """
        Putting the chosen presets into your own library.

        Already imported before? Then we skip it rather than making a second row: the
        catalogue is a source, not a second library.
        """
        if not ids:
            raise LibraryError(
                "Tick at least one setting to take over.",
                code="presetariat.pickOne",
            )
        catalogue = self.catalogue()
        by_id = {p.get("id"): p for p in catalogue["presets"]}
        known = self._imported_ids()

        imported, skipped, missing = [], [], []
        for key in ids:
            if key in known:
                skipped.append(key)
                continue
            preset = by_id.get(key)
            if preset is None:
                missing.append(key)
                continue
            material = self._material_id(preset)
            row = self.library.add_preset(
                material_id=material,
                machine_id=machine_id,
                thickness_mm=preset.get("thickness_mm"),
                operation=preset.get("operation"),
                speed_mm_s=preset.get("speed_mm_s"),
                power_percent=preset.get("power_percent"),
                passes=preset.get("passes", 1),
                air_assist=preset.get("air_assist", True),
                focus_offset_mm=preset.get("focus_offset_mm", 0),
                source="geimporteerd",
                origin_id=key,
                note=_note(preset),
            )
            imported.append(row)
            known.add(key)

        return {
            "imported": imported,
            "skipped": skipped,
            "missing": missing,
        }

    # -------------------------------------------------------------- sharing

    def as_contribution(self, preset_id: int) -> dict:
        """One of your own presets in the catalogue's format, ready to share."""
        preset = self.library.preset(preset_id)
        machine = None
        if preset.get("machine_id"):
            machine = self._machine(preset["machine_id"])
        if machine is None or not machine.get("power_watt"):
            # Half of this refusal used to be Dutch, and `MaterialLibrary.svelte:318`
            # printed it to the screen verbatim in an English interface, for all three
            # of the user's own KH-5030 presets.
            raise LibraryError(
                "This setting belongs to a machine whose tube power is not recorded, "
                "so nobody else can tell whether it applies to theirs.",
                code="presetariat.share.noWatt",
            )

        kind = "testraster" if preset["source"] == "testraster" else "handmatig"
        key = _slug(
            preset["material_name"],
            preset.get("thickness_mm"),
            preset["operation"],
            machine,
        )
        body = {
            "id": key,
            "material": preset["material_name"],
            "synonyms": [],
            "thickness_mm": preset.get("thickness_mm"),
            "operation": preset["operation"],
            "machine": {
                "laser_type": machine.get("laser_type") or "co2-glass",
                "power_watt": machine["power_watt"],
                "lens_mm": machine.get("lens_mm"),
            },
            "speed_mm_s": preset["speed_mm_s"],
            "power_percent": preset["power_percent"],
            "passes": preset.get("passes", 1),
            "air_assist": bool(preset.get("air_assist", True)),
            "focus_offset_mm": preset.get("focus_offset_mm", 0),
            "note": preset.get("note", ""),
            "source": {"kind": kind},
            "verified": False,
        }
        return {
            "preset": body,
            "filename": f"{key}.json",
            "issue_url": _issue_url(body),
            "repo_url": REPO_URL,
        }


    # -------------------------------------------------------------- internals

    def _machine(self, machine_id) -> dict | None:
        for row in self.library.machines():
            if row["id"] == machine_id:
                return row
        raise LibraryError(
            f"Machine profile {machine_id} does not exist.",
            code="presetariat.noSuchMachine",
        )

    def _imported_ids(self) -> set[str]:
        return {
            row["origin_id"]
            for row in self.library.presets()
            if row.get("origin_id")
        }

    def _material_id(self, preset: dict) -> int:
        name = str(preset.get("material") or "").strip()
        for row in self.library.materials():
            if row["name"].lower() == name.lower():
                return row["id"]
            if any(s.lower() == name.lower() for s in row["synonyms"]):
                return row["id"]
        return self.library.add_material(name, preset.get("synonyms") or [])["id"]

    def _read_cache(self) -> dict | None:
        """
        The copy on disk, or None when there is not a usable one.

        The shape check is here and not only on the network path because a cache file
        is an ordinary file in an ordinary directory: it can be truncated by a full
        disk, half-written by a kill, or edited by a curious owner. A bare list in it
        would otherwise reach `cached.get(...)` as an AttributeError on the one path
        whose whole job is to survive things going wrong.
        """
        try:
            payload = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("presets"), list):
            return None
        return payload

    def _write_cache(self, payload: dict) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload))
        except OSError:
            # No cache is annoying, not a reason to make the call fail.
            pass


def _keep(entries, check) -> tuple[list, list]:
    """
    The entries that pass `check`, and a reason for each one that does not.

    A list that is not a list at all counts as no entries and no reasons: an envelope
    saying `"boards": {}` is a shape problem, and the shape of the *presets* array is
    the only one worth refusing the whole file over.
    """
    kept, reasons = [], []
    for entry in entries if isinstance(entries, list) else ():
        why = check(entry)
        if why is None:
            kept.append(entry)
        else:
            reasons.append(why)
    return kept, reasons


def _unreachable(reason) -> LibraryError:
    """
    The refusal for "no catalogue, and no earlier copy either".

    The raw socket error moves into `values` rather than into the sentence. What the
    user saw before was `<urlopen error [Errno 8] nodename nor servname provided…>`
    verbatim, with no code, and that is what every fresh install sees today because
    the repository is private — an untranslatable string that names a DNS failure
    where the actual news is "there is nothing here yet".

    Returned rather than raised, so the call site reads `raise _unreachable(e) from e`
    and keeps both the control flow and the socket error in the traceback — the same
    shape as `refuse()` in `server.py`.
    """
    return LibraryError(
        "The shared catalogue could not be fetched, and there is no earlier copy "
        "on this computer.",
        code="presetariat.unreachable",
        values={"reason": str(reason)},
    )


def _confidence(preset: dict) -> tuple:
    """Re-burned before measured, measured before guessed."""
    kind = (preset.get("source") or {}).get("kind")
    return (
        bool(preset.get("verified")),
        {"testraster": 2, "fabrikant": 1}.get(kind, 0),
    )


def _note(preset: dict) -> str:
    """
    Where these numbers came from, in one line, on the preset itself.

    English, because it is read in the material library and the interface is English.
    The `kind` inside the brackets stays as the catalogue writes it — `testraster`,
    `handmatig`, `fabrikant` are stored values, the same carve-out as `source` in the
    database — and `OPERATION_LABELS`-style translation of those belongs on the
    screen, not in a note we write once.
    """
    source = preset.get("source") or {}
    parts = [f"From the Presetariat ({source.get('kind', 'unknown')})"]
    if source.get("by"):
        parts.append(f"by {source['by']}")
    if preset.get("verified"):
        parts.append("burned again by a second person")
    note = str(preset.get("note") or "").strip()
    return " — ".join([", ".join(parts)] + ([note] if note else []))


def _slug(material: str, thickness, operation: str, machine: dict) -> str:
    import re
    import unicodedata

    def clean(text: str) -> str:
        text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore")
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.decode().lower()))

    kind = {"co2-glass": "co2", "co2-rf": "co2rf", "diode": "diode", "fiber": "fiber"}
    parts = [clean(material)]
    if thickness:
        # SQLite hands back 3.0 where the catalogue writes 3; otherwise the same preset
        # would get two different ids.
        number = float(thickness)
        text = str(int(number)) if number == int(number) else str(number)
        parts.append(f"{text.replace('.', 'p')}mm")
    parts.append(clean(operation))
    parts.append(kind.get(machine.get("laser_type"), "co2"))
    parts.append(f"{int(float(machine['power_watt']))}w")
    return "-".join(p.strip("-") for p in parts if p.strip("-"))


def _issue_url(preset: dict) -> str:
    """
    A pre-filled proposal on GitHub.

    Without an OAuth app of our own we cannot open a pull request on the user's behalf; this
    does work, without anybody having to arrange a token.
    """
    import urllib.parse

    body = (
        "New preset for the catalogue.\n\n"
        f"File: `presets/{preset['id']}.json`\n\n"
        "```json\n" + json.dumps(preset, indent=2, ensure_ascii=False) + "\n```\n"
    )
    query = urllib.parse.urlencode(
        {
            "title": f"Preset: {preset['material']} — {preset['operation']}",
            "body": body,
            "labels": "preset",
        }
    )
    return f"{REPO_URL}/issues/new?{query}"
