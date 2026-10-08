"""
Text in an imported SVG, turned into the vector text the text tool makes.

The engine reads an SVG `<text>` into an `elem text`, and that node only becomes a shape
through a font renderer — which lives in the wxPython GUI we do not run. Without one the
node has no geometry at all, and that made it disappear three times over. Measured on a
drawing with nine red outlines and nine blue labels (`fill="#0000ff"`, 6 mm Helvetica):

- the snapshot left the labels out (`DesignReader._element` drops a node without a path),
  so the canvas showed nine shapes where the file had eighteen;
- the engine still classified them, so "Standard-Raster" counted 18 elements with nothing
  visible in it;
- the rasteriser skips `elem text` on purpose (`rasterizer._SKIPPED_TYPES`), so the burn
  left the labels off the plate without a word.

So each text becomes what its outline as a `<path>` would have been: the same paint
(`fill`, `stroke`) and the same classification, which is whatever the engine does with a
path of that colour — a filled blue path lands in the raster layer, an outlined one in
an engrave layer. The geometry is the text tool's own (`create_linetext_node`), so the
result is editable text like any other, with its `mktext` and friends on it.

A text that cannot be made into a shape is taken out and named, not left in a layer.
"""

from __future__ import annotations

import math

#: SVG's generic families name no file; asking the font registry for them finds nothing
#: and only wastes a search, so they go straight to the fallback.
GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}

ALIGNMENTS = ("start", "middle", "end")


def outline_texts(kernel, nodes) -> dict:
    """
    Replace every `elem text` among `nodes` with vector text.

    Hands back the texts that could not be turned into a shape, by their wording, so the
    import can say which labels did not come in. The rest is replaced in place: same
    parent, same position among its siblings.
    """
    elements = kernel.elements
    registry = getattr(kernel.root, "fonts", None)
    unreadable: list[str] = []
    replaced = []
    for node in list(nodes):
        if getattr(node, "type", None) != "elem text":
            continue
        wording = str(getattr(node, "text", "") or "")
        if not wording.strip():
            # A text of nothing but spaces draws nothing in any program; there is no
            # label to lose.
            node.remove_node()
            continue
        shape = None
        if registry is not None:
            try:
                shape = _vector_text(kernel, registry, node, wording)
            except Exception:
                shape = None
        if shape is None:
            unreadable.append(wording)
            node.remove_node()
            continue
        parent = node.parent
        index = parent.children.index(node)
        node.remove_node()
        parent.add_node(shape, pos=index)
        replaced.append(shape)
    if replaced and getattr(elements, "classify_new", True):
        elements.classify(replaced)
    return {"outlined": len(replaced), "unreadable": unreadable}


def _vector_text(kernel, registry, node, wording):
    """The path node for one text, or None when no shape comes out of it."""
    from meerk40t.svgelements import Matrix

    matrix = Matrix(node.matrix)
    # The SVG's font-size is in the text's own units; the matrix carries the scale to the
    # bed (2580.12 per mm for a drawing in millimetres). Taking that scale out of the
    # matrix and into the size leaves the matrix at what the text tool would have given:
    # a translation, plus any rotation the drawing had.
    scale = math.sqrt(abs(matrix.a * matrix.d - matrix.b * matrix.c))
    if not scale:
        return None
    size = float(getattr(node, "font_size", None) or 16.0) * scale
    align = getattr(node, "anchor", None)
    if align not in ALIGNMENTS:
        align = "start"

    root = kernel.root
    root.setting(str, "last_font", "")
    previous = root.last_font
    try:
        # Same guard as `Drawing._keep_last_font`: the engine writes every font it uses
        # into `last_font`, and an imported label must not choose the next text's font.
        shape = registry.create_linetext_node(
            0, 0, wording, font=_font_for(registry, node), font_size=size, align=align
        )
    finally:
        root.last_font = previous
    if shape is None or shape.bounds is None:
        return None
    x0, y0, x1, y1 = shape.bounds
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or (x1 - x0) <= 0:
        return None

    matrix.pre_scale(1 / scale)
    shape.matrix = matrix
    # The bounds above were cached at the origin; without this every label reports the
    # spot where it was rendered instead of where it stands (measured: all nine at 0,0).
    shape.set_dirty_bounds()
    shape.fill = node.fill
    shape.stroke = node.stroke
    shape.stroke_width = node.stroke_width
    if getattr(node, "label", None):
        shape.label = node.label
    return shape


def _font_for(registry, node):
    """
    The first family in the SVG's list that this computer can render, else None.

    None makes the engine fall back the way a text without a font does in the text tool.
    Worth knowing: Helvetica on a Mac is a `.ttc`, which the engine does not read, so
    `"Helvetica, Arial, sans-serif"` comes out in Arial — measured.
    """
    families = str(getattr(node, "font_family", "") or "")
    for family in families.split(","):
        family = family.strip().strip("'\"")
        if not family or family.lower() in GENERIC_FAMILIES:
            continue
        path = registry.face_to_full_name(family)
        if path:
            return path
    return None
