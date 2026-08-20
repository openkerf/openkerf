"""
Een rasteraar zonder GUI.

`op raster` zet zijn vormen tijdens het plannen om in een bitmap, en vraagt de
kernel daarvoor om de dienst `render-op/make_raster`
(`meerk40t/core/node/op_raster.py:468`). Die dienst registreert **alleen de
wxPython-GUI** (`meerk40t/gui/plugin.py:79`, met als commentaar "This is used to
do cut planning" — upstream weet dus dat het geen UI-taak is). Ontbreekt hij,
dan neemt `OpRasterNode.preprocess` de `strip_rasters`-tak: de laag gooit zijn
eigen kinderen weg en levert nul cutcode. Elke rasterbewerking komt dan blanco
uit de machine.

Deze module levert dezelfde dienst op Pillow, geregistreerd vanuit onze eigen
plugin. Er verandert dus niets in de MeerK40t-repo zelf. Draait iemand ooit mét
GUI, dan staat de wx-rasteraar er al en laten wij hem staan.

Het contract is afgeleid uit `meerk40t/gui/laserrender.py:1356` en de aanroep in
`op_raster.py:503`:

    make_raster(nodes, bounds, width=None, height=None, bitmap=False,
                step_x=1, step_y=1, keep_ratio=False) -> PIL.Image

Wit is achtergrond, zwart is werk; de engine doet er daarna `.convert("L")` op
en drempelt het in `process_image()`.
"""

from math import ceil

import numpy as np
from PIL import Image, ImageChops, ImageDraw

# Waar de wx-versie een GraphicsContext met INTERPOLATION_BEST heeft, tekenen
# wij op een veelvoud en verkleinen we met LANCZOS. Een rasterlaag wordt daarna
# gedrempeld; zachte randen leveren dan nettere trapjes dan harde.
SUPERSAMPLE = 4

# Een rasterlaag over een heel bed op 1000 dpi is zo een half gigapixel. De
# wx-versie loopt daar op een MemoryError vast, die `preprocess` opvangt als
# "Raster too large". Wij begrenzen liever de hulpschaal dan het resultaat.
MAX_SUPERSAMPLED_PIXELS = 64_000_000

# Wat we kunnen tekenen. De rest slaan we over in plaats van erop te struikelen.
_SKIPPED_TYPES = ("elem text",)


def register(kernel) -> bool:
    """
    Registreer de rasteraar, maar alleen als er nog geen is.

    Geeft terug of wij hem geleverd hebben. Staat er al iets (de wxPython-GUI),
    dan wint die: die tekent met de echte fonts en de echte penstreken.
    """
    root = kernel.root
    try:
        if root.lookup("render-op/make_raster") is not None:
            return False
    except Exception:
        return False
    root.register("render-op/make_raster", make_raster)
    return True


def make_raster(
    nodes,
    bounds,
    width=None,
    height=None,
    bitmap=False,
    step_x=1,
    step_y=1,
    keep_ratio=False,
):
    """
    Zet een verzameling elementknopen om in een afbeelding van de gevraagde maat.

    @param nodes: de elementknopen (de engine heeft references al opgelost).
    @param bounds: (x0, y0, x1, y1) in native eenheden; None → None.
    @param width: gewenste breedte in pixels; None → `raster_width / step_x`.
    @param height: gewenste hoogte in pixels; None → `raster_height / step_y`.
    @param bitmap: alleen voor de wx-versie; hier zonder betekenis.
    @param step_x: rasterstap, tevens de schaal van de afbeelding.
    @param step_y: idem, verticaal.
    @param keep_ratio: de kleinste van beide schalen op beide assen.
    @return: een RGB-afbeelding, wit met het werk in zwart.
    """
    if bounds is None:
        return None
    # Een stap van nul is geen stap maar een deling door nul.
    if not step_x:
        step_x = 1
    if not step_y:
        step_y = 1

    _nodes = list(nodes) if isinstance(nodes, (tuple, list)) else [nodes]
    _nodes = [n.node if getattr(n, "type", None) == "reference" else n for n in _nodes]

    x_min, y_min, x_max, y_max = _union_paint_bounds(_nodes, bounds)

    raster_width = max(x_max - x_min, 1)
    raster_height = max(y_max - y_min, 1)
    if width is None:
        width = raster_width / step_x
    if height is None:
        height = raster_height / step_y
    width = max(width, 1)
    height = max(height, 1)

    scale_x = width / raster_width
    scale_y = height / raster_height
    if keep_ratio:
        scale_x = scale_y = min(scale_x, scale_y)

    pixel_width = int(ceil(abs(width)))
    pixel_height = int(ceil(abs(height)))

    # De affiene afbeelding van scene- naar pixelcoördinaten. Dezelfde volgorde
    # als de wx-versie: eerst naar de oorsprong schuiven, dan schalen; een
    # negatieve schaal spiegelt en moet daarna terug in beeld geschoven worden.
    offset_x = -x_min
    offset_y = -y_min
    if scale_x < 0:
        offset_x -= raster_width
    if scale_y < 0:
        offset_y -= raster_height

    supersample = _supersample_for(pixel_width, pixel_height)
    canvas = Image.new(
        "RGB", (pixel_width * supersample, pixel_height * supersample), "white"
    )
    draw = ImageDraw.Draw(canvas)

    transform = _Transform(
        scale_x * supersample,
        scale_y * supersample,
        offset_x,
        offset_y,
        supersample,
    )
    for node in _nodes:
        _draw_node(canvas, draw, node, transform)

    if supersample != 1:
        canvas = canvas.resize((pixel_width, pixel_height), Image.LANCZOS)
    return canvas


def _supersample_for(pixel_width: int, pixel_height: int) -> int:
    """As much supersampling as fits in memory, and no more."""
    pixels = max(pixel_width * pixel_height, 1)
    supersample = SUPERSAMPLE
    while supersample > 1 and pixels * supersample * supersample > MAX_SUPERSAMPLED_PIXELS:
        supersample //= 2
    return supersample


def _union_paint_bounds(nodes, fallback):
    """
    Het kader waarin getekend wordt: `paint_bounds` van de knopen, met terugval
    op `bounds` van de knoop en uiteindelijk op het meegegeven kader.
    """
    x_min = y_min = float("inf")
    x_max = y_max = -float("inf")
    for node in nodes:
        box = None
        try:
            box = node.paint_bounds
        except Exception:
            box = None
        if box is None:
            try:
                box = node.bounds
            except Exception:
                box = None
        if box is None:
            continue
        x_min = min(x_min, box[0])
        y_min = min(y_min, box[1])
        x_max = max(x_max, box[2])
        y_max = max(y_max, box[3])
    if x_min == float("inf"):
        return tuple(fallback)
    return x_min, y_min, x_max, y_max


class _Transform:
    """Scene units to pixels, plus the pen width that goes with it."""

    def __init__(self, scale_x, scale_y, offset_x, offset_y, supersample):
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.supersample = supersample

    def points(self, complex_points):
        """A row of complex points to a list of (x, y) in pixels."""
        array = np.asarray(complex_points, dtype=complex)
        xs = (array.real + self.offset_x) * self.scale_x
        ys = (array.imag + self.offset_y) * self.scale_y
        return list(zip(xs.tolist(), ys.tolist()))

    def line_width(self, stroke_width) -> int:
        """
        Een streek van nul breed is op een raster onzichtbaar, en dat is precies
        wat je niet wil: dan brandt de laag niets. Minimaal één pixel dus, en op
        de hulpschaal ook echt zo dik als hij op het eindresultaat moet zijn.
        """
        scale = (abs(self.scale_x) + abs(self.scale_y)) / 2
        try:
            width = float(stroke_width or 0) * scale
        except (TypeError, ValueError):
            width = 0
        return max(int(round(width)), self.supersample)


def _draw_node(canvas, draw, node, transform):
    node_type = getattr(node, "type", "") or ""
    if getattr(node, "hidden", False):
        return
    if node_type in _SKIPPED_TYPES:
        # Tekst zonder GUI heeft geen font-engine. In onze app is tekst al naar
        # geometrie omgezet vóór het planningsmoment; komt er toch een `elem
        # text` langs, dan is niets tekenen beter dan omvallen.
        return
    if node_type == "elem image" or hasattr(node, "as_image"):
        _draw_image(canvas, node, transform)
        return
    geometry = _geometry_of(node)
    if geometry is None:
        return
    _draw_geometry(canvas, draw, node, geometry, transform)


def _geometry_of(node):
    getter = getattr(node, "as_geometry", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _draw_geometry(canvas, draw, node, geometry, transform):
    fill = _paint(getattr(node, "fill", None))
    stroke = _paint(getattr(node, "stroke", None))
    # Zonder streek en zonder vulling zou een vorm onzichtbaar zijn, en dus
    # niet gebrand worden. Een vorm die in een rasterlaag zit, is bedoeld om te
    # branden: dan is een haarlijn de eerlijkste weergave.
    if not fill and not stroke:
        stroke = True
    width = transform.line_width(
        getattr(node, "implied_stroke_width", None)
        if getattr(node, "implied_stroke_width", None) is not None
        else getattr(node, "stroke_width", None)
    )

    vlakken = []
    for polyline in _polylines(geometry):
        points = transform.points(polyline)
        if len(points) < 2:
            if len(points) == 1 and stroke:
                x, y = points[0]
                draw.ellipse(
                    (x - width / 2, y - width / 2, x + width / 2, y + width / 2),
                    fill="black",
                )
            continue
        closed = _is_closed(points, tolerance=transform.supersample)
        if fill and closed and len(points) >= 3:
            vlakken.append(points)
        if stroke:
            draw.line(points, fill="black", width=width, joint="curve")
    _fill(canvas, draw, vlakken)


def _fill(canvas, draw, vlakken) -> None:
    """
    De gesloten deelpaden van één vorm vullen, met gaten.

    Eén deelpad is één vlak; dan is `polygon` het snelst. Meerdere deelpaden
    horen bij elkaar: de binnencontour van een "0" is een gat en niet een tweede
    vlak. Elk deelpad los vullen gaf een nul die op het scherm open stond en op
    het hout helemaal dichtgebrand was.

    Even-oddregel, door de maskers op elkaar te XOR-en. SVG rekent standaard met
    nonzero, en die twee verschillen alleen bij contouren die elkaar overlappen
    én dezelfde kant op lopen — bij letters en CAD-vormen loopt een gat juist
    andersom, dus daar komen ze op hetzelfde uit. Het masker beslaat alleen de
    omhullende van de vorm, zodat een groot bed niet per deelpad een volledig
    beeld kost.
    """
    if not vlakken:
        return
    if len(vlakken) == 1:
        draw.polygon(vlakken[0], fill="black")
        return

    punten = [p for vlak in vlakken for p in vlak]
    x0 = max(int(min(x for x, _ in punten)) - 1, 0)
    y0 = max(int(min(y for _, y in punten)) - 1, 0)
    x1 = min(int(max(x for x, _ in punten)) + 2, canvas.width)
    y1 = min(int(max(y for _, y in punten)) + 2, canvas.height)
    if x1 <= x0 or y1 <= y0:
        return

    masker = Image.new("1", (x1 - x0, y1 - y0), 0)
    for vlak in vlakken:
        laag = Image.new("1", masker.size, 0)
        ImageDraw.Draw(laag).polygon(
            [(x - x0, y - y0) for x, y in vlak], fill=1
        )
        masker = ImageChops.logical_xor(masker, laag)
    canvas.paste("black", (x0, y0), masker)


def _polylines(geometry):
    """
    De geometrie als polylijnen in scene-eenheden.

    `as_interpolated_points` levert de punten van de hele geomstr achter elkaar,
    met een `None` op elke breuk tussen deelpaden.
    """
    current = []
    try:
        points = geometry.as_interpolated_points(interpolate=50)
    except Exception:
        return
    for point in points:
        if point is None:
            if current:
                yield current
            current = []
            continue
        if np.isnan(point.real) or np.isnan(point.imag):
            continue
        current.append(point)
    if current:
        yield current


def _is_closed(points, tolerance=1.0) -> bool:
    first, last = points[0], points[-1]
    return abs(first[0] - last[0]) <= tolerance and abs(first[1] - last[1]) <= tolerance


def _paint(color) -> bool:
    """Does this colour actually put anything down?"""
    if color is None:
        return False
    value = getattr(color, "value", "unset")
    if value is None:
        return False
    alpha = getattr(color, "alpha", 255)
    return alpha is None or alpha > 0


def _draw_image(canvas, node, transform):
    """
    Een afbeeldingsknoop met zijn eigen matrix inplakken.

    De knoop draagt zijn plaatsing in `active_matrix`; die vermenigvuldigen we
    met onze scene→pixel-afbeelding en voeren we omgekeerd aan Pillow, want
    `Image.transform` vraagt de afbeelding van doel naar bron.
    """
    try:
        image = node.active_image
        matrix = node.active_matrix
    except Exception:
        try:
            image = node.image
            matrix = node.matrix
        except Exception:
            return
    if image is None:
        return

    # De volledige afbeelding van beeldpixel naar canvaspixel.
    a = matrix.a * transform.scale_x
    b = matrix.b * transform.scale_y
    c = matrix.c * transform.scale_x
    d = matrix.d * transform.scale_y
    e = (matrix.e + transform.offset_x) * transform.scale_x
    f = (matrix.f + transform.offset_y) * transform.scale_y

    determinant = a * d - b * c
    if not determinant:
        return
    # De inverse: canvaspixel terug naar beeldpixel.
    inv_a = d / determinant
    inv_b = -c / determinant
    inv_c = (c * f - d * e) / determinant
    inv_d = -b / determinant
    inv_e = a / determinant
    inv_f = (b * e - a * f) / determinant

    if image.mode not in ("RGBA", "RGB", "L"):
        image = image.convert("RGBA")
    mask = image.getchannel("A") if image.mode == "RGBA" else None
    placed = image.convert("RGB").transform(
        canvas.size,
        Image.AFFINE,
        (inv_a, inv_b, inv_c, inv_d, inv_e, inv_f),
        resample=Image.BILINEAR,
        fillcolor=(255, 255, 255),
    )
    if mask is not None:
        mask = mask.transform(
            canvas.size,
            Image.AFFINE,
            (inv_a, inv_b, inv_c, inv_d, inv_e, inv_f),
            resample=Image.BILINEAR,
            fillcolor=0,
        )
        canvas.paste(placed, (0, 0), mask)
    else:
        canvas.paste(placed, (0, 0))
