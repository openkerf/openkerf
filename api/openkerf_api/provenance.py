"""
Waar de instellingen van een laag vandaan komen.

De pre-flight leidde de herkomst tot nu toe af uit de getallen zelf: zoek in de
bibliotheek een preset met dezelfde snelheid en hetzelfde vermogen, en neem
diens bron over. Dat werkt zolang die combinatie uniek is, en juist waar het
ertoe doet is ze dat niet — 12 mm/s op 65% bestaat voor berken én voor acryl.
Dan staat er "gemeten" boven een getal dat op ander materiaal gemeten is.

Daarom onthouden we het toepassen zelf. Wie een preset op een laag zet, laat
hier een briefje achter: welke preset, welk materiaal, welke dikte, welke bron.
Dat briefje overleeft het sluiten van de bibliotheek, en het is wat de
pre-flight nodig heeft om te zeggen "deze laag draagt een instelling van 3 mm
berken, maar dit vel is 5 mm acryl".

Het briefje is een momentopname, geen verwijzing: verandert de preset later,
dan blijft staan wat er op de laag gezet is. En verandert iemand de snelheid
met de hand, dan klopt het briefje niet meer — daarom noteren we de waarden
erbij en zwijgen we zodra ze afwijken. Liever geen herkomst dan een verkeerde.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Ruimer dan een afrondingsverschil, krapper dan een bewuste bijstelling. De
# engine bewaart vermogen in promille, dus 0,1% is de fijnste stap die er is.
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
            # De waarden zoals ze op de laag terechtkwamen: hiermee zien we
            # later of er met de hand aan gedraaid is.
            "speed_mm_s": preset.get("speed_mm_s"),
            "power_percent": preset.get("power_percent"),
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._write(data)

    def forget_sheet(self, sheet_id: str) -> None:
        """
        Een verwijderd vel neemt zijn briefjes mee.

        Nodig, geen opruimwerk: vel-nummers worden hergebruikt, dus zonder dit
        erft een nieuw "vel-3" de herkomst van het oude.
        """
        data = self._read()
        if data.pop(sheet_id, None) is not None:
            self._write(data)

    def clear(self) -> None:
        """
        Alle briefjes weg — bij een nieuw project.

        Om dezelfde reden als `forget_sheet`: een nieuw project begint weer op
        "vel-1", en zonder dit draagt de eerste laag daarvan de herkomst van
        het werk van gisteren. Een instelling die zegt dat hij uit een testraster
        komt terwijl niemand die preset toepaste, is erger dan geen herkomst.
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
        Het briefje van deze laag, als het nog klopt.

        Wijkt de laag inmiddels af van wat de preset erop zette, dan is dit
        niet meer die preset en geven we niets terug.
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
        # Zonder vergelijkingswaarde vergelijken we niet; dat is geen bewijs
        # van gelijkheid, maar ook geen reden om het briefje weg te gooien.
        return True
    try:
        return abs(float(a) - float(b)) <= slack
    except (TypeError, ValueError):
        return False
