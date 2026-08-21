"""
De plan-bewerkers en de lopende tegelreeks.

The premise of all these tests: whatever happens in the plan, the user's element tree comes
out unchanged.
"""

import pytest

from openkerf_api.commands import PLAN_AND_SPOOL, CommandRunner
from openkerf_api.tiling import Alignment, Point, Rect
from openkerf_api.tilerun import TileMutator, marker_geometry

UNITS_PER_MM = 65535 / 25.4


def test_a_plain_job_still_takes_the_single_line_route(kernel):
    """
    Without mutators it stays one line. That path is walked on every job and deserves no
    detour for a feature most people do not use.

    It is tested against the constant and not against a written-out line: that line contains
    `clear`, and *why* that is there is an expensive lesson (without clear every start piles
    the same work onto the plan again). A test literal imitating the constant will sooner or
    later drift out of step with the original, and then the test is a trap instead of a safety
    net.
    """
    runner = CommandRunner(kernel)
    gedraaid = []
    runner.run = lambda regel: gedraaid.append(regel) or []

    runner._plan_and_spool()

    assert gedraaid == [PLAN_AND_SPOOL]


def test_a_mutator_gets_the_plan_steps_and_can_replace_them(kernel):
    runner = CommandRunner(kernel)
    gezien = {}

    def bewerker(steps):
        gezien["aantal"] = len(steps)
        return list(steps)

    kernel.console("rect 0 0 10mm 10mm\n")
    kernel.console("classify\n")
    runner._plan_and_spool(mutators=[bewerker])

    assert "aantal" in gezien


def _wide_sheet(server):
    """
    A board of 800 × 150 mm on the dummy bed, with tiling on.

    That size is not arbitrary: the dummy device has a bed of 320 × 220 mm (measured, not the
    500 × 300 you would expect), so the usable window is 300 mm and this board becomes exactly
    three tiles. Choose 900 and it becomes four and the tests fall over for a reason that has
    nothing to do with tiling.
    """
    sheet = server.sheets.state()["sheets"][0]
    server.sheets.update(sheet["id"], width_mm=800.0, height_mm=150.0)
    server.sheets.update(sheet["id"], tiling={"enabled": True})
    server.kernel.console("rect 10mm 10mm 30mm 30mm\n")
    server.kernel.console("rect 600mm 10mm 30mm 30mm\n")
    server.kernel.console("classify\n")


def test_a_run_survives_a_restart_but_its_alignment_does_not(kernel, tmp_path):
    """
    The series is hours of work and survives a shutdown. The alignment does not: it says
    where the board lay, and after a break you no longer know that.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    run = server.tiles
    _wide_sheet(server)
    run.start()
    run.align([{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner")
    assert run.state()["aligned"] is True

    opnieuw = ApiServer(kernel, library_path=tmp_path / "v.db").tiles

    assert opnieuw.state()["current"] == 0
    assert opnieuw.state()["aligned"] is False


def test_the_fingerprint_is_the_same_in_a_fresh_process(kernel, tmp_path):
    """
    The fingerprint goes to disk and is compared after a restart, so it has to have the same
    value outside this process.

    That sounds obvious and is not: Python salts the hash of strings per process, so a
    fingerprint from `hash()` comes back different after every restart and declares every
    resumed series invalid — precisely the case the series is stored for. A test that makes two
    servers in the same process sees nothing of it; only a genuinely second process does.
    """
    import subprocess
    import sys

    tekst = "|".join(["800.0x150.0", '{"enabled": true}', "elem rect:10-10-40-40"])
    script = "import hashlib;" f"print(hashlib.sha1({tekst!r}.encode()).hexdigest())"
    eerste = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    ).stdout
    tweede = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    ).stdout

    assert eerste == tweede != ""


def test_the_fingerprint_is_a_digest_and_not_a_process_hash(kernel, tmp_path):
    """
    Together with the test above this closes the chain: sha1 is stable across processes, and
    the fingerprint *is* a sha1 digest.

    Forty hex digits is the proof. `str(hash(...))` is a decimal number and fails here at once
    — and that is exactly the fault this has to catch, because without this test it only came
    out after a restart, as a series declaring itself invalid for no reason.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    sheet = server.sheets.state()["sheets"][0]

    afdruk = server.tiles._fingerprint(sheet)

    assert len(afdruk) == 40
    assert all(teken in "0123456789abcdef" for teken in afdruk)
    assert afdruk == server.tiles._fingerprint(sheet)


def test_a_run_whose_sheet_is_deleted_expires_gracefully(kernel, tmp_path):
    """
    Het sheet weggooien terwijl er een reeks loopt.

    What actually happens then is not "no sheet any more": `Sheets.remove` activates another
    sheet first and only then throws the old one away, and there is always exactly one active
    sheet. The series belongs to a sheet that no longer exists, so it lapses — and that is
    exactly right.

    What this test pins down is that you get that back as a state, and that both burning and
    aligning then refuse neatly with *that* explanation, not with a message from the depths
    about sheets while you are tapping a mark.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    sheet = server.sheets.state()["sheets"][0]
    server.sheets.add(name="Ander sheet")
    server.sheets.remove(sheet["id"])

    state = server.tiles.state()
    assert state["stale"] is True
    assert state["message"]

    for call in (
        lambda: server.tiles.burn(),
        lambda: server.tiles.align(
            [{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner"
        ),
    ):
        with pytest.raises(DesignError) as error:
            call()
        # The series explains that it has lapsed. A bare "There is no active sheet." would
        # answer the wrong question here.
        assert str(error.value) == state["message"]


def test_changing_the_design_invalidates_a_running_series(kernel, tmp_path):
    """
    Burning half the old design and half the new one is the most expensive mistake this
    system can make. So: invalid, and visibly so.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    kernel.console("rect 500mm 100mm 20mm 20mm\n")
    kernel.console("classify\n")

    state = server.tiles.state()
    assert state["stale"] is True
    assert "design" in state["message"].lower()


def test_burning_without_alignment_is_refused(kernel, tmp_path):
    from openkerf_api.server import ApiServer
    from openkerf_api.edits import DesignError

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    with pytest.raises(DesignError) as error:
        server.tiles.burn()

    # On "aligned" and not on "align": and on "marks", because a refusal that does not say
    # what to do about it is a refusal the user has no use for.
    message = str(error.value).lower()
    assert "aligned" in message
    assert "marks" in message


def _design(kernel):
    """Twee vierkanten: één left op de plaat, één right."""
    kernel.console("rect 10mm 10mm 30mm 30mm\n")
    kernel.console("rect 300mm 10mm 30mm 30mm\n")
    kernel.console("classify\n")


def _shapes(steps):
    """
    De shapes in een bewerkt plan.

    Through `build_plan` and not through a whole `plan` line: `blob` replaces the operations
    with one `CutCode`, and then nothing can be established about the clipping.
    """
    return [c for step in steps for c in getattr(step, "children", []) or []]


def test_only_what_lies_in_the_tile_survives(kernel):
    _design(kernel)
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
    )

    steps = runner.build_plan([mutator])

    assert len(_shapes(steps)) == 1


def test_the_users_tree_is_untouched_after_spooling(kernel):
    """
    The most important test of this design. The plan may be mangled, the design may not —
    otherwise the user loses work to a job.
    """
    _design(kernel)
    voor = [
        (n.type, tuple(round(v, 3) for v in n.bounds)) for n in kernel.elements.elems()
    ]
    runner = CommandRunner(kernel)

    runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, -100.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    na = [
        (n.type, tuple(round(v, 3) for v in n.bounds)) for n in kernel.elements.elems()
    ]
    assert na == voor


def test_the_alignment_shift_moves_the_tile_into_the_bed(kernel):
    """
    Tile 2 is at x=300 on the board, but after shifting the board it lies at x=100 under the
    head. The plan has to contain that last one.
    """
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(200, 0, 400, 200),
                alignment=Alignment(0.0, -200.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    shapes = _shapes(steps)
    assert len(shapes) == 1
    assert shapes[0].bounds[0] / UNITS_PER_MM == pytest.approx(100.0, abs=0.5)


def test_the_mutator_counts_what_it_actually_burns(kernel):
    """
    `burned_length_units` is the number task 12's coverage test rests on: there it is summed
    over all the tiles and compared with the whole design. If it counts what is not burned, or
    counts twice, that test goes green while all sorts of things go wrong. So it is pinned down
    here against a shape whose outline we can compute by hand.
    """
    kernel.console("rect 10mm 10mm 30mm 20mm\n")
    kernel.console("classify\n")
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
    )

    runner.build_plan([mutator])

    omtrek_mm = 2 * (30 + 20)
    assert mutator.burned_length_units / UNITS_PER_MM == pytest.approx(
        omtrek_mm, rel=1e-3
    )


def test_a_picture_belongs_to_one_tile_and_is_not_repeated(kernel):
    """
    An image has no geometry to clip, so it comes along as a whole or not at all. Without
    that test a photo ended up in *every* tile — in the wrong place, with the full burn time,
    and that again per tile.
    """
    from meerk40t.core.node.elem_image import ImageNode
    from meerk40t.svgelements import Matrix
    from PIL import Image

    picture = ImageNode(
        image=Image.new("L", (20, 20), 0),
        matrix=Matrix.translate(20 * UNITS_PER_MM, 20 * UNITS_PER_MM),
        dpi=500,
    )
    kernel.elements.elem_branch.add_node(picture)
    # As a console command `classify` only classifies what is emphasised; this image has
    # never been selected (unlike a shape drawn through `rect`). Calling it directly gets
    # around that.
    kernel.elements.classify([picture])
    runner = CommandRunner(kernel)

    binnen = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )
    buiten = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(400, 0, 600, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    assert any(c.type == "elem image" for c in _shapes(binnen))
    assert not any(c.type == "elem image" for c in _shapes(buiten))


def test_an_operation_that_ends_up_empty_leaves_the_plan(kernel):
    """A layer that no longer does anything does not belong in the job."""
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(600, 600, 800, 800),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    assert not [s for s in steps if getattr(s, "children", None)]


def test_a_mark_is_a_circle_with_a_cross_in_it(kernel):
    """
    The circle gives an edge to aim the head at that a bare cross does not have; the cross
    gives the centre you tap.

    The circle is exactly the requested size. The *mark* is larger, because a digit sits beside
    it — that size is in `mark_footprint`, because only the finder has to know it. Across the
    long axis nothing changes, and that is deliberate: the overlap width is the tight measure.
    """
    geom = marker_geometry([Point(100.0, 50.0)], size_mm=8.0, units_per_mm=UNITS_PER_MM)

    x0, y0, x1, y1 = geom.bbox()
    # Without a zone the digit is below it (the ordinary state, a narrow zone), so the width
    # is the circle's and the height is not.
    assert (x1 - x0) / UNITS_PER_MM == pytest.approx(8.0, abs=0.1)
    assert (y1 - y0) / UNITS_PER_MM > 8.0


def test_the_marks_are_burned_last(kernel):
    """
    Burning earlier means a later cut can still run through it, and then you align on a mark
    that is half gone.
    """
    _design(kernel)
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
        marker_geometry=marker_geometry(
            [Point(180.0, 20.0), Point(180.0, 180.0)], 8.0, UNITS_PER_MM
        ),
    )

    steps = runner.build_plan([mutator])

    laatste = [s for s in steps if getattr(s, "children", None)][-1]
    assert laatste.label == "Alignment marks"
    assert len(laatste.children) == 1


def test_a_tile_whose_marks_fall_off_the_bed_is_refused(kernel, tmp_path):
    """
    The marks lie in the overlap zone and therefore outside the burn area. A check that only
    looks at the burn area lets a tile through whose marks would be burned beside the bed — the
    head against its end stop, with material in the machine.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()
    # So far to the right that the burn area still fits and the marks do not.
    server.tiles.align([{"x_mm": 30.0, "y_mm": 0.0}], reference="plate_corner")

    with pytest.raises(DesignError) as error:
        server.tiles.burn()

    assert "outside the bed" in str(error.value)


def test_burning_the_same_tile_twice_asks_first(kernel, tmp_path):
    """
    Burning again is allowed — you have to be able to redo an aborted job — but not by
    accident. The second time the laser goes over work that is already there.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()
    server.tiles.align([{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner")
    server.tiles.burn()

    with pytest.raises(DesignError) as error:
        server.tiles.burn()
    assert "already been burned" in str(error.value)

    # With confirmation it is allowed.
    assert server.tiles.burn(confirm_reburn=True)["burned_length_mm"] > 0


def test_the_last_tile_burns_no_marks(kernel):
    """No next tile, so nothing to align on — and so no mark."""
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
                marker_geometry=None,
            )
        ]
    )

    assert not [s for s in steps if getattr(s, "label", None) == "Alignment marks"]


def test_the_shift_puts_the_marks_on_the_bed(kernel, tmp_path):
    """
    After the stated shift the marks have to lie on the bed.

    This is the property, not the sum — and it was found with a screenshot, not with a test.
    The panel computed the shift from the *burn areas*, and those sit half an overlap further
    apart than the windows. Measured on a board of 500 mm with a bed of 235: with the burn step
    (178.75 mm) the marks land at bed-x −31.5 and 28.5, so the first lies off the bed and
    cannot be tapped. The instruction sent the operator too far and then asked them to point
    out a mark that was no longer there.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    layout = server.tiles.layout()
    bed = server.drawing.bed_mm()

    assert layout["tiles"][0]["shift_mm"] is None, "the first tile does not shift"

    for grens, mark in enumerate(layout["marks"]):
        verschuiving = layout["tiles"][grens + 1]["shift_mm"]
        assert verschuiving is not None
        for punt in mark["points"]:
            x = punt["x_mm"] - verschuiving["x"]
            y = punt["y_mm"] - verschuiving["y"]
            assert 0 <= x <= bed[0], f"mark op bed-x {x:.1f} valt buiten 0..{bed[0]}"
            assert 0 <= y <= bed[1], f"mark op bed-y {y:.1f} valt buiten 0..{bed[1]}"


def _hoog_vel(server):
    """
    A board that is only too *tall*: 200 × 500 mm on the dummy bed.

    This is the direction a machine without side feed needs — you push the board forwards or
    backwards, not sideways. Not a single test used it, while it is half the possible
    divisions.
    """
    sheet = server.sheets.state()["sheets"][0]
    server.sheets.update(sheet["id"], width_mm=200.0, height_mm=500.0)
    server.sheets.update(sheet["id"], tiling={"enabled": True})
    # A shape covering the *whole* overlap zone of the first seam (which runs from 142.5 to
    # 215), so that there is no crossing-free position to move to. A shape that only partly
    # touches the zone is neatly avoided by the seam shifter — that is the intention, but then
    # it counts zero and you are testing nothing.
    server.kernel.console("rect 40mm 120mm 100mm 120mm\n")
    server.kernel.console("classify\n")


def test_a_plate_that_is_only_too_tall_splits_into_bands(kernel, tmp_path):
    """
    The division direction follows the sheet: too tall gives bands, not columns.

    That is not a detail for anybody with a machine without side feed — then this is the only
    direction in which they can shift a board.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _hoog_vel(server)

    layout = server.tiles.layout()

    assert len(layout["tiles"]) > 1
    assert {t["row"] for t in layout["tiles"]} == set(range(len(layout["tiles"])))
    assert {t["column"] for t in layout["tiles"]} == {0}
    # The burn areas lie above each other and touch, just as with columns.
    for upper, lower in zip(layout["tiles"], layout["tiles"][1:]):
        assert upper["burn"]["y1_mm"] == pytest.approx(lower["burn"]["y0_mm"])
        assert upper["burn"]["x0_mm"] == lower["burn"]["x0_mm"]


def test_a_band_shifts_along_its_own_axis(kernel, tmp_path):
    """The shift should be in y, not in x."""
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _hoog_vel(server)

    layout = server.tiles.layout()

    assert layout["tiles"][0]["shift_mm"] is None
    stap = layout["tiles"][1]["shift_mm"]
    assert stap["x"] == pytest.approx(0.0)
    assert stap["y"] > 0


def test_the_marks_of_a_band_lie_side_by_side(kernel, tmp_path):
    """
    With bands the overlap zone is wide and low, so the marks lie *beside* each other. The
    further apart, the more accurate the angle — and here that means: along the width of the
    board.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _hoog_vel(server)

    marks = server.tiles.layout()["marks"][0]["points"]

    width = abs(marks[1]["x_mm"] - marks[0]["x_mm"])
    height = abs(marks[1]["y_mm"] - marks[0]["y_mm"])
    assert width > height, "marks should lie along the zone's long axis"
    assert width > 100


def test_crossings_are_counted_on_the_axis_that_was_split(kernel, tmp_path):
    """
    The number of shapes cut through was counted only on x, so with bands zero came out while
    something was indeed being cut in half. This design has a shape lying across the first
    seam, so zero is the wrong answer here.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _hoog_vel(server)

    layout = server.tiles.layout()

    seam = layout["tiles"][0]["burn"]["y1_mm"]
    assert 120.0 < seam < 240.0, "the seam should run through the shape"
    assert layout["crossings"] >= 1


def test_burn_regions_stay_contiguous_after_a_seam_is_nudged(kernel, tmp_path):
    """
    In the column direction too the burn areas must leave no gap after a seam has moved.

    This is the same fault as with the bands, approached from the other side: every seam
    touches two tiles, so the middle one is written twice. Here there is one shape that only
    *partly* covers the first overlap zone, so that the seam moves to it and the second seam
    stays put — precisely the state in which
    het gat zichtbaar werd.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    sheet = server.sheets.state()["sheets"][0]
    # 800 mm on the 320 dummy bed gives three tiles, and therefore a middle one that is
    # written twice — with two tiles the fault does not exist.
    server.sheets.update(sheet["id"], width_mm=800.0, height_mm=150.0)
    server.sheets.update(sheet["id"], tiling={"enabled": True})
    # This shape lies in the middle *of* the first overlap zone (250-300), so across the
    # midpoint 275, with free space on both sides. Only *then* does the seam really move — a
    # shape that covers the zone entirely leaves it at the middle, and then the double-write
    # fault does not occur and this test proves nothing. That is the trap the first version
    # fell into.
    server.kernel.console("rect 265mm 20mm 20mm 60mm\n")
    server.kernel.console("classify\n")

    tiles = server.tiles.layout()["tiles"]

    assert len(tiles) == 3
    assert tiles[0]["burn"]["x0_mm"] == pytest.approx(0.0)
    assert tiles[-1]["burn"]["x1_mm"] == pytest.approx(800.0)
    for left, right in zip(tiles, tiles[1:]):
        assert left["burn"]["x1_mm"] == pytest.approx(right["burn"]["x0_mm"]), (
            "een gat of overlap tussen twee brandgebieden: geometrie ertussen "
            "wordt nooit gebrand, of tweemaal"
        )


def test_bands_stay_contiguous_after_a_seam_is_nudged(kernel, tmp_path):
    """
    The same in the band direction, and this is the test that found the gap.

    The shape lies in the middle of the first overlap zone, so that the seam moves to it.
    Without that shift the fault stays invisible.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    sheet = server.sheets.state()["sheets"][0]
    server.sheets.update(sheet["id"], width_mm=200.0, height_mm=500.0)
    server.sheets.update(sheet["id"], tiling={"enabled": True})
    server.kernel.console("rect 40mm 168mm 100mm 14mm\n")
    server.kernel.console("classify\n")

    tiles = server.tiles.layout()["tiles"]

    assert len(tiles) == 3
    assert tiles[0]["burn"]["y1_mm"] != pytest.approx(
        175.0
    ), "the seam should have moved; without a shift this test tests nothing"
    assert tiles[0]["burn"]["y0_mm"] == pytest.approx(0.0)
    assert tiles[-1]["burn"]["y1_mm"] == pytest.approx(500.0)
    for upper, lower in zip(tiles, tiles[1:]):
        assert upper["burn"]["y1_mm"] == pytest.approx(lower["burn"]["y0_mm"]), (
            "gat of overlap tussen twee banden: wat ertussen ligt wordt nooit "
            "gebrand, of tweemaal"
        )


# ------------------------------------------------------- genummerde marks


def test_a_digit_is_one_continuous_stroke_of_the_asked_size():
    """
    The digits are drawn ourselves, not through a font.

    Two glyphs is too few to pull in font machinery for — and besides, `linetext` drags the
    trap along that *every* text placement overwrites `last_font` (see CLAUDE.md). One
    continuous stroke per digit is also the most comfortable for a laser.
    """
    from openkerf_api.tilerun import digit_geometry

    for digit in (1, 2):
        geom = digit_geometry(digit, 0.0, 0.0, 6.0)
        assert geom.index >= 2, "a digit consists of more than one stroke"
        x0, y0, x1, y1 = geom.bbox()
        assert y1 - y0 == pytest.approx(6.0, rel=1e-6)
        assert 0 < x1 - x0 <= 6.0


def test_the_two_digits_are_not_the_same_shape():
    """Otherwise there would be no point: the difference is the whole point."""
    from openkerf_api.tilerun import digit_geometry

    een = digit_geometry(1, 0.0, 0.0, 6.0)
    twee = digit_geometry(2, 0.0, 0.0, 6.0)

    def lengte(g):
        return sum(abs(g.length(i)) for i in range(g.index))

    assert lengte(een) != pytest.approx(lengte(twee), rel=0.05)


def test_a_burned_mark_carries_its_number(kernel):
    """
    The number has to be on the board, not only on the screen.

    Without a burned digit "jog to mark 1" is unusable: then there are two identical circles
    and the word for a position we did away with is still the only thing to go by. This test
    measures that the geometry of two marks is *more* than the same circle twice.
    """
    from openkerf_api.tilerun import marker_geometry
    from openkerf_api.tiling import Point

    een = marker_geometry([Point(100.0, 20.0)], 8.0, UNITS_PER_MM)
    twee = marker_geometry([Point(100.0, 20.0), Point(100.0, 180.0)], 8.0, UNITS_PER_MM)

    # Two marks are more than one mark twice: a digit is added per mark.
    assert twee.index > 2 * een.index


def test_a_mark_reserves_room_for_its_digit(kernel):
    """
    The free-place finder has to count the digit, otherwise it lands on the work — and then
    the mark itself is still free but its label is not.
    """
    from openkerf_api.tiling import Rect, marker_spots

    # A landscape zone with room for several marks, so that the finder really chooses instead
    # of refusing.
    zone = Rect(0.0, 0.0, 60.0, 14.0)
    een, twee = marker_spots(zone, [], size_mm=8.0)

    from openkerf_api.tiling import mark_footprint

    for punt in (een, twee):
        vak = mark_footprint(punt, 8.0, zone)
        assert zone.x0 <= vak.x0 and vak.x1 <= zone.x1, "digit valt buiten de zone"
        assert zone.y0 <= vak.y0 and vak.y1 <= zone.y1
