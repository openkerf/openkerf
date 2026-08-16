"""
Vellen: meerdere stukken materiaal in één project.

Zoals de platen van een 3D-slicer, met één verschil dat er voor een laser toe
doet: **een vel is een stuk materiaal, geen kopie van het bed.** Het heeft een
eigen maat — vaak kleiner dan het bed — en één materiaal, zodat de presets en
de tijdschatting per vel kloppen.

Elk vel is een **eigen document**. Wisselen betekent: het huidige vel opslaan,
de elementenboom leegmaken, en het andere vel inladen. Dat is bewust gekozen
boven één boom met vel-labels: wat je ziet is dan altijd precies wat er gebrand
wordt. Bij één gedeelde boom hangt dat af van een filter op het moment van
spoolen, en een fout in dat filter kost materiaal — of erger.

De prijs is dat ongedaan maken per vel werkt en dat wisselen even duurt. Dat
weegt niet op tegen per ongeluk het verkeerde vel branden.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .edits import DesignError, _finite, _positive

MAX_SHEETS = 20

DEFAULT_TILING = {
    "enabled": False,
    "margin_mm": 10.0,
    "overlap_mm": 25.0,
    "marker_size_mm": 8.0,
}


class Sheets:
    def __init__(self, kernel, drawing, document, directory: Path | str):
        self.kernel = kernel
        self.drawing = drawing
        self.document = document
        self.directory = Path(directory)
        self._active: str | None = None
        # Of het actieve vel in deze draai al werkelijk op tafel gelegd is.
        # Zie `_materialiseer`.
        self._geladen = False

    # ------------------------------------------------------------- opslag

    @property
    def index_path(self) -> Path:
        return self.directory / "vellen.json"

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            return []
        for sheet in data if isinstance(data, list) else []:
            sheet.setdefault("tiling", dict(DEFAULT_TILING))
        return data if isinstance(data, list) else []

    def _write(self, sheets: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(sheets, indent=1, ensure_ascii=False))

    def _file(self, sheet_id: str) -> Path:
        return self.directory / f"{sheet_id}.svg"

    # ------------------------------------------------------------ toestand

    def state(self) -> dict:
        sheets = self._ensure()
        return {
            "active": self._active,
            "sheets": [
                {**sheet, "active": sheet["id"] == self._active} for sheet in sheets
            ],
        }

    @property
    def active_id(self) -> str | None:
        self._ensure()
        return self._active

    def active(self) -> dict | None:
        """Het vel waarop nu gewerkt wordt — inclusief zijn materiaal."""
        sheets = self._ensure()
        for sheet in sheets:
            if sheet["id"] == self._active:
                return dict(sheet)
        return None

    def _ensure(self) -> list[dict]:
        """
        Er is altijd minstens één vel.

        Dat scheelt een lege toestand die niemand snapt: een project zonder vel
        bestaat niet, net zomin als een laser zonder bed.
        """
        sheets = self._read()
        if not sheets:
            width, height = self._bed()
            sheets = [
                {
                    "id": "vel-1",
                    "name": "Vel 1",
                    "width_mm": width,
                    "height_mm": height,
                    "material_id": None,
                    "thickness_mm": None,
                    "tiling": dict(DEFAULT_TILING),
                }
            ]
            self._write(sheets)
        elif any("thickness_mm" not in sheet for sheet in sheets):
            # Dikte kwam er later bij (besluit B1). Vellen uit een ouder project
            # missen de sleutel; zonder deze regel valt de bovenbalk erover.
            for sheet in sheets:
                sheet.setdefault("thickness_mm", None)
            self._write(sheets)
        if self._active is None or all(s["id"] != self._active for s in sheets):
            self._active = sheets[0]["id"]
        self._materialiseer()
        return sheets

    def _materialiseer(self) -> None:
        """
        Het actieve vel inladen bij de eerste vraag na het opstarten.

        Zonder dit stond de vellenbalk na een herstart op "Vel 1" terwijl het
        canvas leeg was: het bestand lag er wel, maar niemand had het ingeladen.
        Erger dan de lege aanblik was wat er daarna gebeurde — wegwisselen ziet
        een lege boom, leest dat als "de gebruiker heeft dit vel leeggemaakt",
        en gooit `vel-1.svg` weg. Eén klik, alles kwijt.

        Alleen als de boom leeg is: staat er al werk in (herstel na een
        crash, of iets dat vóór de eerste vraag getekend werd), dan wint dat.
        """
        if self._geladen:
            return
        self._geladen = True
        if any(True for _ in self.kernel.elements.elems()):
            return
        if self._active and self._file(self._active).is_file():
            self._load(self._active)

    def _bed(self) -> tuple[float, float]:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)

        def side(name, fallback):
            try:
                return round(float(Length(getattr(device, name)).mm), 1)
            except Exception:
                return fallback

        return side("bedwidth", 500.0), side("bedheight", 300.0)

    def _find(self, sheets, sheet_id):
        for sheet in sheets:
            if sheet["id"] == sheet_id:
                return sheet
        namen = ", ".join(f"'{s['name']}'" for s in sheets) or "geen"
        raise DesignError(
            f"Vel '{sheet_id}' bestaat niet. Beschikbaar: {namen}. Kies er een "
            "uit de vellenbalk boven het canvas."
        )

    # ------------------------------------------------------------ beheren

    def add(
        self,
        name=None,
        width_mm=None,
        height_mm=None,
        material_id=None,
        thickness_mm=None,
    ) -> dict:
        sheets = self._ensure()
        if len(sheets) >= MAX_SHEETS:
            raise DesignError(f"Meer dan {MAX_SHEETS} vellen wordt onoverzichtelijk.")
        bed_width, bed_height = self._bed()
        number = max(
            (int(s["id"].rsplit("-", 1)[-1]) for s in sheets if s["id"][-1].isdigit()),
            default=0,
        )
        # Namen uniek houden: twee dozen achter elkaar leverden anders twee
        # vellen die allebei "Doos 2" heten, en dan weet je niet welke welke is.
        wanted = str(name or f"Vel {number + 1}").strip()[:40]
        taken = {s["name"] for s in sheets}
        unique, suffix = wanted, 2
        while unique in taken:
            unique = f"{wanted} ({suffix})"
            suffix += 1

        sheet = {
            "id": f"vel-{number + 1}",
            "name": unique,
            "width_mm": self._side(width_mm, bed_width, "width_mm"),
            "height_mm": self._side(height_mm, bed_height, "height_mm"),
            "material_id": material_id,
            "thickness_mm": self._thickness(thickness_mm),
            "tiling": dict(DEFAULT_TILING),
        }
        sheets.append(sheet)
        self._write(sheets)
        return self.state()

    def _thickness(self, value):
        """
        De dikte van dit stuk materiaal, of niets.

        Leeg is een geldig antwoord: wie een restje van onbekende dikte in de
        machine legt, moet niet eerst een getal hoeven verzinnen. Een preset
        zonder dikte hoort erbij te kunnen — dwingen zou de bovenbalk in een
        formulier veranderen.
        """
        if value is None or value == "":
            return None
        dikte = _positive(value, "thickness_mm")
        if dikte > 500:
            raise DesignError("Een vel van meer dan 500 mm dik gaat er niet in.")
        return round(dikte, 2)

    def _side(self, value, fallback, label):
        if value is None:
            return fallback
        size = _positive(value, label)
        if not 5 <= size <= 5000:
            raise DesignError(f"{label} moet tussen 5 en 5000 mm liggen.")
        return round(size, 1)

    def _tiling(self, huidig, gevraagd) -> dict:
        """
        De tegelinstellingen van dit vel, gecontroleerd op samenhang.

        Marge, overlap en markergrootte hangen samen: past er geen merk in de
        overlapstrook, dan is er niets om op uit te lijnen. Dat hoort hier te
        stuiten en niet pas bij het branden — daar sta je al met een plaat in
        de machine.
        """
        blok = dict(DEFAULT_TILING)
        blok.update(huidig or {})
        if not isinstance(gevraagd, dict):
            raise DesignError("tiling moet een blokje instellingen zijn.")
        blok["enabled"] = bool(gevraagd.get("enabled", blok["enabled"]))
        for sleutel in ("margin_mm", "overlap_mm", "marker_size_mm"):
            if gevraagd.get(sleutel) is not None:
                blok[sleutel] = round(_positive(gevraagd[sleutel], sleutel), 1)

        speling = 4.0
        if blok["overlap_mm"] < blok["marker_size_mm"] + speling:
            raise DesignError(
                f"Een uitlijnmerk is {blok['marker_size_mm']:g} mm groot en past niet "
                f"in een overlap van {blok['overlap_mm']:g} mm. Maak de overlap "
                f"minstens {blok['marker_size_mm'] + speling:g} mm."
            )
        if blok["margin_mm"] > 100:
            raise DesignError("Een marge van meer dan 100 mm laat geen bed over.")
        return blok

    def update(self, sheet_id: str, **fields) -> dict:
        sheets = self._ensure()
        sheet = self._find(sheets, sheet_id)
        if fields.get("name") is not None:
            name = str(fields["name"]).strip()[:40]
            if not name:
                raise DesignError("Een vel heeft een naam nodig.")
            sheet["name"] = name
        for key in ("width_mm", "height_mm"):
            if fields.get(key) is not None:
                sheet[key] = self._side(fields[key], sheet[key], key)
        if "material_id" in fields:
            sheet["material_id"] = fields["material_id"]
        if "thickness_mm" in fields:
            sheet["thickness_mm"] = self._thickness(fields["thickness_mm"])
        if fields.get("tiling") is not None:
            sheet["tiling"] = self._tiling(sheet.get("tiling"), fields["tiling"])
        self._write(sheets)
        return self.state()

    def remove(self, sheet_id: str) -> dict:
        sheets = self._ensure()
        if len(sheets) == 1:
            raise DesignError("Het laatste vel kan niet weg; een project heeft er één.")
        sheet = self._find(sheets, sheet_id)
        if sheet["id"] == self._active:
            # Eerst weg van het vel dat verdwijnt, anders blijft de inhoud van
            # een verwijderd vel op het canvas staan.
            other = next(s for s in sheets if s["id"] != sheet_id)
            self.activate(other["id"])
            sheets = self._read()
        self._file(sheet_id).unlink(missing_ok=True)
        self._write([s for s in sheets if s["id"] != sheet_id])
        return self.state()

    def reset(self) -> dict:
        """
        Terug naar één leeg vel — wat "nieuw project" met de vellen doet.

        De opgeslagen vellen gaan mee weg. Ze staan naast de database en
        overleven anders het nieuwe project: je begint dan schoon en vindt in
        de vellenbalk nog de dozen van gisteren.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob("*.svg"):
            old.unlink(missing_ok=True)
        self.index_path.unlink(missing_ok=True)
        self._active = None
        # Er valt niets in te laden en de boom is net geleegd; zonder dit zou
        # `_ensure` het net weggegooide vel alsnog van schijf willen halen.
        self._geladen = True
        return self.state()

    # ------------------------------------------------------------ wisselen

    def activate(self, sheet_id: str) -> dict:
        sheets = self._ensure()
        sheet = self._find(sheets, sheet_id)
        if sheet["id"] == self._active:
            return self.state()

        self.save_active()
        self._load(sheet["id"])
        self._active = sheet["id"]
        return self.state()

    def save_active(self) -> None:
        """Het huidige vel wegschrijven. Gebeurt bij elke wissel en bij opslaan."""
        if self._active is None:
            return
        target = self._file(self._active)
        self.directory.mkdir(parents=True, exist_ok=True)
        if not any(True for _ in self.kernel.elements.elems()):
            # Een leeg vel: geen bestand, anders lijkt het bij het terugkomen
            # alsof er iets stukging.
            target.unlink(missing_ok=True)
            return
        written = self.drawing.export_svg("vel.svg")
        shutil.copyfile(written, target)

    def _load(self, sheet_id: str) -> None:
        self.kernel.elements.clear_all()
        self.drawing.user_operations.clear()
        source = self._file(sheet_id)
        if source.is_file():
            self.drawing.runner.run(f'load "{source}"')
            self.kernel.elements.validate_ids()
            # De lagen van dit vel weer als "van de gebruiker" merken. Een verse
            # boom heeft ruim tweehonderd lege standaardoperaties; zonder deze
            # markering zijn de lagen die je zelf gemaakt hebt niet van die
            # ruis te onderscheiden en verdwijnen ze uit de lijst.
            for operation in self.kernel.elements.ops():
                if getattr(operation, "id", None):
                    self.drawing.user_operations.add(operation.id)
            # `load` zet de bestandsnaam op het document, en die naam komt
            # daarna terug als jobnaam in de spooler: elke job heette
            # `vel-2.svg` terwijl de gebruiker "Proefstuk" op zijn tabblad ziet
            # — dezelfde fout als `herstel.svg` in autosave.py. Dit bestand is
            # onze opslag, geen document dat de gebruiker een naam gaf, dus het
            # document blijft naamloos en de vellenbalk bepaalt de naam.
            try:
                self.kernel.elements._filename = None
            except Exception:  # pragma: no cover - de engine mag ons niet breken
                pass
        self.kernel.elements.signal("rebuild_tree", "all")
        self.kernel.elements.signal("refresh_scene", "Scene")

    # ------------------------------------------------------- verplaatsen

    def move_selection(self, ids, sheet_id: str) -> dict:
        """
        De selectie naar een ander vel verhuizen.

        Via het klembord van de engine: dat leeft op de elementenservice en
        overleeft dus het wisselen van vel. Knippen vóór het wisselen, plakken
        erna — precies de volgorde waarin niets tussen wal en schip valt.
        """
        sheets = self._ensure()
        self._find(sheets, sheet_id)
        if sheet_id == self._active:
            raise DesignError("Dat is het vel waar je al op werkt.")

        nodes = []
        for element_id in ids or []:
            node = self.kernel.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} bestaat niet (meer).")
            nodes.append(node)
        if not nodes:
            raise DesignError("Kies eerst wat er mee moet.")

        self.kernel.elements.set_emphasis(nodes)
        self.drawing.runner.run("clipboard cut")
        self.activate(sheet_id)
        self.drawing.runner.run("clipboard paste")
        self.kernel.elements.validate_ids()
        self.kernel.elements.signal("rebuild_tree", "all")
        self.document.touch()
        return {**self.state(), "moved": len(nodes)}

    # -------------------------------------------------------- projectbestand

    def export_into(self, bundle) -> list[dict]:
        """De vellen in een projectbestand zetten; geeft de index terug."""
        self.save_active()
        sheets = self._ensure()
        for sheet in sheets:
            source = self._file(sheet["id"])
            if source.is_file():
                bundle.write(source, f"vellen/{sheet['id']}.svg")
        return sheets

    def import_from(self, bundle, sheets: list[dict], active: str | None = None) -> None:
        """Vellen uit een projectbestand terugzetten; vervangt wat er lag."""
        if not sheets:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob("*.svg"):
            old.unlink(missing_ok=True)
        for sheet in sheets:
            name = f"vellen/{sheet['id']}.svg"
            if name in bundle.namelist():
                self._file(sheet["id"]).write_bytes(bundle.read(name))
        self._write(sheets)
        self._active = active if any(s["id"] == active for s in sheets) else sheets[0]["id"]
