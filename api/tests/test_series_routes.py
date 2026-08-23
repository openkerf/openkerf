"""
A series over HTTP: uploading a list, attaching it, and running the burns.

`api/tests/test_series.py` owns the arithmetic — reading a file, finding placeholders,
how rows fall into burns. This file owns the contract a client sees: which route
changes something and which one does not, that a refusal of ours arrives as 409 with
its code in `X-OpenKerf-Error`, and that the run verbs count plates the way an operator
does. Everything here goes through `TestClient`, so it is the same path the browser
takes, headers and all.

No job ever reaches a real machine here: the kernel fixture activates the dummy device,
which spools and does nothing. That is also why the burn tests are safe to run with a
laser on the bench — `test_write_actions.py` has spooled through this same fixture since
phase 2.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.series import ranges_of, rows_in
from openkerf_api.server import ApiServer

FIVE = ("Anna", "Bram", "Cees", "Daan", "Eva")


@pytest.fixture
def server(kernel, tmp_path):
    # A library of its own, so the series file lands beside it in tmp_path and not in
    # the developer's real settings directory next to the list their app has attached.
    return ApiServer(kernel, library_path=tmp_path / "series.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def a_csv(names=FIVE, column="name") -> bytes:
    return (column + "\n" + "\n".join(names) + "\n").encode("utf-8")


def upload(client, data: bytes, name: str = "names.csv"):
    return client.post(
        "/api/series/upload", files={"file": (name, data, "text/csv")}
    )


def attach(client, data: bytes = None, **body):
    """Upload and attach in one go, the way the window's own button does."""
    if data is not None:
        uploaded = upload(client, data)
        assert uploaded.status_code == 200, uploaded.text
        body = {"file": uploaded.json()["file"], **body}
    return client.post("/api/series/attach", json=body)


def a_text(client, template: str, x: float = 20.0, y: float = 20.0):
    """One vector text on the bed carrying a template. Returns its element id."""
    response = client.post(
        "/api/design/elements",
        json={
            "type": "text",
            "x_mm": x,
            "y_mm": y,
            "text": template,
            "font_size_mm": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def engine_row(kernel, column: str = "name"):
    """
    Where the engine's own pointer stands, counted the way we count rows.

    `IDX_POSITION` is index 1 of an entry and the values start at index 2
    (`core/wordlist.py:42-44`). Read here and only here, because the drift the tests
    below are about is not visible anywhere else.
    """
    entry = kernel.elements.mywordlist.content.get(column)
    return None if entry is None else entry[1] - 2


def burned_text(kernel, element_id: str) -> str:
    """What the engine has actually rendered into this node — not what we asked for."""
    for node in kernel.elements.elems():
        if getattr(node, "id", None) == element_id:
            return getattr(node, "_translated_text", None)
    raise AssertionError(f"There is no element {element_id} on the bed.")


# --------------------------------------------------------------- reading a list


def test_uploading_a_list_changes_nothing(client):
    """
    The upload is a look, not a decision.

    Two steps and not one, like the library bundle and the machine profile: somebody
    has to be able to see that their semicolons were read as semicolons and that the
    first row was taken as column names before fifty plates depend on it. Fails on the
    plausible shortcut — upload and attach in one route — because then the answer below
    would already say `attached`.
    """
    response = upload(client, a_csv())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["columns"] == ["name"]
    assert body["row_count"] == 5
    assert [row["name"] for row in body["rows"]] == list(FIVE)
    assert body["header_guess"] is True
    assert body["has_header"] is True
    assert body["delimiter"] == ","
    assert client.get("/api/series").json()["attached"] is False


def test_the_header_question_can_be_answered_again_without_uploading_again(client):
    """
    Our guess about the first row is a guess, and it has to be overrulable.

    The engine's own answer here is `csv.Sniffer().has_header()`, which said False for
    `name,city` over two names and True for `code,size` over two codes — measured. So
    the file stays under its own name in the upload directory and the preview can be
    asked again with the other answer. Fails on an implementation that parses in the
    browser or throws the upload away, because then this route has nothing to re-read.
    """
    name = upload(client, a_csv()).json()["file"]

    again = client.post(
        "/api/series/preview", json={"file": name, "has_header": False}
    )

    assert again.status_code == 200, again.text
    body = again.json()
    # The heading became a row, and the column has no name of its own any more.
    assert body["columns"] == ["column_1"]
    assert body["row_count"] == 6
    assert body["rows"][0]["column_1"] == "name"
    # And what we would have said is still in there, so the control can stay pre-filled.
    assert body["header_guess"] is True
    assert body["has_header"] is False


def test_a_list_the_engine_would_have_thrown_away_is_read(client):
    """
    The reason the reading is ours at all, proved through the route.

    A Dutch Excel export: cp1252 bytes, semicolons, an accent. Measured against
    `core/wordlist.py:809`, the engine's loader returns `(0, 0, [])` and one warning
    nobody sees, because `EncodingDetectFile` declares `ENCODING_CP1252` at
    `extra/encode_detect.py:17` and never returns it from any branch.
    """
    data = "naam;plaats\nRené;Zwolle\nSofie;Gouda\n".encode("cp1252")

    body = upload(client, data, "namen.csv").json()

    assert body["columns"] == ["naam", "plaats"]
    assert body["delimiter"] == ";"
    assert body["encoding"] == "cp1252"
    assert body["rows"][0]["naam"] == "René"


def test_a_reserved_column_is_refused_with_its_code_in_the_header(client):
    """
    A refusal of ours has to arrive as something the interface can translate.

    409, the sentence in `detail`, the code in `X-OpenKerf-Error`. A column called
    `date` matters because the engine answers that name itself: measured,
    `set_value("date", …)` appends to the built-in and `{date}` still resolves to the
    clock, so the column would silently do nothing at all. Fails on a 500, and on a
    refusal that arrives without its code — the window would then have nothing but an
    English sentence to show a Dutch reader.
    """
    response = upload(client, b"date;qty\n2026-08-22;3\n", "orders.csv")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.reservedColumn"
    assert "date" in response.json()["detail"]


def test_a_file_too_big_to_be_a_list_is_refused_before_it_is_parsed(client):
    """
    Five megabytes of anything is not a list of names.

    The count runs while the body is being read, so the refusal comes before the whole
    file is on disk and before a parser walks it. Fails on a check placed after the
    write, which would put whatever somebody sent in the temp directory first.
    """
    response = upload(client, b"n\n" * 2_700_000, "huge.csv")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.fileTooBig"
    assert "5 MB" in response.json()["detail"]


def test_a_list_the_server_no_longer_has_says_so(client):
    """
    Uploads live in a temp directory that is wiped when the server stops.

    So a page left open across a restart holds a file name that means nothing. Without
    this the preview would read no bytes and show an empty list, which reads as "my
    file was empty" rather than "this server has never seen it".
    """
    response = client.post("/api/series/preview", json={"file": "vanished.csv"})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.uploadGone"


# ------------------------------------------------------------------- attaching


def test_attaching_a_list_makes_the_bed_show_the_first_row(client, kernel):
    """
    The promise the whole feature stands on, over HTTP: the bed shows what burns next.

    Fails on the plausible implementation that stores the rows and stops there — the
    node then still carries its own template and renders as nothing, `bounds` comes
    back `(nan, nan, nan, nan)` and it drops out of the snapshot while still counting
    as burnable. That is a plate with a frame and no name.
    """
    a_text(client, "{name}")

    response = attach(client, a_csv())

    assert response.status_code == 200, response.text
    state = response.json()
    assert state["attached"] is True
    assert state["row_count"] == 5
    assert state["current_row"] == 0
    assert state["burns"] == 5
    assert state["step"] == 1
    assert state["used_columns"] == ["name"]
    assert burned_text(kernel, a_text(client, "{name}", y=40.0)) == "Anna"


def test_numbers_fill_the_rows_in_through_the_same_door(client, kernel):
    """
    "Numbered parts 001 to 250" is a real job and must not need a spreadsheet first.

    Numbers are not a second kind of series: the same attach, the same list, the same
    burns afterwards, and `source.kind` is the only thing that remembers where the rows
    came from. Fails on a second route family or a counter in the engine — the engine's
    own `TYPE_COUNTER` increments on every read, so re-rendering the bed to show what
    is next would itself move it on.
    """
    a_text(client, "{part}")

    response = attach(
        client, kind="numbers", first=1, last=3, padding=3, column="part"
    )

    assert response.status_code == 200, response.text
    state = response.json()
    assert state["source"]["kind"] == "numbers"
    assert state["row_count"] == 3
    assert state["burns"] == 3
    assert client.get("/api/series").json()["rows"] == [
        {"part": "001"},
        {"part": "002"},
        {"part": "003"},
    ]
    assert burned_text(kernel, a_text(client, "{part}", y=40.0)) == "001"


def test_the_rows_ride_only_on_the_windows_own_route(client):
    """
    A thousand rows may not go down every heartbeat.

    `GET /api/series` is the window's route and carries the rows; the status payload
    carries the sum. Fails on the tempting shortcut of one shape everywhere, which puts
    a thousand names on the socket every two seconds for a number that fits in a word.
    """
    a_text(client, "{name}")
    attach(client, a_csv())

    assert "rows" in client.get("/api/series").json()
    assert "rows" not in client.get("/api/status").json()["series"]


def test_a_series_appears_in_the_status_payload(client):
    """
    One snapshot, the same everywhere.

    Top bar, canvas, context panel and phone view all read the live socket. Fails on a
    series that is only readable from its own route, which is precisely how the tile
    run once went missing on the WebSocket while `/api/status` already had it.
    """
    assert client.get("/api/status").json()["series"] is None

    a_text(client, "{name}")
    attach(client, a_csv())

    series = client.get("/api/status").json()["series"]
    assert series["attached"] is True
    assert series["current_row"] == 0
    assert series["burns"] == 5


def test_the_series_sum_rides_with_the_pre_flight(client):
    """
    The pre-flight has to be able to multiply one burn by the burns still to go.

    On `/api/job/layers` and not behind `/api/job/estimate`, for the reason that
    route's own docstring gives: a blockage must not have to queue behind the clock. A
    job of fifty burns showing the time of one is a wrong answer that looks right.
    """
    a_text(client, "{name}")
    attach(client, a_csv())

    layers = client.get("/api/job/layers").json()

    assert layers["series"]["burns"] == 5
    assert layers["series"]["uses"][0]["placeholder"] == "{name}"
    assert layers["series"]["uses"][0]["renders"] == "Anna"


def test_detaching_leaves_no_name_behind_on_the_bed(client, kernel):
    """
    A text that reads from a list has nothing to say once the list is gone.

    Leaving `Anna` on the bed after the list is detached would be a lie the next burn
    tells. Fails on a detach that only deletes the file: the engine's register would
    still answer `{name}` and the canvas would keep the name of a list nobody has.
    """
    element = a_text(client, "{name}")
    attach(client, a_csv())
    assert burned_text(kernel, element) == "Anna"

    response = client.delete("/api/series")

    assert response.status_code == 200, response.text
    assert response.json()["attached"] is False
    assert burned_text(kernel, element) == ""


# ------------------------------------------------------------------- the run


def a_list_and_a_text(client, names=FIVE, template="{name}") -> str:
    """
    A list attached, and then a text that reads from it — in that order, deliberately.

    A text placed while nothing is attached renders as the empty string, so its bounds
    come back `(nan, nan, nan, nan)` and the engine classifies it into no layer at all:
    measured through these routes, zero operations and "There is nothing ready to burn"
    from the spooler. That is the ghost the plan describes and it is not this file's
    subject — a burn test has to begin from a design that can actually burn.
    """
    assert attach(client, a_csv(names)).status_code == 200
    element = a_text(client, template)
    # The engrave layer a text lands in arrives with 'burn along' off in this kernel, so
    # a job over it is empty and the spooler answers "there is nothing ready to burn".
    # Switching it on is what the operator does in the Layers panel and is not what
    # these tests are about.
    for operation in client.get("/api/design").json()["operations"]:
        if element in operation["element_ids"]:
            switched = client.patch(
                f"/api/design/operations/{operation['id']}", json={"output": True}
            )
            assert switched.status_code == 200, switched.text
    return element


def a_running_series(client, names=FIVE, template="{name}"):
    """A list, a text that reads from it, and a run going. Returns the state."""
    a_list_and_a_text(client, names, template)
    started = client.post("/api/series/start", json={})
    assert started.status_code == 200, started.text
    return started.json()


def test_starting_needs_a_text_that_reads_from_the_list(client):
    """
    A series over a design that reads nothing is fifty identical plates.

    Measured today with no guard at all: the run starts, every burn is the same, and
    the operator finds out at the end of the list. Fails on a start that only checks
    that a list is attached.
    """
    a_text(client, "Fixed sign")
    attach(client, a_csv())

    response = client.post("/api/series/start", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.nothingVariable"


def test_starting_names_the_column_the_list_has_not_got(client):
    """
    Two refusals compete here and the informative one has to win.

    A text reading `{nope}` makes `used_columns` empty as well, so the check on "does
    anything read the list" would fire first and say "none of the text comes from the
    list" about a text that plainly does. The reader can act on the name of the missing
    column; they cannot act on the other sentence.
    """
    a_text(client, "{nope}")
    attach(client, a_csv())

    response = client.post("/api/series/start", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.unknownColumn"
    assert "nope" in response.json()["detail"]


def test_starting_twice_refuses_rather_than_losing_the_count(client):
    """
    Starting over would throw away which plates are burned.

    That is an afternoon of counting the operator cannot get back by looking at the
    bed, so it is a refusal and not a restart. Fails on a `start` that simply writes a
    fresh run block over the old one.
    """
    a_running_series(client)

    response = client.post("/api/series/start", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.alreadyStarted"


def test_a_plain_job_is_refused_while_a_series_is_going(client, kernel):
    """
    The ordinary Burn button burns one plate and counts nothing.

    The operator would find out by counting plates against the burn list, which is the
    one thing this feature exists to make unnecessary. 409 through the `refuse()`
    helper, so the code arrives in the header; and 200 again the moment the run is
    stopped, because the guard must not outlive the run.
    """
    a_running_series(client)

    refused = client.post("/api/job/start")

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "series.runGoing"
    assert client.post("/api/series/stop").status_code == 200
    assert client.post("/api/job/start").status_code == 200


def test_a_series_will_not_start_while_a_tile_run_is_going(client):
    """
    Two things that both decide what the next burn is may not both be going.

    A tile run clips the design to a piece of a board; a series changes what a text
    says. Both at once is two sets of bookkeeping over one plate. The neighbour is
    faked here rather than a real tile run set up, because the seam under test is
    exactly "the series asks the tile run whether it is going" — a real one would need
    a board bigger than the bed and two tapped marks, and would test tiling.

    Checked on every burn and not only on start: a tile run can be begun from its own
    panel after a series has started, and it is the burn that costs material.
    """
    a_text(client, "{name}")
    attach(client, a_csv())

    class ATileRunIsGoing:
        @staticmethod
        def state():
            return {"tiles": 4, "current": 0}

    client.server.series.tiles = ATileRunIsGoing()
    response = client.post("/api/series/start", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.otherRunGoing"


def test_a_tile_run_will_not_start_while_a_series_is_going(client):
    """
    The other half of that promise, which was missing.

    The refusal above is made by the series when it is asked to start. A tile run is
    begun from its own panel and knew nothing about a series, so the two could be
    started in either order and only one order was refused — and the operator finds out
    by counting plates. This is the mirror: its own code, because its sentence says stop
    the series while the other says stop the tile run, and one code carries one
    translated sentence.
    """
    a_running_series(client)

    response = client.post("/api/tiling/start")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.runGoingTiles"


def test_a_tile_burn_passes_the_same_gate_as_every_other_burn(client):
    """
    A tile burn was the one way into the spooler that vetted nothing at all.

    `TileRun.burn` is the third caller of `CommandRunner.start_job` beside the ordinary
    Burn button and a series burn, and it asked the series nothing. So a board carrying a
    text that reads a column the list has not got came off the machine with the frame
    burned and the name missing, without a word — the very failure `Series.vet()` exists
    to stop, reached by the only route that did not call it.

    The proof is in *which* refusal comes back. There is no tile run going here, so a
    route that vets nothing answers the tile run's own "there is no tile run going",
    which carries no code at all. Getting `series.unknownColumn` instead is what says the
    gate is in front of the burn and not behind it.

    The text is placed before the list is attached, which is the only order left: typing
    `{nope}` while a list is attached is now refused at the text field itself
    (`series.require_known_columns`). A ghost still arrives by this door, and by an
    imported SVG, and by swapping the list — which is why the gate at the burn stays.
    """
    a_text(client, "{nope}")
    attach(client, a_csv())

    response = client.post("/api/tiling/burn", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.unknownColumn"


def test_asking_to_read_a_file_without_naming_one_is_a_refusal_like_the_others(client):
    """
    Every no in this API is a 409 with its code in the header, this one included.

    It used to be a bare 422 with an English sentence and no code, which is the one
    refusal in the family the window could not have said in Dutch. Nothing about the
    answer being unreachable in the app excuses it: curl and a script reach it, and a
    client that special-cases one status for one route is a client that will get it
    wrong.
    """
    response = client.post("/api/series/preview", json={"kind": "file"})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.noFileChosen"


def test_the_list_cannot_be_swapped_under_a_run(client):
    """
    What is burned has to keep matching what is left.

    Its own code beside `series.runGoing`, because the two refusals ask for different
    things — one says press the other button, this one says stop the run — and one code
    can carry only one translated sentence.
    """
    a_running_series(client)

    response = client.delete("/api/series")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.listLocked"


def test_burning_spools_one_job_and_marks_those_rows_done(client, kernel):
    """
    A burn is one plate: one job in the queue, one row marked.

    Marked here and not in `advance`, because the plate exists as soon as the plan
    reaches the spooler — marking on the way past would count a plate nobody made
    every time somebody stepped over a burn. Fails on an implementation that expands
    the whole list into one job, which is also how you get fifty layers into a
    controller that answered "file invalid" at thirty-three.
    """
    a_running_series(client)
    before = len(kernel.device.spooler.queue)

    response = client.post("/api/series/burn", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(kernel.device.spooler.queue) == before + 1
    assert body["burned"] == 1
    assert body["burned_rows"] == [0]
    assert body["run"]["done"] == [[0, 0]]
    # And the pointer has not moved: the bed still shows the plate just made until
    # somebody says they are done with it.
    assert body["current_row"] == 0


def test_the_engine_pointer_is_put_back_after_the_spooler_moves_it(client, kernel):
    """
    `spool` runs a `wordlist advance` inside itself (`core/spoolers.py:57`).

    So the engine's row moves on the moment a job is handed over, without anybody
    asking, and the burn after it would take the row after the one we mean. Measured
    through the runner alone, with no series involved: the pointer went from 0 to 1 on
    one `start_job`. On a twelve-up sheet that is a whole sheetful slid by one row per
    job start.

    This reads the engine's register directly because that is the only place the drift
    shows: the node on the bed is not re-rendered by the advance, so it says `Anna`
    either way. And the second half is the same invariant from the other side — a
    pointer moved by hand is put back by *looking* at the series, not by pressing
    anything, which is what makes the register write-only from our side.
    """
    a_list_and_a_text(client)
    assert client.post("/api/series/start", json={}).status_code == 200

    assert client.post("/api/series/burn", json={}).status_code == 200

    assert engine_row(kernel) == 0
    assert client.get("/api/series").json()["current_row"] == 0

    kernel.elements.mywordlist.set_index("name", 2)
    assert client.get("/api/series").json()["current_row"] == 0
    assert engine_row(kernel) == 0


def test_burning_the_same_one_twice_asks_first(client):
    """
    Going over work that is already there spoils it, so it takes a confirmation.

    Cleared by `{"confirm": true}` and by nothing else — the same shape a tile reburn
    uses. Fails on a burn that silently repeats, which is what a double tap on a
    touchscreen produces.
    """
    a_running_series(client)
    client.post("/api/series/burn", json={})

    again = client.post("/api/series/burn", json={})

    assert again.status_code == 409
    assert again.headers["X-OpenKerf-Error"] == "series.alreadyBurned"
    assert client.post("/api/series/burn", json={"confirm": True}).status_code == 200


def test_a_changed_design_refuses_the_burn_and_says_which_way_it_changed(client):
    """
    Half old and half new is the one outcome nobody can use.

    Two reasons and therefore two codes: the geometry moved, or the number of places on
    a sheet changed and the rows now fall into different burns. The punishment differs,
    so the sentence has to differ. Fails on one code for both, and on a fingerprint
    taken over the bounds of every element — a text's bounds change with the row by
    design, so that would call a series stale one burn after it began.
    """
    element = a_list_and_a_text(client)
    assert client.post("/api/series/start", json={}).status_code == 200

    moved = client.post(
        "/api/design/move", json={"ids": [element], "dx_mm": 10, "dy_mm": 0}
    )
    assert moved.status_code == 200, moved.text

    response = client.post("/api/series/burn", json={})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.staleGeometry"
    assert "half old and half new" in response.json()["detail"]


def test_advancing_moves_the_bed_to_the_next_name(client, kernel):
    """
    Advance is the moment the operator swaps the workpiece, so the bed has to follow.

    Fails on the plausible implementation that only writes the new row number: the
    engine's index moves and the node keeps its old geometry, so the screen says Anna
    while the machine would burn Bram.
    """
    element = a_list_and_a_text(client)
    client.post("/api/series/start", json={})
    client.post("/api/series/burn", json={})

    response = client.post("/api/series/advance")

    assert response.status_code == 200, response.text
    assert response.json()["current_row"] == 1
    assert response.json()["finished"] is False
    assert burned_text(kernel, element) == "Bram"


def test_the_last_advance_finishes_the_run_and_keeps_the_list(client):
    """
    A finished series is not a lost list.

    The rows stay attached — the next batch of the same job is the same list — and only
    this run's bookkeeping goes. Fails on the tile run's own shape, which writes the
    whole state file away when the last tile is done.
    """
    a_running_series(client, names=("Anna", "Bram"))
    for _ in range(2):
        assert client.post("/api/series/burn", json={}).status_code == 200
        response = client.post("/api/series/advance")
        assert response.status_code == 200, response.text

    assert response.json()["finished"] is True
    assert response.json()["run"] is None
    assert response.json()["attached"] is True
    assert response.json()["row_count"] == 2


def test_redo_leaves_the_pointer_where_the_work_is_and_sweeps_up_the_rest(client):
    """
    The repair story: three plates spoiled out of nineteen, and no plate burned twice.

    Nineteen rows are burned and the operator marks 12, 13 and 14 to be done again — in
    that order, so the pointer ends on 14, the last row they tapped. Burning 14 and
    pressing on has to arrive at 19, the plate that was never made. Two wrong rules die
    here, and both of them cost material:

    - "the current row plus one" lands on 15, which is already burned, and would then
      re-burn 15 to 18 — four plates twice;
    - "the earliest row that is not done" lands back on 12 before 19 has ever been
      burned, which is not wrong so much as a hole left at the end of the run.

    The rule that survives is: the first burn *after* this one that is not done, and
    only when there is none, the first anywhere. That second half is what sweeps 12 and
    13 up at the end instead of calling the series finished with two rows missing.
    """
    names = tuple(f"N{i:02d}" for i in range(20))
    a_running_series(client, names=names)
    # Nineteen plates already made, written the way `burn` writes them: inclusive row
    # ranges, coalesced.
    data = client.server.series._read()
    data["run"]["done"] = ranges_of(range(19))
    data["current_row"] = 19
    client.server.series._write(data)

    for row in (12, 13, 14):
        redo = client.post("/api/series/redo", json={"row": row})
        assert redo.status_code == 200, redo.text
        assert redo.json()["current_row"] == row
    assert rows_in(client.get("/api/series").json()["run"]["done"]) == set(
        range(12)
    ) | set(range(15, 19))

    # Row 14, then on to the one that was never burned at all.
    assert client.post("/api/series/burn", json={}).status_code == 200
    assert client.post("/api/series/advance").json()["current_row"] == 19
    # And now the two holes, oldest first, and then the run is over.
    assert client.post("/api/series/burn", json={}).status_code == 200
    assert client.post("/api/series/advance").json()["current_row"] == 12
    assert client.post("/api/series/burn", json={}).status_code == 200
    assert client.post("/api/series/advance").json()["current_row"] == 13
    assert client.post("/api/series/burn", json={}).status_code == 200

    finished = client.post("/api/series/advance")
    assert finished.json()["finished"] is True
    # The run's bookkeeping goes with the run; the list stays for the next batch.
    assert finished.json()["run"] is None
    assert finished.json()["row_count"] == 20


def test_redoing_a_row_the_series_has_not_got_says_so(client):
    """
    A row number typed or tapped in has to be answerable, not an index error.

    Fails on `burns[row]`-style arithmetic, which for row 40 of a five-row list either
    raises or — worse — reaches round the end of the list and points somewhere real.
    """
    a_running_series(client)

    response = client.post("/api/series/redo", json={"row": 40})

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.noSuchBurn"


def test_the_run_verbs_refuse_when_no_series_is_going(client):
    """
    Burn, advance and redo are about a run, and there has to be one.

    Stop is deliberately not in this list: a Stop button that answers "there is no
    series going" is a dead end for somebody who pressed it twice, or who pressed it
    after the last burn had already finished the run.
    """
    a_text(client, "{name}")
    attach(client, a_csv())

    for path, body in (
        ("/api/series/burn", {}),
        ("/api/series/advance", None),
        ("/api/series/redo", {"row": 0}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409, path
        assert response.headers["X-OpenKerf-Error"] == "series.noRun", path

    assert client.post("/api/series/stop").status_code == 200


def test_a_sheetful_eats_its_rows_in_one_burn(client):
    """
    Three tags on one sheet is three rows per burn, and the offsets say so.

    `step` comes from the design — one more than the largest step forward — and it is
    re-derived on every read, never frozen when a run starts. Seven names over a
    three-up sheet is three burns, the last one short: that short burn is what the
    overrun mutator exists for, because the places it has no rows for would otherwise
    engrave `{name#+2}` as nine characters of real geometry.
    """
    a_text(client, "{name}", y=20.0)
    a_text(client, "{name#+1}", y=40.0)
    a_text(client, "{name#+2}", y=60.0)

    state = attach(client, a_csv(tuple(f"N{i}" for i in range(7)))).json()

    assert state["step"] == 3
    assert state["burns"] == 3
    assert state["current_burn"] == 1
    assert sorted(state["used_columns"]) == ["name"]


def test_starting_over_is_refused_while_a_series_is_going(client):
    """
    Three doors replace the drawing, and all three have to be shut.

    Opening a project was guarded; `POST /api/project/new` and `POST /api/design/clear`
    were not. Measured before this test: with a run going, starting over answered 200
    and left the series attached with a run over an empty bed — a count of plates made
    from a drawing that no longer existed, and `start` writes an empty `done`, so the
    number in the operator's head was the only copy left.
    """
    a_running_series(client)

    for door in ("/api/project/new", "/api/design/clear"):
        refused = client.post(door)
        assert refused.status_code == 409, f"{door} answered {refused.status_code}"
        assert refused.headers.get("X-OpenKerf-Error") == "series.runGoingProject"

    assert client.post("/api/series/stop").status_code == 200
    assert client.post("/api/project/new").status_code == 200
