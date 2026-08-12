"""
Wat een paletkleur eerder deed, per machine.

Besluit B2. In LightBurn kennen gebruikers hun palet uit hun hoofd: rood is
"snijden op 12 mm/s", blauw is "graveren op 300". Dat werkt omdat de kleur zijn
snelheid en vermogen onthoudt, over jobs heen. Bij ons begon elke nieuwe laag
blanco, dus die reflex kon niet ontstaan.

**Dit is nadrukkelijk geen preset.** Het verschil is de reikwijdte, en het is
geen woordenspel:

| | palet-geheugen | preset |
|---|---|---|
| hangt aan | machine + kleur | machine + materiaal + dikte |
| komt van | wat jij het laatst deed | een meting, met herkomst |
| zegt | "hier stond je vorige keer" | "hierop is gebrand, en dit kwam eruit" |

Een preset draagt bewijs; het palet draagt gewoonte. Daarom overschrijven ze
elkaar niet: een preset toepassen laat een briefje achter in `provenance.py` en
werkt hier het geheugen bij (want dat is wat de kleur nu doet), maar andersom
krijgt een palet-waarde nooit een herkomst. Wie een getal met herkomst ziet,
mag erop vertrouwen dat er ooit iets gebrand is.

De machine hoort erbij omdat snelheid en vermogen machine-eigenschappen zijn.
12 mm/s op 80 watt is een andere snede dan 12 mm/s op 40 watt, en een geheugen
dat dat door elkaar haalt is erger dan geen geheugen.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Zonder actieve machine hangt het geheugen nergens aan. We gooien het dan niet
# weg — één sleutel voor "nog geen machine gekozen" is beter dan een gebruiker
# die zijn instellingen kwijtraakt zodra hij zijn laser aansluit. Bij de eerste
# echte machine begint hij wel opnieuw; dat is eerlijk, want de waarden van een
# machineloze sessie zijn op niets gemeten.
GEEN_MACHINE = "geen-machine"


def machine_key(profile: dict | None) -> str:
    """De sleutel waaronder het geheugen van deze machine staat."""
    if not profile:
        return GEEN_MACHINE
    machine_id = profile.get("id")
    if machine_id is not None:
        return f"machine-{machine_id}"
    pad = str(profile.get("device_path") or "").strip()
    return f"pad-{pad}" if pad else GEEN_MACHINE


def normalise(color) -> str | None:
    """`#RRGGBB` in kleine letters, of niets als het geen kleur is."""
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

        Halve waarden worden niet weggegooid maar aangevuld: wie alleen de
        snelheid bijstelt, verliest daarmee niet het vermogen dat er stond.
        """
        kleur = normalise(color)
        if kleur is None:
            return None
        data = self._read()
        machine = data.setdefault(str(key or GEEN_MACHINE), {})
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
        machine = data.get(str(key or GEEN_MACHINE)) or {}
        if machine.pop(kleur, None) is not None:
            self._write(data)

    # ------------------------------------------------------------ opzoeken

    def recall(self, key: str, color) -> dict | None:
        kleur = normalise(color)
        if kleur is None:
            return None
        return (self._read().get(str(key or GEEN_MACHINE)) or {}).get(kleur)

    def all(self, key: str) -> dict:
        """Alles wat deze machine onthouden heeft, op kleur."""
        machine = self._read().get(str(key or GEEN_MACHINE)) or {}
        return {k: v for k, v in machine.items() if normalise(k)}
