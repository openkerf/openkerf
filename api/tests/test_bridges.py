"""
Bridges (tabs) in a cut line: the gaps that keep a part in the sheet.

Two halves are tested apart from each other, because they fail apart. The engine already
cuts the gaps (`final_geometry` + `Geomstr.wobble_tab`), so the plan and the time need
nothing from us; what needs us is the picture on the bed, the refusals the engine does not
make, and the two SVG parameters without which a saved project comes back broken.
"""

import pytest
from fastapi.testclient import TestClient

from meerk40t.core.units import UNITS_PER_MM

from openkerf_api.bridges import (
    MAX_COUNT,
    bridged_geometry,
    gap_spans,
    parse_positions,
    path_length,
    positions_for,
)
from openkerf_api.design import DesignReader
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    # 60 x 40 mm: a 200 mm perimeter, so a percentage is a round number of millimetres.
    kernel.console("rect 10mm 10mm 60mm 40mm\n")
    kernel.console("element* cut -s 10 -p 60\n")
    return Drawing(kernel)


def element(kernel, index=0):
    return DesignReader(kernel).snapshot()["elements"][index]


def node(kernel, index=0):
    # Ids are handed out by `validate_ids`, which the snapshot calls; a node fresh from the
    # console has none yet, and `_nodes` would then look for `None`.
    kernel.elements.validate_ids()
    return list(kernel.elements.elems())[index]


def ids(kernel):
    kernel.elements.validate_ids()
    return [n.id for n in kernel.elements.elems()]


def engine_length_mm(kernel, index=0):
    """What the machine really travels: the engine's own geometry, gaps and all."""
    geometry = node(kernel, index).final_geometry()
    return path_length(geometry) / UNITS_PER_MM


def our_length_mm(kernel, index=0):
    data = element(kernel, index)["bridges"]["path"]
    from meerk40t.core.geomstr import Geomstr
    from meerk40t.svgelements import Path

    return path_length(Geomstr.svg(Path(data))) / UNITS_PER_MM


# ------------------------------------------------------------------ the arithmetic


def test_a_count_spreads_the_bridges_the_way_the_engine_does():
    """`"*4"` is `(i + 0.5) * 100 / 4` in the engine (fill/fills.py:565)."""
    assert positions_for(4) == [12.5, 37.5, 62.5, 87.5]
    assert positions_for(1) == [50.0]


def test_the_position_string_is_read_back_the_way_the_engine_reads_it():
    assert parse_positions("*4") == [12.5, 37.5, 62.5, 87.5]
    assert parse_positions("10, 50 90") == [10.0, 50.0, 90.0]
    # Clamped, like fills.py:582-585, and unreadable pieces dropped.
    assert parse_positions("-5, 120, zes") == [0.0, 100.0]
    for silent in ("", "*0", "*abc", "abc", f"*{MAX_COUNT + 1}"):
        assert parse_positions(silent) == [], silent


def test_a_bridge_over_the_seam_wraps_round_instead_of_being_clipped():
    """The engine wraps a gap whose start falls before 0 (fills.py:623); so do we."""
    spans = gap_spans(200.0, [0.0], 4.0)

    assert spans == [(0.0, 2.0), (198.0, 200.0)]


def test_overlapping_bridges_become_one_gap():
    assert gap_spans(100.0, [50.0, 51.0], 4.0) == [(48.0, 53.0)]


# ------------------------------------------------------------------ the picture


def test_a_shape_without_bridges_says_so(kernel, drawing):
    bridges = element(kernel)["bridges"]

    assert bridges["count"] == 0
    assert bridges["path"] == ""
    # The engine's own default length, and it is exactly two millimetres.
    assert bridges["length_mm"] == pytest.approx(2.0, abs=0.001)
    assert bridges["path_length_mm"] == pytest.approx(200.0, abs=0.01)


def test_the_snapshot_carves_the_gaps_the_engine_cuts(kernel, drawing):
    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)

    bridges = element(kernel)["bridges"]
    assert bridges["count"] == 4
    assert bridges["positions_percent"] == [12.5, 37.5, 62.5, 87.5]
    # The engine overshoots by exactly one 0.05 mm resample step per gap, so its contour is
    # 0.2 mm shorter than ours over four bridges. Measured: 191.75 against 192.00.
    assert engine_length_mm(kernel) == pytest.approx(191.75, abs=0.01)
    assert our_length_mm(kernel) == pytest.approx(192.0, abs=0.02)


def test_the_carved_path_stays_small_enough_to_poll(kernel, drawing):
    """
    Why we do not simply ship `final_geometry()`.

    `wobble_tab` resamples at 0.05 mm: measured on this rectangle, 3839 segments and
    114,661 characters of `d` against our 8 segments. The snapshot is polled.
    """
    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)

    engine = len(node(kernel).final_geometry().as_path().d())
    ours = len(element(kernel)["bridges"]["path"])

    assert engine > 100_000
    assert ours < 500


def test_the_ideal_contour_is_still_there_for_hit_testing(kernel, drawing):
    """The gaps go in their own path; `path` keeps being the whole shape."""
    before = element(kernel)["path"]

    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)

    after = element(kernel)
    assert after["path"] == before
    assert after["subpaths"] == 1
    assert after["bridges"]["path"].count("M") == 5


def test_a_curve_is_cut_on_its_parameter_and_stays_a_curve(kernel):
    """
    A circle of r = 20 mm: `EllipseNode.as_geometry` draws it as twelve cubics. On these the
    parameter happens to be proportional to arc length (measured: t = 0.5 sits at 50.000 % of
    each segment), so what this pins down is the other half — the pieces stay cubics.
    Nothing is interpolated, where the engine's own answer for the same circle is 2352
    straight segments. `_Ruler` earns its keep on a hard-bent cubic, not on a circle.
    """
    kernel.console("circle 50mm 50mm 20mm\n")
    drawing = Drawing(kernel)
    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)

    data = element(kernel)["bridges"]["path"]

    assert "C" in data and "L" not in data, data
    # Twelve cubics in the ideal circle, sixteen after four gaps: each gap splits the one
    # cubic it lands in. The engine's own answer is 2352 segments for the same circle.
    assert node(kernel).as_geometry().as_path().d().count("C") == 12
    assert data.count("C") == 16
    perimeter = 2 * 3.141592653589793 * 20
    assert our_length_mm(kernel) == pytest.approx(perimeter - 8.0, abs=0.05)


# ------------------------------------------------------------------ the plan


def test_the_cut_plan_carries_the_bridges_without_our_help(kernel, drawing):
    """
    `core/cutplan.py:630` prefers `final_geometry()` for `op cut`, so the estimate drops by
    itself and there is nothing for us to build. Measured through the exact plan on this
    rectangle in a 10 mm/s cut layer: 35.7 s becomes 34.5 s.

    Only the drop is asserted, not the seconds. The absolute number depends on the active
    device's acceleration settings, and those are not isolated per kernel: the same test
    gives 35.7 s on its own and 20.0 s inside the full suite. That is the `-P/--profile`
    hole noted in CLAUDE.md, and it is not this feature's to close. The contour length
    beside it *is* exact, and it is the thing that decides the time.
    """
    before = drawing.estimate(None, None, None, exact=True)
    assert engine_length_mm(kernel) == pytest.approx(200.0, abs=0.01)

    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)
    after = drawing.estimate(None, None, None, exact=True)

    assert engine_length_mm(kernel) == pytest.approx(191.75, abs=0.01)
    assert after["seconds"] < before["seconds"]
    assert after["parts"] == before["parts"] == 1


# ------------------------------------------------------------------ the refusals


def test_a_line_carries_no_bridges(kernel):
    """
    `LineNode.final_geometry` sets `numtabs = 4` and then `numtabs = 0`
    (core/node/elem_line.py:157-159), so tabs on a line are silently ignored. Measured: a
    100 mm line with `"*4"` stays 100.0 mm and one subpath.
    """
    kernel.console("line 10mm 10mm 110mm 10mm\n")
    drawing = Drawing(kernel)

    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], count=4)

    assert caught.value.code == "bridges.notSupported"


def test_zero_bridges_is_a_refusal_and_not_a_silent_nothing(kernel, drawing):
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], count=0, length_mm=2.0)

    assert caught.value.code == "bridges.needsCount"


def test_an_empty_list_of_places_is_a_refusal(kernel, drawing):
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], positions_percent=[])

    assert caught.value.code == "bridges.needsCount"


def test_a_length_of_zero_is_a_refusal(kernel, drawing):
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], count=4, length_mm=0)

    assert caught.value.code == "bridges.needsLength"


def test_bridges_that_would_leave_no_cut_are_refused(kernel, drawing):
    """
    The engine lets this through. Measured: four bridges of 49.9 mm on the 200 mm perimeter
    pass its `len(positions) * tablen < total_length` check and leave 0.15 mm of cut in the
    whole contour — the part is not cut at all.
    """
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], count=4, length_mm=49.9)

    # A refusal with numbers in it keeps its English sentence: the numbers do not fit in the
    # X-OpenKerf-Error header, and a translated sentence without them says less.
    assert caught.value.code is None
    assert "199.6" in str(caught.value)
    assert node(kernel).mktabpositions == ""


def test_a_hundred_bridges_of_two_millimetres_never_reaches_the_engine(kernel, drawing):
    """
    Measured on this rectangle: with `"*100"` and 2 mm the engine's geometry comes back
    *empty* — index 0, zero subpaths, zero length — and it says nothing. So we stop it.
    """
    with pytest.raises(DesignError):
        drawing.set_bridges([node(kernel).id], count=100, length_mm=2.0)


def test_more_places_than_a_contour_can_hold_is_a_refusal(kernel, drawing):
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges(
            [node(kernel).id],
            # Percentages, so they all have to be inside [0, 100]: 201 of them at a
            # hundredth of a percent apart.
            positions_percent=[i / 100 for i in range(MAX_COUNT + 1)],
            length_mm=0.1,
        )

    assert str(MAX_COUNT) in str(caught.value)


def test_a_length_on_an_unreadable_position_string_falls_back_to_the_default(kernel, drawing):
    """
    An old project or a hand-edited SVG can carry a string the engine ignores. Then there
    is nothing to keep, and writing it back would leave the shape with no bridges and no
    word said — which is exactly the engine behaviour we are here to replace.
    """
    target = node(kernel)
    target.mktabpositions = "nonsense"
    target.altered()

    result = drawing.set_bridges([target.id], length_mm=2.0)

    assert result["count"] == 4
    assert element(kernel)["bridges"]["count"] == 4


def test_a_place_outside_the_path_is_a_refusal(kernel, drawing):
    with pytest.raises(DesignError):
        drawing.set_bridges([node(kernel).id], positions_percent=[50, 140])


# ------------------------------------------------------------------ a selection


def test_several_shapes_get_them_and_the_answer_counts_both(kernel, drawing):
    kernel.console("circle 100mm 50mm 15mm\n")
    kernel.console("line 10mm 90mm 110mm 90mm\n")
    chosen = ids(kernel)

    result = drawing.set_bridges(chosen, count=4, length_mm=2.0)

    assert result["bridged"] == 2
    assert result["skipped"] == 1
    for index in (0, 1):
        assert element(kernel, index)["bridges"]["count"] == 4


def test_the_shortest_contour_in_the_selection_decides(kernel, drawing):
    """
    Per shape, because the bound is the shape's own contour. A 9 mm bridge is nothing on
    200 mm and everything on a circle of r = 10 mm (perimeter 62.8 mm): four of them take
    36 mm of it. Refusing beats bridging nineteen shapes and skipping the twentieth in
    silence.
    """
    kernel.console("circle 100mm 50mm 10mm\n")
    chosen = ids(kernel)

    with pytest.raises(DesignError) as caught:
        drawing.set_bridges(chosen, count=4, length_mm=9.0)

    assert "62.8" in str(caught.value)
    assert node(kernel, 0).mktabpositions == ""


# ------------------------------------------------------------------ open and closed


def test_an_open_path_gets_bridges_too(kernel):
    """A polyline that does not close: three sides of 40 mm, so 120 mm of path."""
    kernel.console("polyline 10mm,10mm 50mm,10mm 50mm,50mm 10mm,50mm\n")
    drawing = Drawing(kernel)
    drawing.set_bridges([node(kernel).id], count=3, length_mm=2.0)

    bridges = element(kernel)["bridges"]

    assert bridges["path_length_mm"] == pytest.approx(120.0, abs=0.01)
    assert our_length_mm(kernel) == pytest.approx(114.0, abs=0.05)
    # Three gaps in an open line leave four pieces; in a closed one they leave three.
    assert bridges["path"].count("M") == 4


def test_a_closed_path_wraps_its_first_bridge_round_the_seam(kernel, drawing):
    """
    A bridge asked for at 0 % straddles the start of the path. Half of it therefore sits at
    the very end, and the engine does the same — so the picture matches the cut.
    """
    drawing.set_bridges([node(kernel).id], positions_percent=[0.0], length_mm=4.0)

    assert our_length_mm(kernel) == pytest.approx(196.0, abs=0.05)
    assert engine_length_mm(kernel) == pytest.approx(196.0, abs=0.1)


# ------------------------------------------------------------------ clearing


def test_changing_only_the_length_keeps_the_count(kernel, drawing):
    """
    The panel has two fields and they have to be independent. Measured before this: with six
    bridges on the shape, typing a length of 30 mm was refused with "4 bridges of 30 mm" — a
    sentence about a number nobody had asked for.
    """
    element_id = node(kernel).id
    drawing.set_bridges([element_id], count=6, length_mm=2.0)

    result = drawing.set_bridges([element_id], length_mm=3.0)

    assert result["count"] == 6
    assert result["length_mm"] == 3.0
    bridges = element(kernel)["bridges"]
    assert bridges["count"] == 6
    assert bridges["length_mm"] == pytest.approx(3.0, abs=0.001)


def test_changing_only_the_count_keeps_the_length(kernel, drawing):
    element_id = node(kernel).id
    drawing.set_bridges([element_id], count=4, length_mm=5.0)

    drawing.set_bridges([element_id], count=8)

    bridges = element(kernel)["bridges"]
    assert bridges["count"] == 8
    assert bridges["length_mm"] == pytest.approx(5.0, abs=0.001)


def test_two_shapes_with_different_bridges_each_keep_their_own_count(kernel, drawing):
    """A length typed for a whole selection may not level the counts."""
    kernel.console("circle 130mm 50mm 20mm\n")
    rect, circle = ids(kernel)
    drawing.set_bridges([rect], count=6, length_mm=2.0)
    drawing.set_bridges([circle], count=3, length_mm=2.0)

    drawing.set_bridges([rect, circle], length_mm=2.5)

    assert element(kernel, 0)["bridges"]["count"] == 6
    assert element(kernel, 1)["bridges"]["count"] == 3
    for index in (0, 1):
        assert element(kernel, index)["bridges"]["length_mm"] == pytest.approx(2.5, abs=0.001)


def test_a_length_on_a_shape_without_bridges_gives_it_the_default_four(kernel, drawing):
    """Only a length on a bare shape: then there is nothing to keep, so the default lands."""
    result = drawing.set_bridges([node(kernel).id], length_mm=2.0)

    assert result["count"] == 4


def test_clearing_closes_the_cut_again_and_keeps_the_length(kernel, drawing):
    element_id = node(kernel).id
    drawing.set_bridges([element_id], count=4, length_mm=3.0)

    result = drawing.clear_bridges([element_id])

    assert result["cleared"] == 1
    bridges = element(kernel)["bridges"]
    assert bridges["count"] == 0
    assert bridges["path"] == ""
    # The length stays, so switching them back on offers what was there.
    assert bridges["length_mm"] == pytest.approx(3.0, abs=0.001)
    assert engine_length_mm(kernel) == pytest.approx(200.0, abs=0.01)


def test_clearing_a_shape_that_has_none_changes_nothing(kernel, drawing):
    assert drawing.clear_bridges([node(kernel).id])["cleared"] == 0


# ------------------------------------------------------------------ saving


def test_the_svg_parameters_are_registered_so_a_reload_gives_a_number_back(kernel):
    """
    MeerK40t registers these two in `main.py:258` — its own entry point, which our stack
    never runs. Without them `core/svg_io.py:897` hands `mktablength` back as a *string* and
    `final_geometry()` dies on `ufunc 'greater' did not contain a loop with signature
    matching types (Float64DType, StrDType)`.
    """
    registered = list(kernel.lookup_all("registered_mk_svg_parameters"))

    assert "mktablength" in registered
    assert "mktabpositions" in registered


def test_bridges_survive_a_save_and_an_open(kernel, drawing, tmp_path):
    drawing.set_bridges([node(kernel).id], count=4, length_mm=2.0)
    before = engine_length_mm(kernel)

    path = drawing.export_svg("bridges.svg")
    kernel.console("element* delete\n")
    kernel.console(f'load "{path}"\n')

    reopened = node(kernel)
    assert isinstance(reopened.mktablength, float)
    assert reopened.mktabpositions == "*4"
    assert engine_length_mm(kernel) == pytest.approx(before, abs=0.05)


# ------------------------------------------------------------------ over HTTP


def test_the_route_puts_bridges_on_the_selection(client, kernel, drawing):
    element_id = node(kernel).id

    answer = client.post(
        "/api/design/bridges", json={"ids": [element_id], "count": 4, "length_mm": 2.0}
    )

    assert answer.status_code == 200
    assert answer.json() == {
        "ids": [element_id],
        "bridged": 1,
        "skipped": 0,
        "count": 4,
        "length_mm": 2.0,
        "positions_percent": None,
    }
    assert client.get("/api/design").json()["elements"][0]["bridges"]["count"] == 4


def test_the_route_clears_them_again(client, kernel, drawing):
    element_id = node(kernel).id
    client.post("/api/design/bridges", json={"ids": [element_id], "count": 4})

    answer = client.post("/api/design/bridges/clear", json={"ids": [element_id]})

    assert answer.status_code == 200
    assert answer.json()["cleared"] == 1


def test_a_refusal_carries_its_code_in_the_header(client, kernel):
    kernel.console("line 10mm 10mm 110mm 10mm\n")
    element_id = node(kernel).id

    answer = client.post("/api/design/bridges", json={"ids": [element_id], "count": 4})

    assert answer.status_code == 409
    assert answer.headers["X-OpenKerf-Error"] == "bridges.notSupported"


def test_bridged_geometry_hands_back_nothing_when_there_is_nothing_to_cut(kernel, drawing):
    geometry = node(kernel).as_geometry()

    assert bridged_geometry(geometry, [], 5160.0) is None
    assert bridged_geometry(geometry, [50.0], 0.0) is None


def test_too_many_bridges_carries_a_code_and_the_maximum(client, kernel, drawing):
    """
    The refusal a panel hits first, because it fires on any number above the maximum typed
    into the Number field. Measured before this: a fully Dutch panel showed the English
    sentence, because the code was missing and the header was absent.
    """
    element_id = node(kernel).id

    answer = client.post(
        "/api/design/bridges", json={"ids": [element_id], "count": MAX_COUNT + 1}
    )

    assert answer.status_code == 409
    assert answer.headers["X-OpenKerf-Error"] == "bridges.tooMany"
    # The number itself travels beside the code, so the catalogue does not hold a second
    # copy of MAX_COUNT.
    assert answer.headers["X-OpenKerf-Error-Values"] == '{"max": %d}' % MAX_COUNT


def test_a_place_outside_the_path_carries_a_code(client, kernel, drawing):
    answer = client.post(
        "/api/design/bridges", json={"ids": [node(kernel).id], "positions_percent": [150]}
    )

    assert answer.status_code == 409
    assert answer.headers["X-OpenKerf-Error"] == "bridges.percentRange"


def test_the_shape_that_is_too_small_is_named(kernel, drawing):
    """
    The bound is per shape, and the refusal is for the whole call. Then the sentence has to
    say *which* shape: measured before this with three rectangles selected (contours 200,
    200 and 12 mm) it named "a contour that is 12.0 mm long" and nothing more, so on a
    nested sheet the offending part could not be found.
    """
    kernel.console("rect 10mm 60mm 3mm 3mm\n")
    small = node(kernel, 1)

    with pytest.raises(DesignError) as caught:
        drawing.set_bridges(ids(kernel), count=4, length_mm=2.0)

    message = str(caught.value)
    assert small.id in message
    assert "12.0 mm long" in message
    # And how big the problem is: one of the two shapes would have been fine.
    assert "1 of the 2 shapes would have been fine" in message


def test_one_shape_that_is_too_small_says_nothing_about_a_tally(kernel, drawing):
    """A count of one out of one is noise; the sentence stays as short as it can."""
    with pytest.raises(DesignError) as caught:
        drawing.set_bridges([node(kernel).id], count=4, length_mm=49.9)

    assert "would have been fine" not in str(caught.value)
