"""
De lopende tegelreeks: het plan per tegel, en waar je in de reeks bent.

Het klippen en verplaatsen gebeurt op de **kopie** die `plan copy` maakt.
`copy_children_as_real` (meerk40t/core/node/node.py:805) dereferentieert de
ReferenceNodes en kopieert de vormen zelf, dus alles wat hier gebeurt laat de
elementenboom van de gebruiker ongemoeid. Dat is geen bijzaak maar de reden dat
dit ontwerp zo weinig hoeft aan te raken.
"""

from __future__ import annotations

import math

from .tiling import Alignment, Rect, clip_geometry


class TileMutator:
    """
    Eén tegel: klip het plan op het brandgebied en zet het waar de plaat ligt.

    Scènecoördinaten zijn plaatcoördinaten — het ontwerp is op de plaat
    getekend en de engine leest de scène als het bed. De uitlijnmatrix mag
    daarom rechtstreeks in de scène toegepast worden, net zoals
    `Drawing.verschoven` het nulpunt toepast.
    """

    def __init__(
        self,
        burn_mm: Rect,
        alignment: Alignment,
        units_per_mm: float,
        marker_geometry=None,
    ):
        self.burn_mm = burn_mm
        self.alignment = alignment
        self.units_per_mm = units_per_mm
        self.marker_geometry = marker_geometry
        #: hoeveel geklipte geometrie deze tegel brandt, in engine-eenheden.
        #: Hier geteld en niet achteraf uit het plan gelezen: `blob` vervangt de
        #: bewerkingen door één CutCode, en dan is dit niet meer te achterhalen.
        #: De merken tellen niet mee — die horen bij de machine, niet bij het werk.
        self.burned_length_units = 0.0

    # ------------------------------------------------------------- rekenen

    @property
    def burn_units(self) -> Rect:
        u = self.units_per_mm
        return Rect(
            self.burn_mm.x0 * u,
            self.burn_mm.y0 * u,
            self.burn_mm.x1 * u,
            self.burn_mm.y1 * u,
        )

    def matrix(self):
        """De uitlijning als matrix in engine-eenheden."""
        from meerk40t.svgelements import Matrix

        u = self.units_per_mm
        mx = Matrix()
        mx.post_rotate(math.radians(self.alignment.angle_deg))
        mx.post_translate(self.alignment.dx_mm * u, self.alignment.dy_mm * u)
        return mx

    # ------------------------------------------------------------ bewerken

    def __call__(self, steps):
        blijft = []
        for step in steps:
            children = getattr(step, "children", None)
            if children is None:
                blijft.append(step)
                continue
            if self._reshape(step):
                blijft.append(step)
        return blijft

    def _reshape(self, operation) -> bool:
        """Klip de kinderen van deze bewerking. Geeft terug of er iets overblijft."""
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.svgelements import Matrix

        venster = self.burn_units
        mx = self.matrix()
        vervangers = []
        for child in list(operation.children):
            geom = self._geometry(child)
            if geom is None:
                # Een knoop zonder geometrie (een afbeelding) verplaatsen we
                # met zijn eigen matrix; klippen gebeurt bij het rasteren.
                vervangers.append(self._moved_image(child, mx))
                continue
            geklipt = clip_geometry(geom, venster)
            if geklipt.index == 0:
                continue
            self.burned_length_units += sum(
                abs(geklipt.length(i)) for i in range(geklipt.index)
            )
            geklipt.transform(mx)
            vervangers.append(
                PathNode(
                    geklipt,
                    matrix=Matrix(),
                    stroke=getattr(child, "stroke", None),
                    fill=getattr(child, "fill", None),
                    stroke_width=getattr(child, "stroke_width", 1000.0),
                )
            )

        for child in list(operation.children):
            child.remove_node()
        for node in [v for v in vervangers if v is not None]:
            operation.add_node(node)
        return bool(operation.children)

    @staticmethod
    def _geometry(node):
        maker = getattr(node, "as_geometry", None)
        if maker is None:
            return None
        try:
            return maker()
        except Exception:
            return None

    @staticmethod
    def _moved_image(node, mx):
        """Een afbeelding verplaatst mee; hij draagt zijn eigen matrix."""
        matrix = getattr(node, "matrix", None)
        if matrix is None:
            return node
        node.matrix.post_cat(mx)
        marker = getattr(node, "set_dirty_bounds", None)
        if marker is not None:
            # Een rauwe matrixtoekenning meldt niets aan de knoop; zonder dit
            # draagt hij de omhullende van zijn oude plek.
            marker()
        return node
