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
5. **What we offer is shaped by the catalogue's own schema, and refused here rather
   than there.** Measured against
   `https://raw.githubusercontent.com/openkerf/presetariat/main/schema/preset.schema.json`
   on 23 August 2026, with `jsonschema` 4.26 outside this venv: every contribution the
   app wrote failed the repository's CI with `'by' is a required property` and
   `'tier' is a required property`, because those two arrived in the schema and never
   arrived here. The schema is `additionalProperties: false`, so a body of ours with one
   extra key fails as hard as one with a field missing — which is why nothing about the
   *state* of a contribution travels inside `preset`, only beside it.

## The three things a contribution may not do

- **It may not claim a tier the app cannot show evidence for.** `measured` means a board
  with a name, on this machine, with an outcome recorded; anything else is a
  `starting_point`, and `_evidence` below says in one word which of the two it is and
  why. The schema agrees on the mechanics — `board` is "Required when the tier is
  measured, and null otherwise" — so the rule is not ours alone.
- **It may not wash a value out of the catalogue back in as evidence.** Measured on a
  throwaway library: an imported 80 W starting point, re-parented to a 60 W profile, came
  out as a brand-new `berkentriplex-3mm-graveren-raster-co2-60w` with
  `source: {"kind": "handmatig"}` and nothing at all saying where those numbers had come
  from. The row knew (`source = 'geimporteerd'`, `origin_id`), and now the contribution
  says so too: `derived_from`, and a tier that stays a starting point.
- **It may not go out unattributed.** `by` is a GitHub handle and the app has never had
  one, so it asks once and remembers it beside the library. CC BY 4.0 is the licence of
  the whole catalogue: the handle is the attribution somebody downstream has to be able
  to give, so a contribution without one is not offerable at all — and saying that before
  the work is better than a refusal from CI afterwards.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .catalogue_schema import BOARD_UID, SUPPORTED_SCHEMA, check_board, check_preset
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

#: What GitHub itself accepts as a handle: letters and digits, single hyphens between
#: them, none at either end, at most thirty-nine characters. Anchored, because a handle
#: with a space in it is not a shorter handle but somebody else's.
#:
#: Stricter than the catalogue's schema on purpose. That pattern is
#: `^[A-Za-z0-9-]{1,39}$`, which passes `-`, `-me` and `a--b`; measured before this, a
#: single hyphen was kept as a handle and written to disk. Such a body clears the
#: repository's CI and still fails the one thing `by` is for — CC BY 4.0 attribution that
#: somebody downstream can follow — because it points at no account on GitHub. A field
#: whose only job is to name a person may not hold something that names nobody.
HANDLE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

#: Where the handle is remembered, beside the library and not inside it. A library is
#: exchangeable (`library.export_bundle`), and who *you* are is not part of a library you
#: hand to a colleague — their contributions would go out under your name.
HANDLE_FILE = "openkerf-contributor.json"

#: How long a cached copy is used without asking the network again.
CACHE_MAX_AGE = 6 * 3600

#: Past this, the copy on disk is old enough that the interface should say when it is
#: from rather than merely that it is stale. Measured on the live install: the cache
#: was written on 13 August, the repository has answered 404 ever since, and nothing
#: anywhere told the user either fact. `stale` alone cannot carry that — it is set
#: whenever one fetch fails, which is a normal thing on a laptop with no network.
CACHE_STALE_AFTER = 30 * 24 * 3600


class Presetariat:
    def __init__(
        self,
        library,
        cache_path: Path | str,
        url: str = CATALOGUE_URL,
        handle_path: Path | str | None = None,
    ):
        self.library = library
        self.cache_path = Path(cache_path)
        self.url = url
        # Derived from the cache by default so that every caller gets the same directory
        # without having to know about a second file.
        self.handle_path = (
            Path(handle_path)
            if handle_path is not None
            else self.cache_path.with_name(HANDLE_FILE)
        )

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

    def handle(self) -> str | None:
        """
        The GitHub handle this installation offers under, or None when nobody has said.

        Read from disk on every call rather than cached: it is asked once in the life of
        an install, the file holds one line, and a cached `None` would outlive the answer
        by the whole session.
        """
        try:
            payload = json.loads(self.handle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        by = payload.get("by") if isinstance(payload, dict) else None
        # An ordinary file in a directory the owner can open, so by the time we read it
        # back it may hold anything. An unusable handle is the same situation as no
        # handle at all: ask, rather than offer somebody's contribution under it.
        return _as_handle(by, quiet=True)

    def remember_handle(self, value) -> str:
        """
        The handle, kept, so that the question is asked once.

        A failed write is refused rather than shrugged off. The whole promise of asking
        is that it happens once; an app that cannot keep that promise has to say so,
        because otherwise the reader answers the same question for ever and never learns
        why.
        """
        handle = _as_handle(value)
        try:
            self.handle_path.parent.mkdir(parents=True, exist_ok=True)
            self.handle_path.write_text(
                json.dumps({"by": handle}, indent=1) + "\n", encoding="utf-8"
            )
        except OSError as error:  # pragma: no cover - a read-only settings directory
            raise LibraryError(
                "Your handle could not be saved on this computer, so it will be asked "
                "for again.",
                code="presetariat.share.handleNotKept",
                values={"reason": str(error)},
            ) from error
        return handle

    def as_contribution(self, preset_id: int) -> dict:
        """
        One of your own presets in the catalogue's format, and what it still needs.

        Reads; writes nothing. `preset` is built only when it would validate against the
        repository's schema, so there is no path here that hands back a body the
        repository's CI would refuse — without a handle there is no `by`, and a
        contribution without `by` is not a contribution. Everything about the *state* of
        the offer travels beside `preset` and never inside it: the schema is
        `additionalProperties: false`, so one extra key of ours fails as hard as one
        missing field of theirs.
        """
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
        kind = machine.get("laser_type")
        if not kind or kind == "unknown":
            # `unknown` is the column's default (`library.py:30`) and it means nobody has
            # been asked yet. Before this check the machine block claimed whatever was
            # there and `_slug` fell back to `co2` regardless, so a contribution from an
            # undescribed machine went out with `co2` in its file name — a claim about
            # somebody's optics that nobody made.
            raise LibraryError(
                "This setting belongs to a machine whose kind of laser is not recorded, "
                "and a CO2 setting is not a starting point for a diode.",
                code="presetariat.share.noKind",
            )

        # `material` carries `minLength: 2` in the catalogue's schema and nothing at all
        # here: the library refuses only an empty name (`library.add_material`). Measured
        # against the schema as fetched, a material called "A" produced `material: 'A' is
        # too short` — a CI failure for a reason nobody had mentioned. It is asked here
        # rather than in `_within_the_schema` because it is a fact about the row, like the
        # two above, and those are all said before the reader is asked for a handle.
        if len(str(preset["material_name"] or "").strip()) < 2:
            raise LibraryError(
                "The catalogue searches on the material name, so it needs at least two "
                "characters; rename this material before offering its settings.",
                code="presetariat.share.materialNameTooShort",
                values={"material": str(preset["material_name"] or "")},
            )

        handle = self.handle()
        evidence = self._evidence(preset)
        key = _slug(
            preset["material_name"],
            preset.get("thickness_mm"),
            preset["operation"],
            machine,
        )
        body = None
        if handle:
            body = {
                "id": key,
                "material": preset["material_name"],
                # The other names this board goes by. The catalogue searches on them, so
                # a library that knows "birch plywood" is a "Berkentriplex" should hand
                # that on rather than make the next reader look for it.
                "synonyms": self._synonyms(preset["material_id"]),
                "thickness_mm": preset.get("thickness_mm"),
                "operation": preset["operation"],
                "machine": {
                    "laser_type": kind,
                    "power_watt": machine["power_watt"],
                    # `or None` because a lens of zero millimetres is a blank field and
                    # not a lens. The machine form takes it (`library._number(...,
                    # optional=True)` bounds nothing), the catalogue's schema refuses it
                    # (`lens_mm`, `exclusiveMinimum: 0`) — measured against the schema as
                    # fetched: "0.0 is less than or equal to the minimum of 0" — and
                    # `[number, null]` is what that schema calls "not recorded". So the
                    # blank goes over as a blank rather than as a claim about optics that
                    # do not exist.
                    "lens_mm": machine.get("lens_mm") or None,
                },
                "speed_mm_s": preset["speed_mm_s"],
                "power_percent": preset["power_percent"],
                "passes": int(preset.get("passes") or 1),
                "air_assist": bool(preset.get("air_assist", True)),
                "focus_offset_mm": preset.get("focus_offset_mm") or 0,
                "note": preset.get("note", ""),
                # `source` is what schema 1 had, and it stays because a reader on schema 1
                # has nowhere else to look. The handle goes in it as well as at the top
                # level for the same reason: `_note` below reads the credit out of
                # `source.by`, and CC BY does not care which of the two a reader
                # understands.
                "source": {"kind": _kind_of(preset), "by": handle},
                # Contributing is not verifying, and `verified_by` is a maintainer's
                # field: neither is ours to write.
                "verified": False,
                "tier": evidence["tier"],
                "board": evidence["board"],
                "measured_at": evidence["measured_at"],
                # The day it went *into* the catalogue. Not ours: it has not happened
                # yet, and a date here would be the one claim in the file that nobody
                # could check.
                "catalogued_at": None,
                "result": evidence["result"],
                "derived_from": evidence["derived_from"],
                "by": handle,
            }
            _within_the_schema(body)
        return {
            "preset": body,
            "filename": f"{key}.json",
            "issue_url": _issue_url(body) if body else None,
            "repo_url": REPO_URL,
            "by": handle,
            "ready": body is not None,
            # What is missing, as a token to branch on rather than a sentence to print.
            # One entry today; a list because the next thing the schema asks for should
            # not have to change the shape of this answer.
            "needs": [] if handle else ["handle"],
            "tier": evidence["tier"],
            # Why it is not measured, in one word — `None` when it is. This is beside the
            # body and not in it on purpose: it is about the offer, not about the setting.
            "tier_reason": evidence["tier_reason"],
            "board": evidence["board"],
            "measured_at": evidence["measured_at"],
            "derived_from": evidence["derived_from"],
        }

    def offer(self, preset_id: int, by=None, result=None) -> dict:
        """
        The two answers a contribution needs, taken together, and then the contribution.

        One call because they belong to one press. Asked separately, a reader who fills
        in both and then meets a refusal about the second fills in the first one twice.
        """
        if by is not None:
            self.remember_handle(by)
        if result is not None:
            self._record_outcome(preset_id, result)
        return self.as_contribution(preset_id)

    def _record_outcome(self, preset_id: int, result) -> None:
        """
        What came out of the material, onto the row it came out of.

        Kept rather than passed through, so that the second time this setting is offered
        nobody is asked again — and so that a library handed to a colleague carries its
        own evidence. `charring` is the one field the schema insists on, because a number
        with no outcome beside it is not something anybody can judge; the other two are
        genuinely unknown as often as not, and a guess in them would be worse than a gap.
        """
        if not isinstance(result, dict):
            raise LibraryError(
                "The outcome of a burn is a set of answers, not a single value.",
                code="presetariat.share.badResult",
            )
        if not result.get("charring"):
            raise LibraryError(
                "Say how the edge came out, because a speed and a power with no outcome "
                "beside them is not something anybody else can judge.",
                code="presetariat.share.needsCharring",
            )
        fields = {"result_charring": result["charring"]}
        if result.get("cut_through") is not None:
            fields["result_cut_through"] = bool(result["cut_through"])
        if result.get("kerf_mm") not in (None, ""):
            fields["result_kerf_mm"] = result["kerf_mm"]
        self.library.update_preset(preset_id, **fields)

    def _evidence(self, preset: dict) -> dict:
        """
        What this row can prove, in the catalogue's own fields.

        The order of the tests is the order of the answers, and it is the order of how
        badly the row is placed: a value that came out of the catalogue does not become
        measurable by recording an outcome for it, so `derived` is asked first.

        `board`, `measured_at` and `result` are filled in only on the `measured` branch.
        That is not caution, it is the schema: `board` is "Required when the tier is
        measured, and null otherwise", so a starting point carrying a board would be
        refused by the repository — and rightly, because it would look like evidence.
        """
        origin = str(preset.get("origin_id") or "")
        derived = origin if origin and not origin.startswith("testgrid:") else None
        guess = {
            "tier": "starting_point",
            "board": None,
            "measured_at": None,
            "result": None,
            "derived_from": derived,
        }
        if derived:
            # The laundering this closes, measured on a throwaway library: an imported
            # 80 W starting point, re-parented to a 60 W profile, came out as a fresh
            # `berkentriplex-3mm-graveren-raster-co2-60w` with `source.kind: handmatig`
            # and no trace of the guess it was copied from.
            return {**guess, "tier_reason": "derived"}
        if preset.get("source") != "testraster":
            return {**guess, "tier_reason": "notMeasured"}
        board = f"OK1{preset.get('grid_uid') or ''}"
        if not preset.get("grid_id") or not BOARD_UID.match(board):
            # A board nobody can point at is, to the catalogue, a board that is not
            # there: `board` is the name a maintainer follows to the evidence. Every
            # board is given one on every open (`library._name_the_boards`), so what
            # this really catches is the board that has since been deleted — which is
            # the state the library already calls "the evidence is lost". The prefix is
            # `boardcode.UID_PREFIX`, spelled out rather than imported because that
            # module pulls the whole drawing layer in for three characters;
            # `BOARD_UID` is what keeps the two the same, and
            # `test_the_board_name_we_offer_is_the_one_the_board_carries` pins it.
            return {**guess, "tier_reason": "boardGone"}
        if preset.get("grid_machine_id") != preset.get("machine_id"):
            # Re-parenting a row is one PATCH (`machine_id` is in
            # `library.PRESET_FIELDS`), and it is the same move as the laundering above:
            # the numbers stay and the laser underneath them changes. A measurement
            # belongs to the machine it was burned on and to no other, so from here it
            # is a starting point for the new one.
            return {**guess, "tier_reason": "otherMachine"}
        if not preset.get("result_charring"):
            return {**guess, "tier_reason": "noOutcome"}
        return {
            "tier": "measured",
            "tier_reason": None,
            "board": board,
            "measured_at": _day(preset.get("grid_date")),
            "result": {
                "charring": preset["result_charring"],
                "cut_through": (
                    None
                    if preset.get("result_cut_through") is None
                    else bool(preset["result_cut_through"])
                ),
                "kerf_mm": preset.get("result_kerf_mm"),
            },
            "derived_from": None,
        }

    def _synonyms(self, material_id) -> list[str]:
        for row in self.library.materials():
            if row["id"] == material_id:
                return [str(word) for word in row.get("synonyms") or []]
        return []  # pragma: no cover - a preset always has its material

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


def _as_handle(value, *, quiet: bool = False) -> str | None:
    """
    A GitHub handle out of what somebody typed, or a refusal.

    `@jelle`, `https://github.com/jelle` and `  jelle ` are all the same person, and all
    three are what a reader hands over when asked for a handle — refusing them would be
    pedantry about a prefix whose meaning we know. Anything else is refused rather than
    trimmed into something plausible: a handle is an address, and the attribution CC BY
    asks for is worthless if it points at somebody else.
    """
    text = str(value or "").strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/", "@"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.strip("/").strip()
    if HANDLE.match(text):
        return text
    if quiet:
        return None
    raise LibraryError(
        "A GitHub handle is letters and digits, with single hyphens between them and "
        "none at either end.",
        code="presetariat.share.badHandle",
        values={"handle": str(value or "")},
    )


def _kind_of(preset: dict) -> str:
    """
    The `source.kind` a schema-1 reader will see.

    Three values exist and only two can be ours: `fabrikant` is a manufacturer's sheet
    and nothing in this app records one. An imported row says `handmatig` here and
    carries `derived_from` beside it, because "somebody typed this" is true of the row it
    was copied from as well.
    """
    return "testraster" if preset.get("source") == "testraster" else "handmatig"


def _day(value) -> str | None:
    """
    The date out of `2026-08-23 14:02:11`, or None when there is not one in there.

    This is the day the board's row was made, which is the day it was laid out and
    almost always the day it was burned — the closest thing the library records to
    `measured_at`. The photograph, which is the moment the burn is actually judged, has
    no date of its own in the row.
    """
    text = str(value or "")[:10]
    return text if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else None


#: The bounds the catalogue's schema puts on the numbers a contribution carries, field by
#: field. Every one of these is a number a reader typed into a form of ours, and only one
#: of them is checked anywhere else in this app: `add_preset` bounds `power_percent` and
#: nothing more, so a fibre marker at 5000 mm/s is an ordinary row in this library and a
#: CI failure over there. The refusal belongs on this side, because "the repository
#: refused your proposal" is not something a reader can act on.
SCHEMA_BOUNDS = (
    ("speed_mm_s", 0, 2000),
    ("power_percent", 0, 100),
    ("passes", 1, 20),
    ("thickness_mm", 0, 100),
    ("focus_offset_mm", -50, 50),
)


def _within_the_schema(body: dict) -> None:
    """The numbers, against the bounds the repository will hold them to."""
    for field, low, high in SCHEMA_BOUNDS:
        value = body.get(field)
        if value is None:
            continue
        if not low <= float(value) <= high:
            raise LibraryError(
                f"The catalogue holds {field} between {low} and {high}, and this "
                f"setting says {value}.",
                code="presetariat.share.outOfRange",
                values={"field": field, "value": value, "low": low, "high": high},
            )


def _slug(material: str, thickness, operation: str, machine: dict) -> str:
    import re
    import unicodedata

    def clean(text: str) -> str:
        text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore")
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.decode().lower()))

    # Every kind the catalogue knows, because the fallback used to be `co2` and that
    # made the file name of a uv machine's contribution say `co2` while the machine block
    # beside it said `uv` — one file contradicting itself. `unknown` is refused before
    # this is reached, and a kind we have never heard of now spells itself out.
    kind = {
        "co2-glass": "co2",
        "co2-rf": "co2rf",
        "diode": "diode",
        "fiber": "fiber",
        "uv": "uv",
    }
    parts = [clean(material)]
    if thickness:
        # SQLite hands back 3.0 where the catalogue writes 3; otherwise the same preset
        # would get two different ids.
        number = float(thickness)
        text = str(int(number)) if number == int(number) else str(number)
        parts.append(f"{text.replace('.', 'p')}mm")
    parts.append(clean(operation))
    parts.append(kind.get(machine.get("laser_type")) or clean(machine.get("laser_type")))
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
