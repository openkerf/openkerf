"""
Wat een paletkleur eerder deed, per machine.

Decision B2. In LightBurn users know their palette by heart: red is "cutting at 12 mm/s",
blue is "engraving at 300". That works because the colour remembers its speed and power,
across jobs. With us every new layer started blank, so that reflex could not form.

**This is emphatically not a preset.** The difference is the scope, and it is not a play on
words:

| | palet-geheugen | preset |
|---|---|---|
| hangs off | machine + colour | machine + material + thickness |
| comes from | what you last did | a measurement, with provenance |
| says | "this is where you were last time" | "this was burned on, and this came out" |

A preset carries evidence; the palette carries habit. That is why they do not overwrite
each other: applying a preset leaves a note in `provenance.py` and updates the memory here
(because that is what the colour does now), but the other way round a palette value never
gets a provenance. Anybody seeing a number with a provenance may trust that something was
once burned.

The machine belongs with it because speed and power are machine properties. 12 mm/s at 80
watts is a different cut from 12 mm/s at 40 watts, and a memory that mixes those up is worse
than no memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Without an active machine the memory hangs off nothing. We do not throw it away then —
# one key for "no machine chosen yet" is better than a user who loses their settings as soon
# as they connect their laser. With the first real machine it does start over; that is
# honest, because a machineless session's values were measured on nothing.
NO_MACHINE = "no-machine"


def machine_key(profile: dict | None) -> str:
    """The key this machine's memory is stored under."""
    if not profile:
        return NO_MACHINE
    machine_id = profile.get("id")
    if machine_id is not None:
        return f"machine-{machine_id}"
    path = str(profile.get("device_path") or "").strip()
    return f"path-{path}" if path else NO_MACHINE


def normalise(color) -> str | None:
    """`#RRGGBB` in lower case, or nothing when it is not a colour."""
    text = str(color or "").strip().lower()
    if len(text) != 7 or not text.startswith("#"):
        return None
    try:
        int(text[1:], 16)
    except ValueError:
        return None
    return text


class Palette:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # -------------------------------------------------------------- opslag

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------- noteren

    def remember(
        self,
        key: str,
        color,
        speed=None,
        power_percent=None,
        kind: str | None = None,
        machine_name: str | None = None,
    ) -> dict | None:
        """
        Onthoud wat deze kleur op deze machine nu doet.

        Half values are not thrown away but filled in: adjusting only the speed does not
        lose the power that was there.
        """
        kleur = normalise(color)
        if kleur is None:
            return None
        data = self._read()
        machine = data.setdefault(str(key or NO_MACHINE), {})
        entry = dict(machine.get(kleur) or {})
        if speed is not None:
            try:
                entry["speed_mm_s"] = round(float(speed), 3)
            except (TypeError, ValueError):
                pass
        if power_percent is not None:
            try:
                entry["power_percent"] = round(float(power_percent), 1)
            except (TypeError, ValueError):
                pass
        if kind:
            entry["type"] = str(kind).replace("op ", "")
        if machine_name:
            entry["machine_name"] = str(machine_name)
        if not entry:
            return None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        machine[kleur] = entry
        self._write(data)
        return entry

    def forget(self, key: str, color) -> None:
        kleur = normalise(color)
        if kleur is None:
            return
        data = self._read()
        machine = data.get(str(key or NO_MACHINE)) or {}
        if machine.pop(kleur, None) is not None:
            self._write(data)

    # ------------------------------------------------------------ opzoeken

    def recall(self, key: str, color) -> dict | None:
        kleur = normalise(color)
        if kleur is None:
            return None
        return (self._read().get(str(key or NO_MACHINE)) or {}).get(kleur)

    def all(self, key: str) -> dict:
        """Everything this machine has remembered, by colour."""
        machine = self._read().get(str(key or NO_MACHINE)) or {}
        return {k: v for k, v in machine.items() if normalise(k)}
