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

        boxes = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} bestaat niet (meer).")
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            x0, y0, x1, y1 = (value / UNITS_PER_MM for value in bounds)
            boxes.append(
                {
                    "id": element_id,
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0,
                }
            )
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
                self.editor.move([box["id"]], dx, dy)
                moved += 1

        used_height = (y + shelf) - origin_y
        return {
            "moved": moved,
            "used_width_mm": round(usable, 1),
            "used_height_mm": round(used_height, 1),
        }

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
