"""
Knooppunten bewerken: de punten van een vorm zelf verslepen.

Tot nu toe kon je een vorm als geheel verplaatsen, schalen en draaien, maar niet
één hoek verleggen. Dat is precies wat je nodig hebt om een gescand of
geïmporteerd pad passend te maken.

Twee dingen om te weten:

- De engine bewaart een `elem path` als een **Geomstr**: segmenten met complexe
  getallen als punten. Een punt verplaatsen betekent alle segmenten aanpassen
  waar dat punt in voorkomt — begin- én eindpunt, anders valt het pad open.
- Vormen (`elem rect`, `elem ellipse`, …) hebben geen losse punten; ze zijn
  parameters. Wie daar een hoek van versleept, bedoelt "make it a path".
  Dat doen we dan ook, met behoud van kleur, laagtoewijzing en label — anders
  verdwijnt de vorm uit zijn bewerking en zou hij niet meer meebranden.
"""

from __future__ import annotations

from .edits import DesignError

# Punten die binnen deze afstand (in Tats) liggen, zijn hetzelfde punt.
# 65535 Tats is een inch, dus dit is ruwweg een honderdste millimeter.
SAME_POINT = 30.0

SHAPES = ("elem rect", "elem ellipse", "elem line", "elem polyline", "elem path")


class Nodes:
    def __init__(self, kernel, runner=None):
        self.kernel = kernel
        self.runner = runner

    @property
    def elements(self):
        return self.kernel.elements

    def points(self, element_id: str) -> dict:
        """The nodes of an element, in millimetres."""
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        geometry = self._geometry(node)
        return {
            "id": element_id,
            "type": node.type,
            "editable": node.type in SHAPES,
            "points": [
                {"index": index, "x_mm": point.real / UNITS_PER_MM, "y_mm": point.imag / UNITS_PER_MM}
                for index, point in enumerate(self._unique(geometry))
            ],
        }

    def move_point(self, element_id: str, index, x_mm, y_mm) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        if node.type not in SHAPES:
            raise DesignError(f"The nodes of a {node.type} cannot be edited.",
            code="nodes.notEditable",)
        try:
            position = int(index)
            target = complex(float(x_mm) * UNITS_PER_MM, float(y_mm) * UNITS_PER_MM)
        except (TypeError, ValueError) as e:
            raise DesignError("A node needs an index and a position.") from e

        geometry = self._geometry(node)
        points = self._unique(geometry)
        if not 0 <= position < len(points):
            raise DesignError(
                f"Node {position} does not exist; there are {len(points)}."
            )

        moved = self._with_point_moved(geometry, points[position], target)
        with self.elements.undoscope("Move node"):
            new_id = self._replace(node, moved, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "index": position}

    # --------------------------------------------------------------- intern

    def _node(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(f"Element {element_id} does not exist (any more).")
        return node

    def _geometry(self, node):
        try:
            return node.as_geometry()
        except Exception as e:  # pragma: no cover - alleen bij exotische nodes
            raise DesignError(f"No shape can be read from this element: {e}") from e

    def _unique(self, geometry) -> list[complex]:
        """
        Elk knooppunt één keer, in de volgorde waarin het pad loopt.

        Segmenten delen hun eindpunten; zonder ontdubbelen zou de gebruiker twee
        handvatten op elkaar zien liggen en zou "punt 3" niets betekenen.
        """
        found: list[complex] = []
        for segment in geometry.segments[: geometry.index]:
            for point in (segment[0], segment[4]):
                value = complex(point)
                if not any(abs(value - seen) <= SAME_POINT for seen in found):
                    found.append(value)
        return found

    def _with_point_moved(self, geometry, source: complex, target: complex):
        """A copy of the shape with that one point moved."""
        import copy

        moved = copy.deepcopy(geometry)
        shift = target - source
        for segment in moved.segments[: moved.index]:
            for column in (0, 4):
                if abs(complex(segment[column]) - source) <= SAME_POINT:
                    segment[column] = target
            # Regelrechte lijnen hebben hun controlepunten op de uiteinden
            # liggen; laat je die staan, dan knikt een rechte lijn krom.
            for column in (1, 3):
                if abs(complex(segment[column]) - source) <= SAME_POINT:
                    segment[column] = complex(segment[column]) + shift
        return moved

    def _replace(self, node, geometry, element_id: str) -> str:
        """
        De nieuwe vorm terugschrijven.

        Een pad kan zijn geometrie gewoon vervangen. Een rechthoek niet: die
        wordt een pad, en dan moet alles wat eraan hing mee — kleur, label en
        vooral de bewerkingen waar hij in zat.
        """
        if node.type == "elem path":
            node.geometry = geometry
            # De matrix zit al in as_geometry() verwerkt; hem laten staan zou de
            # verplaatsing een tweede keer toepassen.
            node.matrix.reset()
            node.altered()
            return element_id

        operations = [
            reference.parent
            for reference in list(getattr(node, "_references", []))
            if reference.parent is not None
        ]
        parent = node.parent
        replacement = parent.add(
            geometry=geometry,
            type="elem path",
            stroke=getattr(node, "stroke", None),
            stroke_width=getattr(node, "stroke_width", None),
            fill=getattr(node, "fill", None),
            label=getattr(node, "label", None),
        )
        node.remove_node()
        for operation in operations:
            operation.add_reference(replacement)
        self.elements.validate_ids()
        return replacement.id or element_id
