"""
Where a layer's settings came from.

Until now the pre-flight derived the provenance from the numbers themselves: look in the
library for a preset with the same speed and the same power, and adopt its source. That
works as long as that combination is unique, and precisely where it matters it is not —
12 mm/s at 65% exists for birch *and* for acrylic. Then it says "measured" above a number
measured on another material.

So we remember the applying itself. Whoever puts a preset on a layer leaves a note here:
which preset, which material, which thickness, which source. That note survives closing the
library, and it is what the pre-flight needs to say "this layer carries a setting for 3 mm
birch, but this sheet is 5 mm acrylic".

The note is a snapshot, not a reference: if the preset changes later, what was put on the
layer stays. And if somebody changes the speed by hand, the note no longer holds — which is
why we record the values with it and keep quiet as soon as they deviate. Better no
provenance than a wrong one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# More generous than a rounding difference, tighter than a deliberate adjustment. The
# engine keeps power in per mille, so 0.1% is the finest step there is.
SPEED_SLACK = 0.01
POWER_SLACK = 0.1


class Provenance:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # ------------------------------------------------------------- opslag

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------ noteren

    def record(self, sheet_id: str | None, operation_id: str | None, preset: dict) -> None:
        """Remember that this preset was put on this layer of this sheet."""
        if not sheet_id or not operation_id:
            return
        data = self._read()
        data.setdefault(sheet_id, {})[operation_id] = {
            "preset_id": preset.get("id"),
            "material_id": preset.get("material_id"),
            "material_name": preset.get("material_name"),
            "thickness_mm": preset.get("thickness_mm"),
            "operation": preset.get("operation"),
            "source": preset.get("source"),
            "machine_id": preset.get("machine_id"),
            "machine_name": preset.get("machine_name"),
            # The values as they landed on the layer: with these we later see whether
            # somebody has turned them by hand.
            "speed_mm_s": preset.get("speed_mm_s"),
            "power_percent": preset.get("power_percent"),
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._write(data)

    def forget_sheet(self, sheet_id: str) -> None:
        """
        Een verwijderd sheet neemt zijn briefjes mee.

        Necessary, not housekeeping: sheet numbers are reused, so without this a new
        "sheet-3" inherits the old one's provenance.
        """
        data = self._read()
        if data.pop(sheet_id, None) is not None:
            self._write(data)

    def clear(self) -> None:
        """
        All the notes gone — on a new project.

        For the same reason as `forget_sheet`: a new project starts at "sheet-1" again, and
        without this its first layer carries yesterday's work's provenance. A setting saying
        it comes from a test grid while nobody applied that preset is worse than no
        provenance.
        """
        self.path.unlink(missing_ok=True)

    # ------------------------------------------------------------ opzoeken

    def lookup(
        self,
        sheet_id: str | None,
        operation_id: str | None,
        speed=None,
        power_percent=None,
    ) -> dict | None:
        """
        This layer's note, if it still holds.

        If the layer now deviates from what the preset put on it, this is no longer that
        preset and we hand back nothing.
        """
        if not sheet_id or not operation_id:
            return None
        entry = self._read().get(sheet_id, {}).get(operation_id)
        if not entry:
            return None
        if not _same(entry.get("speed_mm_s"), speed, SPEED_SLACK):
            return None
        if not _same(entry.get("power_percent"), power_percent, POWER_SLACK):
            return None
        return entry


def _same(a, b, slack) -> bool:
    if a is None or b is None:
        # Without a value to compare against we do not compare; that is no proof of
        # equality, but no reason to throw the note away either.
        return True
    try:
        return abs(float(a) - float(b)) <= slack
    except (TypeError, ValueError):
        return False
