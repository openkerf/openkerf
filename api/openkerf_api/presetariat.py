"""
De gedeelde presetcatalogus (`openkerf/presetariat`).

Fetching, filtering on what your machine is, and importing into your own library. The other
way round you can offer a preset of your own.

Three things here are deliberate:

1. **A preset from the catalogue is a starting point, not a setting.** Machines differ; a
   two-year-old tube does not achieve what it achieved when new. So the provenance travels
   along (`testraster` weighs more than `handmatig`) and we always import with source
   `geimporteerd`, never as `testraster`.
2. **The network must not hold the app up.** The catalogue is stored locally; if the network
   is gone you work with what you had.
3. **Sharing goes through a pre-filled proposal on GitHub, not through a device flow.** That
   last one needs a registered OAuth app that does not exist yet; building a flow nobody can
   complete produces false certainty. This works today, without anybody having to arrange a
   token.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .library import LibraryError

CATALOGUE_URL = (
    "https://raw.githubusercontent.com/openkerf/presetariat/main/presets.json"
)
REPO_URL = "https://github.com/openkerf/presetariat"

CACHE_MAX_AGE = 6 * 3600


class Presetariat:
    def __init__(self, library, cache_path: Path | str, url: str = CATALOGUE_URL):
        self.library = library
        self.cache_path = Path(cache_path)
        self.url = url

    # ------------------------------------------------------------ catalogus

    def catalogue(self, refresh: bool = False) -> dict:
        """
        The catalogue, from the cache unless that is old or a refresh is asked for.

        If the fetch fails we hand back the cache *with* the reason — an empty list would look
        as if no presets existed.
        """
        cached = self._read_cache()
        fresh_enough = (
            cached is not None
            and not refresh
            and time.time() - cached.get("fetched_at", 0) < CACHE_MAX_AGE
        )
        if fresh_enough:
            return {**cached, "stale": False, "error": None}

        try:
            with urllib.request.urlopen(self.url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            if cached is None:
                raise LibraryError(
                    f"The catalogue cannot be fetched and there is no earlier copy: {error}"
                ) from error
            return {**cached, "stale": True, "error": str(error)}

        if not isinstance(payload, dict) or not isinstance(
            payload.get("presets"), list
        ):
            raise LibraryError("The catalogue has an unexpected shape.")

        payload["fetched_at"] = time.time()
        self._write_cache(payload)
        return {**payload, "stale": False, "error": None}

    def browse(
        self,
        machine_id=None,
        material: str | None = None,
        operation: str | None = None,
        refresh: bool = False,
    ) -> dict:
        """
        The catalogue as it is relevant for this machine.

        Filtering on the machine is not cosmetics: letting a 40 W diode's settings loose on a
        100 W CO2 produces nonsense.
        """
        catalogue = self.catalogue(refresh=refresh)
        presets = list(catalogue["presets"])
        profile = self._machine(machine_id) if machine_id is not None else None

        if profile is not None:
            presets = [p for p in presets if self._fits(p, profile)]
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

        presets.sort(key=_confidence, reverse=True)
        return {
            "version": catalogue.get("version"),
            "count": len(presets),
            "total": catalogue.get("count", len(catalogue["presets"])),
            "stale": catalogue.get("stale", False),
            "error": catalogue.get("error"),
            "machine_id": profile["id"] if profile else None,
            "presets": presets,
        }

    def import_presets(self, ids: list[str], machine_id=None) -> dict:
        """
        Gekozen presets in de eigen bibliotheek zetten.

        Already imported before? Then we skip it rather than making a second row: the
        catalogue is a source, not a second library.
        """
        if not ids:
            raise LibraryError("Choose a preset first.")
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

    # ---------------------------------------------------------------- delen

    def as_contribution(self, preset_id: int) -> dict:
        """One of your own presets in the catalogue's format, ready to share."""
        preset = self.library.preset(preset_id)
        machine = None
        if preset.get("machine_id"):
            machine = self._machine(preset["machine_id"])
        if machine is None or not machine.get("power_watt"):
            raise LibraryError(
                "This preset belongs to no machine profile with a power. Without "
                "knowing what kind of machine it was measured on, it is "
                "niemand anders bruikbaar."
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


    # --------------------------------------------------------------- intern

    def _fits(self, preset: dict, profile: dict) -> bool:
        machine = preset.get("machine") or {}
        if machine.get("laser_type") and profile.get("laser_type"):
            if machine["laser_type"] != profile["laser_type"]:
                return False
        watt, mine = machine.get("power_watt"), profile.get("power_watt")
        if watt and mine:
            # Generous: an 80 W preset is still a usable starting point on a 60 W machine,
            # on a 20 W diode it is not.
            if not 0.5 <= float(watt) / float(mine) <= 2.0:
                return False
        return True

    def _machine(self, machine_id) -> dict | None:
        for row in self.library.machines():
            if row["id"] == machine_id:
                return row
        raise LibraryError(f"Machine profile {machine_id} does not exist.")

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
        try:
            return json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None

    def _write_cache(self, payload: dict) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload))
        except OSError:
            # No cache is annoying, not a reason to make the call fail.
            pass


def _confidence(preset: dict) -> tuple:
    """Nagebrand vóór measured, measured vóór gegokt."""
    kind = (preset.get("source") or {}).get("kind")
    return (
        bool(preset.get("verified")),
        {"testraster": 2, "fabrikant": 1}.get(kind, 0),
    )


def _note(preset: dict) -> str:
    source = preset.get("source") or {}
    parts = [f"Uit Presetariat ({source.get('kind', 'onbekend')})"]
    if source.get("by"):
        parts.append(f"door {source['by']}")
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
    Een voorgevuld voorstel op GitHub.

    Without an OAuth app of our own we cannot open a pull request on the user's behalf; this
    does work, without anybody having to arrange a token.
    """
    import urllib.parse

    body = (
        "New preset for the catalogue.\n\n"
        f"Bestand: `presets/{preset['id']}.json`\n\n"
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
