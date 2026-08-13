"""
Nesten: de gekozen vormen zo dicht mogelijk op het materiaal leggen.

De engine kent hier niets voor, dus dit is eigen werk. Bewust een eenvoudige
methode — vormen op planken leggen, hoogste eerst — en niet meer dan dat:

- Het rekent op **omhullende rechthoeken**, niet op de echte omtrek. Twee ronde
  vormen kunnen dus verder uit elkaar liggen dan strikt nodig. Dat is eerlijker
  dan doen alsof het optimaal is, en het gaat nooit mis: rechthoeken die elkaar
  niet raken, raken de vormen erin ook niet.
- De marge staat er om de snijbreedte en het brandrandje heen. Nul marge betekent
  dat twee sneden elkaar raken, en dan is het één snede.

**Een groep is één ding.** Wat bij elkaar hoort, verhuist als geheel: de vormen
erin houden onderling exact hun plek. Dat is geen nettigheid maar een
noodzaak — een testbord is een meetinstrument, en zodra de vakjes onderling
herschikt zijn betekent "rij 3, kolom 5" niets meer en is de proef weggegooid.
Hetzelfde geldt voor een tandwiel dat je zelf uit vier vormen bouwde.

Raakt de nesting één lid van een groep, dan verhuist de hele groep — ook de
leden die niet meegegeven zijn. Anders zou "terughalen op het bed" (dat alleen
de vormen kent die het ziet) een bord alsnog uit elkaar trekken.
"""

from .edits import DesignError, _finite


class Nesting:
    def __init__(self, kernel, editor):
        self.kernel = kernel
        self.editor = editor

    @property
    def elements(self):
        return self.kernel.elements

    def nest(self, ids, margin_mm=3.0, origin_x_mm=0.0, origin_y_mm=0.0) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        margin = _finite(margin_mm, "margin_mm")
        if margin < 0:
            raise DesignError("Een negatieve marge laat de vormen overlappen.")
        origin_x = _finite(origin_x_mm, "origin_x_mm")
        origin_y = _finite(origin_y_mm, "origin_y_mm")

        # Eerst de losse vormen tot eenheden samenvouwen: alles wat in dezelfde
        # buitenste groep zit is één blok met één omhullende rechthoek.
        eenheden: dict[int, dict] = {}
        volgorde: list[int] = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} bestaat niet (meer).")
            groep = self._group_of(node)
            leden = self._members(groep) if groep is not None else [node]
            sleutel = id(groep) if groep is not None else id(node)
            if sleutel in eenheden:
                continue
            box = self._bounds_of(leden)
            if box is None:
                continue
            x0, y0, x1, y1 = (value / UNITS_PER_MM for value in box)
            self.elements.validate_ids()
            eenheden[sleutel] = {
                "ids": [n.id for n in leden if n.id],
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
            }
            volgorde.append(sleutel)
        boxes = [eenheden[key] for key in volgorde]
        if len(boxes) < 2:
            raise DesignError("Kies minstens twee vormen om te nesten.")

        width_mm = self._bed_width()
        widest = max(box["width"] for box in boxes)
        usable = max(width_mm - 2 * origin_x, widest + margin)

        # Hoogste eerst: dan blijft er minder lucht boven een plank staan.
        boxes.sort(key=lambda box: box["height"], reverse=True)

        placed, x, y, shelf = [], origin_x, origin_y, 0.0
        for box in boxes:
            if x > origin_x and x + box["width"] > origin_x + usable:
                x = origin_x
                y += shelf + margin
                shelf = 0.0
            placed.append({**box, "to_x": x, "to_y": y})
            x += box["width"] + margin
            shelf = max(shelf, box["height"])

        moved = 0
        with self.elements.undoscope("Nesten"):
            for box in placed:
                dx = box["to_x"] - box["x"]
                dy = box["to_y"] - box["y"]
                if abs(dx) < 0.001 and abs(dy) < 0.001:
                    continue
                # Alle leden van de eenheid in één zet: `translate` werkt op de
                # hele selectie, dus de onderlinge afstanden blijven exact.
                self.editor.move(box["ids"], dx, dy)
                moved += len(box["ids"])

        used_height = (y + shelf) - origin_y
        return {
            "moved": moved,
            "used_width_mm": round(usable, 1),
            "used_height_mm": round(used_height, 1),
        }

    @staticmethod
    def _group_of(node):
        """
        De **buitenste** groep waar deze vorm in zit, of niets.

        Buitenste en niet dichtstbijzijnde: een testbord met een gegroepeerd
        opschrift erin is nog steeds één bord. De diepte is begrensd zoals
        overal waar we de boom oplopen — een cyclus in de boom mag geen
        eindeloze lus worden.
        """
        parent = getattr(node, "parent", None)
        buitenste = None
        depth = 0
        while parent is not None and depth < 20:
            if getattr(parent, "type", None) == "group":
                buitenste = parent
            parent = getattr(parent, "parent", None)
            depth += 1
        return buitenste

    @classmethod
    def _members(cls, groep) -> list:
        """Alle vormen onder een groep, hoe diep ook genest."""
        leden = []
        for child in getattr(groep, "children", []) or []:
            if getattr(child, "type", "") == "group":
                leden.extend(cls._members(child))
            elif getattr(child, "bounds", None):
                leden.append(child)
        return leden

    @staticmethod
    def _bounds_of(nodes):
        """De omhullende rechthoek van een eenheid, in engine-eenheden."""
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for node in nodes:
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            a, b, c, d = bounds
            x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
        return None if x0 == float("inf") else (x0, y0, x1, y1)

    def _bed_width(self) -> float:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)
        value = getattr(device, "bedwidth", None)
        try:
            return float(Length(value).mm)
        except Exception:
            # Zonder bekend bed nemen we een halve meter aan; nesten mag niet
            # afketsen op een apparaat dat zijn maat niet vertelt.
            return 500.0
