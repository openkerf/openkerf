"""
The code a board carries: minted, drawn, and read back.

A code nobody can read back is a decoration, so the tests here do not stop at the geometry.
They render what `boardcode.plan` hands over — the same millimetres the laser would get —
and put it through the same OpenCV that a phone photograph goes through. Two of them are
the bugs that were measured while this was designed, kept as tests so they cannot come
back: `segno.make` returning an undecodable Micro QR, and the plain OpenCV detector losing
the code among a board's own dark squares.

Numbers in this file were measured on this laptop with OpenCV 5.0.0, segno 1.6.6 and the
MeerK40t working copy at 0.9.9040 (`meerk40t/main.py:26` — not the 0.9.9000 floor of the
pin in `api/pyproject.toml`, which is what an earlier version of this line quoted).
Nothing has been burned: no board with a code has been on a laser, so every millimetre here
is arithmetic on top of pixels.
"""

import numpy as np
import pytest
import segno

from openkerf_api import boardcode
from openkerf_api.edits import DesignError

HAVE_CV2 = boardcode.available()
needs_cv2 = pytest.mark.skipif(
    not HAVE_CV2, reason="OpenCV is an optional extra; reading codes needs it"
)


# --------------------------------------------------------------- helpers


def render(code: dict, px_per_mm: float, background: int = 255, ink: int = 0):
    """
    The planned squares as pixels, in the millimetres they were planned in.

    Nearest neighbour and noise free: this is the best case a decoder will ever see, so a
    failure here is the format or the arithmetic and never the picture.
    """
    side = int(round(code["size_mm"] * px_per_mm))
    picture = np.full((side, side), background, dtype=np.uint8)
    for square in code["squares"]:
        xs = [(x - code["x_mm"]) * px_per_mm for x, _ in square]
        ys = [(y - code["y_mm"]) * px_per_mm for _, y in square]
        left, right = int(round(min(xs))), int(round(max(xs)))
        top, bottom = int(round(min(ys))), int(round(max(ys)))
        picture[top:max(bottom, top + 1), left:max(right, left + 1)] = ink
    return picture


def photograph(picture, seed=0, angle=5.0, blur=1.1, noise=5, quality=85):
    """
    The same picture as a phone would hand it in: turned a little, soft, noisy, JPEG.

    Not a substitute for wood — nothing here knows what char does to a module edge — but it
    is the difference between "the pattern is right" and "a camera can read it".
    """
    import cv2

    rng = np.random.default_rng(seed)
    height, width = picture.shape
    turned = cv2.warpAffine(
        picture,
        cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0),
        (width, height),
        borderValue=int(picture[0][0]),
    )
    soft = cv2.GaussianBlur(turned, (0, 0), blur)
    speckled = np.clip(
        soft.astype(np.int16) + rng.normal(0, noise, soft.shape).astype(np.int16), 0, 255
    ).astype(np.uint8)
    ok, buffer = cv2.imencode(
        ".jpg", speckled, [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    assert ok
    return bytes(buffer)


def on_a_board(
    code: dict,
    width_px: int,
    board_mm: float = 300.0,
    seed=0,
    squares=True,
    photo=True,
):
    """
    The code where it really is: a corner of a plank, with the board's own squares on it.

    The squares are here because a photograph of a test board always has sixteen of them —
    not because they are what breaks the reading. They were long blamed for that, and they
    measure the same either way; `squares=False` is how that was found out and is what
    `test_it_is_the_photograph_and_not_the_boards_own_squares` uses.
    """
    import cv2

    px_per_mm = width_px / board_mm
    plank = np.full((int(width_px * 0.7), width_px), 232, dtype=np.uint8)
    stamp = render(code, px_per_mm, background=232, ink=48)
    # A tenth of the frame in from the corner, and not right against it: turning the
    # picture 5 degrees about its centre swings a corner by 70-odd pixels either way, and
    # the first version of this helper rotated the code clean out of the frame — which read
    # as "the code is unreadable" when it was simply not in the picture any more.
    margin = int(width_px * 0.1)
    plank[margin : margin + stamp.shape[0], margin : margin + stamp.shape[1]] = stamp
    step = int(width_px * 0.06)
    for row in range(4) if squares else ():
        for column in range(4):
            top = int(width_px * 0.25) + row * step
            left = int(width_px * 0.35) + column * step
            plank[top : top + int(step * 0.8), left : left + int(step * 0.8)] = (
                60 + row * 40 + column * 8
            )
    # `photo=False` hands back the plank as pixels rather than as a JPEG of a plank: the
    # control arm, and the only way to tell the picture apart from what is in it.
    return photograph(plank, seed=seed) if photo else plank


# --------------------------------------------------------------- the identity


def test_the_uid_is_made_of_characters_a_reader_cannot_mix_up():
    """
    No I, L, O or U — Crockford base32, because the code is also printed to be typed.

    Measured over 500 minted uids: all eight characters long, all inside the alphabet, all
    500 different. Random and not a counter or a clock, because boards 28 and 29 in the
    live library were created 21 seconds apart, and a row id is whatever SQLite hands out
    (`library.py:1637`), so neither a timestamp nor the row id is an identity.
    """
    assert not set("ILOU") & set(boardcode.UID_ALPHABET)
    minted = {boardcode.mint_uid() for _ in range(500)}
    assert len(minted) == 500
    assert all(len(uid) == boardcode.UID_LENGTH for uid in minted)
    assert all(set(uid) <= set(boardcode.UID_ALPHABET) for uid in minted)


def test_what_is_printed_under_the_code_is_what_a_reader_types_back():
    """
    `OK1:7X4MQB2K` in the code, `7X4M QB2K` under it, and both parse back to the uid.

    The typed forms are the ones a person actually produces off a plank: lower case, the
    space where the caption has one, a hyphen instead, no prefix at all, and Crockford's
    substitutions (I and L for 1, O for 0). A U is refused rather than guessed: it is not in
    the alphabet, so a reader who typed one got something else wrong too and a corrected uid
    would name a board nobody meant. Anything that is not a board code — a Wi-Fi sticker
    caught in the same photograph — comes back as None, which is how `read` filters it.
    """
    assert boardcode.payload("7X4MQB2K") == "OK1:7X4MQB2K"
    assert boardcode.human("7X4MQB2K") == "7X4M QB2K"

    for typed in (
        "OK1:7X4MQB2K",
        "7X4M QB2K",
        "7x4m qb2k",
        "ok1-7X4M-QB2K",
        "OK17X4MQB2K",
        "  7X4MQB2K  ",
    ):
        assert boardcode.parse(typed) == "7X4MQB2K", typed

    assert boardcode.parse("0OI1L111") == "00111111"
    for nonsense in ("7X4MQB2U", "WIFI:S:shed;T:WPA;;", "7X4MQB2", "", None, "OK1:"):
        assert boardcode.parse(nonsense) is None, nonsense

    with pytest.raises(DesignError) as refusal:
        boardcode.payload("banana")
    assert refusal.value.code == "library.grid.codeUnreadable"


# --------------------------------------------------------------- the drawing


def test_every_code_is_a_full_qr_of_the_same_size_and_never_a_micro_one():
    """
    The bug that made this module necessary, as a test.

    `segno.make` returns a **Micro** QR for a payload this short: measured,
    `segno.make('OK1:7X4MQB2K')` is M4-Q with 17 modules. OpenCV 5.0.0 decodes that as the
    empty string even from a noise-free render at 12 px per module with a 4-module quiet
    zone — so it is the format and not the resolution, and Chromium's `BarcodeDetector`
    lists no micro variant either. `segno.make_qr` gives 1-Q, 21 modules, 29 with the quiet
    zone, and that was the same for 300 of 300 randomly minted uids: a board code's
    footprint never changes, whichever uid it got.
    """
    control = segno.make(boardcode.payload("7X4MQB2K"), error="m")
    assert control.designator == "M4-Q"
    assert control.designator.startswith("M")

    for _ in range(300):
        code = segno.make_qr(boardcode.payload(boardcode.mint_uid()), error="m")
        assert code.designator == "1-Q"
        assert len(code.matrix) == 21

    assert boardcode.plan(boardcode.mint_uid())["modules"] == 21 + 2 * 4


def test_the_footprint_is_the_size_asked_for_and_the_quiet_zone_is_inside_it():
    """
    18 mm buys 29 modules of 0.6207 mm, of which 4 a side are empty material.

    Measured on the default: module 0.621 mm, quiet zone 2.483 mm a side, so 4.97 mm of the
    18 mm is margin and the pattern itself is 13.03 mm. What that margin buys is measured in
    `boardcode.QUIET_MODULES`, and it is not what an earlier version of this docstring said:
    on a code rendered with nothing around it, no quiet zone never decodes (0 of 20 at 3, 6
    and 12 px per module) where two and four both read 20 of 20 at 6 — and on a plank, even
    no quiet zone reads 20 of 20, because the unburned wood is the quiet zone. It is the
    margin that keeps the caption and the squares out of the pattern.

    The footprint is what the board reserves, so nothing may stick out of it: every square
    lies inside the size asked for, and none of them lies in the quiet zone.
    """
    code = boardcode.plan("7X4MQB2K", 10.0, 20.0, 18.0)
    assert code["modules"] == 29
    assert code["module_mm"] == pytest.approx(0.6207, abs=0.0005)
    assert code["quiet_mm"] == pytest.approx(2.483, abs=0.001)
    assert (code["modules"] - 2 * code["quiet"]) * code["module_mm"] == pytest.approx(
        13.03, abs=0.01
    )

    xs = [x for square in code["squares"] for x, _ in square]
    ys = [y for square in code["squares"] for _, y in square]
    inner = code["quiet"] * code["module_mm"]
    assert min(xs) == pytest.approx(10.0 + inner, abs=0.001)
    assert min(ys) == pytest.approx(20.0 + inner, abs=0.001)
    assert max(xs) <= 10.0 + 18.0 - inner + 1e-9
    assert max(ys) <= 20.0 + 18.0 - inner + 1e-9


def test_the_modules_are_area_and_not_outline():
    """
    One closed square per dark module, tiling exactly, adding up to the area it should.

    Area rather than a line, because an engrave layer traces geometry and never consults
    fill (`meerk40t/core/node/op_engrave.py:358+`), and 212 traced module outlines with
    unburned wood inside each one is not something a scanner reads. The dark count varies
    with the uid — measured over 500 minted uids, 202 to 242 of the 441 — and `7X4MQB2K` is
    212 of them.
    """
    code = boardcode.plan("7X4MQB2K")
    assert code["dark"] == 212
    assert len(code["squares"]) == 212
    assert all(len(square) == 4 for square in code["squares"])

    module = code["module_mm"]
    for square in code["squares"]:
        xs = sorted({round(x, 6) for x, _ in square})
        ys = sorted({round(y, 6) for _, y in square})
        assert len(xs) == len(ys) == 2
        assert xs[1] - xs[0] == pytest.approx(module, abs=1e-6)
        assert ys[1] - ys[0] == pytest.approx(module, abs=1e-6)

    corners = {(round(min(x for x, _ in s), 6), round(min(y for _, y in s), 6))
               for s in code["squares"]}
    assert len(corners) == 212, "two modules on the same spot would be one dark module"


def test_a_code_too_small_to_read_is_refused_and_a_small_one_says_so():
    """
    Under 12 mm: refused. Under 14 mm: drawn, with the numbers in a warning.

    At 5 px per module — a resolution that read 40 of 40 on a simulated board photograph —
    an 18 mm code wants a 300 mm board photographed at 2400 px across, a 14 mm code 3100 px
    and a 12 mm code 3600. Below 12 mm the module is 0.41 mm, two kerfs, and the laser would
    be deciding where the module edges are. That is 7 s of burn time for a board that still
    cannot say who it is, so it is a refusal and not a warning.
    """
    with pytest.raises(DesignError) as refusal:
        boardcode.plan("7X4MQB2K", size_mm=11.0)
    assert refusal.value.code == "library.grid.codeTooSmall"
    assert refusal.value.values == {"min_mm": 12.0, "asked_mm": 11.0}

    small = boardcode.plan("7X4MQB2K", size_mm=13.0)
    assert [w["code"] for w in small["warnings"]] == ["boardcode.smallCode"]
    assert small["warnings"][0]["values"]["module_mm"] == pytest.approx(0.448, abs=0.001)
    assert boardcode.plan("7X4MQB2K")["warnings"] == []


# --------------------------------------------------------------- reading back


@needs_cv2
def test_the_planned_code_reads_back_as_the_board_it_names():
    """
    The whole promise, end to end: mint, plan, render the millimetres, read the uid.

    Not the payload string put through a decoder — the geometry that would go to the
    laser, rendered at 12 px per module and read by the same code the photo route uses. The
    control underneath is the bug: the same payload through `segno.make` renders just as
    cleanly and decodes as nothing at all.
    """
    import cv2

    for _ in range(5):
        uid = boardcode.mint_uid()
        code = boardcode.plan(uid)
        picture = render(code, px_per_mm=12 / code["module_mm"])
        assert boardcode.read(picture) == [uid]

    micro = segno.make(boardcode.payload("7X4MQB2K"), error="m")
    matrix = [[1 if cell else 0 for cell in row] for row in micro.matrix]
    quiet, px = 4, 12
    side = (len(matrix) + 2 * quiet) * px
    canvas = np.full((side, side), 255, dtype=np.uint8)
    for row, cells in enumerate(matrix):
        for column, dark in enumerate(cells):
            if dark:
                top, left = (row + quiet) * px, (column + quiet) * px
                canvas[top : top + px, left : left + px] = 0
    assert cv2.QRCodeDetector().detectAndDecode(canvas)[0] == ""
    assert boardcode.read(canvas) == []


@needs_cv2
def test_a_code_photographed_on_a_plank_still_names_its_board():
    """
    The code where the failure was measured: on a board, with the board's own squares.

    An 18 mm code on a 300 mm board, turned 5 degrees, blurred, noised and JPEG 85. Through
    `read` — Aruco first, then a 2x retry — this harness measured 40 of 40 at 2000, 2400 and
    3200 px across (4.1, 5.0 and 6.6 px per module), 16 of 40 at 1600 px and 0 of 40 at
    1200 px. So 1600 px, which is the size a shared contribution keeps, is the one rung that
    half works: that is why the upload and never the stored copy is what gets decoded.

    The detector order is load bearing on a photograph and only there — the plain detector
    read 1 of 20 at 5.0 px per module where Aruco read 19 — and the reason is the photograph
    and not the board's own squares, which
    `test_it_is_the_photograph_and_not_the_boards_own_squares` measures.
    """
    uid = boardcode.mint_uid()
    code = boardcode.plan(uid)
    for seed in range(4):
        assert boardcode.read(on_a_board(code, 2400, seed=seed)) == [uid], seed

    tiny = boardcode.read(on_a_board(code, 900, seed=0))
    assert tiny == [], "a code this small in the frame must come back empty, not wrong"


@needs_cv2
def test_it_is_the_photograph_and_not_the_boards_own_squares():
    """
    The plain detector was blamed for losing the code among the board's own dark squares.

    It does lose it — but not to the squares. Measured on this harness with twenty uids per
    cell at 2400 px across (5.0 px per module), the plain detector read 1 of 20 with the
    sixteen squares in frame and 0 of 20 with them taken out, while Aruco read 18 of 20 and
    19 of 20. Take the *photograph* away instead — the same plank, unturned, unblurred,
    uncompressed, squares and all — and the plain detector reads 59 of 60.

    So the detector order in `_detectors` earns its place on a photograph and nowhere else,
    and the module docstring may not explain it by the squares. Six uids here rather than
    twenty, and thresholds rather than exact counts: at 1 in 20 and 59 in 60 a six-sample
    run of a random uid legitimately lands one either way, and a test that fails one run in
    thirty teaches people to rerun it.
    """
    plain, without, clean = 0, 0, 0
    for seed in range(6):
        uid = boardcode.mint_uid()
        code = boardcode.plan(uid)
        plain += uid in _with("QRCodeDetector", on_a_board(code, 2400, seed=seed))
        without += uid in _with(
            "QRCodeDetector", on_a_board(code, 2400, seed=seed, squares=False)
        )
        clean += uid in _with(
            "QRCodeDetector", on_a_board(code, 2400, seed=seed, photo=False)
        )
        # And the detector that is asked first does read the photograph, which is the
        # whole reason it is asked first.
        assert boardcode.read(on_a_board(code, 2400, seed=seed)) == [uid], seed

    assert clean >= 5, ("without the photograph the plain detector reads them", clean)
    assert plain <= 2 and without <= 2, (plain, without)
    # The claim itself: taking the squares out does not help the plain detector.
    assert abs(plain - without) <= 2, (plain, without)


def _with(name: str, image) -> list[str]:
    """One named OpenCV detector on one picture, the way `_decode` asks it."""
    import cv2

    picture = boardcode._as_grey(cv2, image)
    detector = getattr(cv2, name)()
    ok, decoded = detector.detectAndDecodeMulti(picture)[:2]
    texts = [str(t) for t in (decoded or []) if t] if ok else []
    if not texts:
        single = detector.detectAndDecode(picture)[0]
        texts = [str(single)] if single else []
    return [u for u in (boardcode.parse(t) for t in texts) if u]


@needs_cv2
def test_a_photograph_that_names_nothing_and_one_that_names_two_boards():
    """
    Reading is never an error: no code, a foreign code and two codes all come back as data.

    A photograph of a thumb, a Wi-Fi sticker on the wall behind the bench, or two boards
    lying next to each other — the caller decides what to do with that (the picker, or the
    refusal that a code names a different board). This function only ever answers with the
    board uids it saw.
    """
    assert boardcode.read(np.full((400, 400), 220, dtype=np.uint8)) == []
    assert boardcode.read(b"") == []
    assert boardcode.read(b"this is not a picture") == []

    stranger = segno.make_qr("WIFI:S:shed;T:WPA;P:hunter2;;", error="m")
    matrix = [[1 if cell else 0 for cell in row] for row in stranger.matrix]
    quiet, px = 4, 10
    side = (len(matrix) + 2 * quiet) * px
    canvas = np.full((side, side), 255, dtype=np.uint8)
    for row, cells in enumerate(matrix):
        for column, dark in enumerate(cells):
            if dark:
                canvas[(row + quiet) * px : (row + quiet + 1) * px,
                       (column + quiet) * px : (column + quiet + 1) * px] = 0
    assert boardcode.read(canvas) == []

    first, second = boardcode.mint_uid(), boardcode.mint_uid()
    left = render(boardcode.plan(first), px_per_mm=12 / boardcode.plan(first)["module_mm"])
    right = render(boardcode.plan(second), px_per_mm=12 / boardcode.plan(second)["module_mm"])
    pair = np.full((left.shape[0], left.shape[1] * 2 + 40), 255, dtype=np.uint8)
    pair[:, : left.shape[1]] = left
    pair[:, left.shape[1] + 40 :] = right
    assert sorted(boardcode.read(pair)) == sorted([first, second])


def test_without_opencv_reading_says_nothing_rather_than_raising(monkeypatch):
    """
    OpenCV is an optional extra and must not become a dependency of this app.

    Without it the board still burns its code and the printed line under it still works —
    only the reading back is gone, and that degrades to the picker. So `read` answers `[]`
    and `available()` is False; the sentence a user sees is the caller's
    (`NO_DECODER_HINT`), because only the caller knows what was asked for.
    """
    monkeypatch.setattr(boardcode, "_opencv", lambda: None)
    assert boardcode.available() is False
    assert boardcode.read(b"anything at all") == []
    assert boardcode.read(np.full((10, 10), 255, dtype=np.uint8)) == []
    assert "opencv-python-headless" in boardcode.NO_DECODER_HINT


# --------------------------------------------------------------- what it costs


def test_the_modules_burn_as_one_raster_and_not_as_eight_hundred_outlines(
    kernel, tmp_path
):
    """
    What a code costs a job, measured through the engine's own plan.

    The squares are filled area, and that is the difference between a code and a decoration.
    Measured here on a headless kernel at the caption layer's 80 mm/s, an 18 mm code:

    | layer                 | cut objects | seconds |
    |-----------------------|-------------|---------|
    | `op raster` @ 167 dpi | 1           | 15.8    |
    | `op engrave`          | 848         | 7.9     |

    Faster is not better: those 848 are the four sides of each of 212 modules, traced,
    because `op_engrave.as_cutobjects` (`meerk40t/core/node/op_engrave.py:358+`) never
    consults fill. The wood inside every module stays unburned and no scanner reads the
    result. The same code left at the engine's 500 dpi default measured 46.4 s — on a board
    that takes 57 to 60 s — which is why `CODE_DPI` is pinned in this module; the ceiling
    below fails a regression back to it.
    """
    from meerk40t.svgelements import Color

    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "boardcode.db")
    elements = kernel.elements
    assert server.drawing.engine_report()["raster"], "our own rasteriser has to be there"
    # The same switch `testgrid._draw_cells` throws: without it the engine also classifies
    # every square into a layer of its own and the plan holds each module twice.
    elements.classify_new = False
    code = boardcode.plan("7X4MQB2K", 10.0, 10.0)

    def plan_with(op_type, **extra):
        for node in list(elements.elems()):
            node.remove_node(children=True, destroy=True)
        for op in list(elements.ops()):
            op.remove_node()
        operation = elements.op_branch.add(
            type=op_type, speed=80.0, power=300, **extra
        )
        for square in code["squares"]:
            left = min(x for x, _ in square)
            top = min(y for _, y in square)
            width = max(x for x, _ in square) - left
            height = max(y for _, y in square) - top
            before = {id(n) for n in elements.elems()}
            kernel.console(f"rect {left}mm {top}mm {width}mm {height}mm\n")
            node = next(n for n in elements.elems() if id(n) not in before)
            node.fill = Color("black")
            operation.add_reference(node)
        server.commands.run("plan clear copy preprocess validate blob preopt optimize")
        kinds: dict[str, int] = {}
        seconds = 0.0
        for item in kernel.planner.default_plan.plan:
            for cut in item:
                kinds[type(cut).__name__] = kinds.get(type(cut).__name__, 0) + 1
            for name in ("duration_cut", "duration_travel"):
                seconds += float(getattr(item, name)())
        server.commands.run("plan clear")
        return kinds, seconds

    kinds, seconds = plan_with("op raster", dpi=boardcode.CODE_DPI)
    assert kinds == {"RasterCut": 1}
    assert seconds == pytest.approx(15.8, abs=1.5)
    assert seconds < 20.0, "a slip back to 500 dpi measured 46.4 s"

    kinds, engraved = plan_with("op engrave")
    assert kinds == {"LineCut": 212 * 4}
    assert engraved < seconds, "and it is still the wrong layer: outlines, no area"
