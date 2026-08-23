"""
A photograph that finds its own board, and one that refuses to be filed wrong.

This is the half of the board code that pays for the other half. Drawing a code on a
plank is arithmetic; the question these tests answer is whether a picture of that plank,
handed to the API the way a phone hands one in, lands on the row it is actually of.

The problem is measured, not hypothetical. Of the thirty-two boards in the author's real
library, **eleven are physically indistinguishable from another one** — same material, same
square size, same sweep, burned minutes apart — and six of them share a single day. Once
the wood is off the machine there is nothing in the burn marks to tell them apart, so the
person uploading has to remember, and a photograph filed under the wrong row becomes
evidence for a burn nobody did.

Every photograph here is fabricated rather than taken: `on_a_board` puts the planned code
in the corner of a grey plank with sixteen darker squares on it, turns it five degrees,
blurs it, adds noise and encodes it as JPEG 85. Not a substitute for wood — nothing here
knows what char does to a module edge, and **no board with a code has been burned yet** —
but it is the difference between "the pattern is right" and "a camera can read it". At the
2400 px used below that photograph decoded 5 of 5 seeds; at 1600 px, 1 of 5. That gap is
why these routes decode the upload and never a stored copy.
"""

from pathlib import Path

import numpy as np
import pytest
import segno
from fastapi.testclient import TestClient

from openkerf_api import boardcode
from openkerf_api.server import ApiServer

from test_boardcode import on_a_board, photograph, render
from test_testgrid import FOUR_BY_FOUR

HAVE_CV2 = boardcode.available()
needs_cv2 = pytest.mark.skipif(
    not HAVE_CV2, reason="OpenCV is an optional extra; reading codes needs it"
)

#: Wide enough that the code is readable, which is the whole premise of the route. An
#: 18 mm code on a 300 mm board at 2400 px across the frame is 4.1 px per module — measured
#: 5 of 5 here, and 20 of 20 over the twenty seeds `boardcode.read`'s table was built from.
FRAME_PX = 2400


@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "photo.db")
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def a_coded_board(client) -> dict:
    """A board drawn on the bed through the API, with its code on the plank."""
    response = client.post(
        "/api/library/testgrids", json={**FOUR_BY_FOUR, "code_enabled": True}
    )
    assert response.status_code == 201, response.text
    board = response.json()
    assert board["code_enabled"] is True and len(board["uid"]) == 8
    return board


def a_photograph_of(uid: str, seed: int = 0, width_px: int = FRAME_PX) -> bytes:
    """The plank as a phone would hand it in: the code in the corner of a board."""
    return on_a_board(boardcode.plan(uid), width_px=width_px, seed=seed)


def upload(client, data: bytes, grid_id: int | None = None):
    """The same call the phone makes, with or without a board id in the path."""
    where = (
        "/api/library/testgrids/photo"
        if grid_id is None
        else f"/api/library/testgrids/{grid_id}/photo"
    )
    return client.post(where, files={"file": ("board.jpg", data, "image/jpeg")})


def code_of(response) -> str | None:
    return response.headers.get("X-OpenKerf-Error")


# ------------------------------------------------- the photograph names its board


@needs_cv2
def test_a_photograph_with_no_id_lands_on_the_board_it_is_of(client):
    """
    The headline: two boards from the same form, one photograph, no id in the path.

    The two boards here are deliberately identical in every burned mark except the code —
    same material, same sweep, same square size, planned from one body — which is the shape
    eleven of the author's thirty-two boards are in. Without the code there is nothing in
    this picture that says which of the two it is; with it, the route answers with the right
    row and the other board still has no photograph at all.

    And the file that lands on disk is byte-identical to the upload: 587 KB in, 587 KB
    stored. That is not tidiness, it is the measurement — the same picture at 1600 px
    decoded 1 of 5 seeds where 2400 px decoded 5 of 5, so anything that shrank the upload
    on the way in would be reading the one size that does not work.
    """
    mine = a_coded_board(client)
    other = a_coded_board(client)
    assert mine["uid"] != other["uid"]
    data = a_photograph_of(mine["uid"])

    response = upload(client, data)

    assert response.status_code == 200, response.text
    landed = response.json()
    assert landed["id"] == mine["id"]
    assert landed["uid"] == mine["uid"]
    assert Path(landed["photo_path"]).read_bytes() == data
    assert client.get(f"/api/library/testgrids/{other['id']}").json()["photo_path"] is None


# No `needs_cv2` on this one, deliberately: the printed line under the code is precisely
# the route for a machine with no OpenCV on it, so a test of it that skips without OpenCV
# would skip in exactly the situation it exists for.
def test_a_typed_code_and_a_read_code_find_the_same_board(client):
    """
    The fallback that needs no camera, at the library layer: `7X4M QB2K` typed off a plank
    finds the board a decoder's `OK1:7X4MQB2K` finds.

    This is what the printed line under the code is for, and it is the only route to a
    board on a phone with no OpenCV behind it — which is every phone, since the reading
    happens on this machine. All three spellings are one name.
    """
    board = a_coded_board(client)
    lib = client.server.library
    uid = board["uid"]
    for spelling in (uid, uid.lower(), f"{uid[:4]} {uid[4:]}", f"OK1:{uid}"):
        assert lib.test_grid_for_uid(spelling)["id"] == board["id"]
    # And a name nothing carries is not a near miss: it is None, not the closest board.
    assert lib.test_grid_for_uid(boardcode.mint_uid()) is None
    assert lib.test_grid_for_uid("not a code at all") is None


# ------------------------------------------------- filed under the wrong board


@needs_cv2
def test_a_photograph_filed_under_another_board_is_refused(client):
    """
    The refusal this whole feature exists for: board A's picture, uploaded against board B.

    Today's route stores whatever it is given without looking at the pixels, so this is the
    case that quietly ruins a library — B's row then offers A's photograph, and every
    preset drawn out of B carries it as evidence. The refusal names both boards in the
    reader's own printed form, so the answer ("file it under that one instead") is in the
    sentence.
    """
    mine = a_coded_board(client)
    other = a_coded_board(client)

    response = upload(client, a_photograph_of(mine["uid"]), grid_id=other["id"])

    assert response.status_code == 409
    assert code_of(response) == "library.photo.codeMismatch"
    assert boardcode.human(mine["uid"]) in response.json()["detail"]
    assert boardcode.human(other["uid"]) in response.json()["detail"]
    # And nothing was written: the wrong row is still empty, the right one untouched.
    assert client.get(f"/api/library/testgrids/{other['id']}").json()["photo_path"] is None
    assert client.get(f"/api/library/testgrids/{mine['id']}").json()["photo_path"] is None


@needs_cv2
def test_a_photograph_of_the_board_you_picked_is_simply_stored(client):
    """
    The other side of the same door. Reading the code must not make the ordinary case
    harder: pick the board, upload its own picture, and it is stored as it always was.
    """
    board = a_coded_board(client)

    response = upload(client, a_photograph_of(board["uid"]), grid_id=board["id"])

    assert response.status_code == 200, response.text
    assert response.json()["photo_path"]


@needs_cv2
def test_a_board_without_a_code_is_still_filed_by_hand(client):
    """
    Most boards in the world have no code on them — the switch is off by default, and the
    thirty-two boards already in the library will never have one. So a picture with nothing
    to read is not an error on the id route: it is the way it has always worked.

    On the id-less route the same picture is a refusal, because there the code is the only
    thing that could have named a board, and the sentence sends the reader to the picker
    rather than blaming the photograph.
    """
    board = client.post("/api/library/testgrids", json=FOUR_BY_FOUR).json()
    plank = photograph(np.full((900, 1400), 232, dtype=np.uint8))
    assert boardcode.read(plank) == []

    stored = upload(client, plank, grid_id=board["id"])
    assert stored.status_code == 200, stored.text
    assert stored.json()["photo_path"]

    refused = upload(client, plank)
    assert refused.status_code == 409
    assert code_of(refused) == "library.photo.noCode"
    assert "Choose the board" in refused.json()["detail"]


@needs_cv2
def test_a_code_this_library_never_burned_names_no_board_here(client):
    """
    A code that reads back perfectly and names nothing here — somebody else's board, or a
    board removed from this library — is its own sentence and not "no code found": the
    reader has to know the picture was read and simply belongs elsewhere.

    On the id route that same picture is *accepted*, and that is deliberate rather than
    lax. `boardcode.parse` takes eight characters of Crockford base32, and plenty of
    ordinary words survive the folding — `notacode` reads back as `N0TAC0DE` — so a QR on
    the bench, a parcel label or a colleague's sticker in the corner of the frame would
    otherwise block a photograph that is perfectly right. Only a code naming a board this
    library actually holds refuses, because only that is the mix-up worth a refusal.
    """
    board = a_coded_board(client)
    stranger = boardcode.mint_uid()
    while stranger == board["uid"]:  # pragma: no cover - 1 in a trillion
        stranger = boardcode.mint_uid()
    data = a_photograph_of(stranger)

    nameless = upload(client, data)
    assert nameless.status_code == 409
    assert code_of(nameless) == "library.photo.unknownBoard"
    assert boardcode.human(stranger) in nameless.json()["detail"]

    filed = upload(client, data, grid_id=board["id"])
    assert filed.status_code == 200, filed.text


@needs_cv2
def test_a_word_that_folds_into_a_code_does_not_block_an_honest_photograph(client):
    """
    The measurement behind the rule above, made explicit: `notacode` in an ordinary QR
    reads back as the board name `N0TAC0DE`, because Crockford folding turns O into 0.

    So "the picture holds something that parses" cannot be the test for "this picture is of
    another board". Here the sticker is in shot beside the board the user picked, and the
    upload goes through.
    """
    assert boardcode.parse("notacode") == "N0TAC0DE"
    board = a_coded_board(client)
    sticker = segno.make_qr("notacode", error="m")
    matrix = [[1 if cell else 0 for cell in row] for row in sticker.matrix]
    quiet, px = 4, 8
    side = (len(matrix) + 2 * quiet) * px
    canvas = np.full((side, side), 255, dtype=np.uint8)
    for row, cells in enumerate(matrix):
        for column, dark in enumerate(cells):
            if dark:
                canvas[(row + quiet) * px : (row + quiet + 1) * px,
                       (column + quiet) * px : (column + quiet + 1) * px] = 0
    assert boardcode.read(canvas) == ["N0TAC0DE"]

    response = upload(client, photograph(canvas, angle=0.0), grid_id=board["id"])

    assert response.status_code == 200, response.text


@needs_cv2
def test_two_boards_in_one_frame_are_not_filed_under_the_nearer_one(client):
    """
    Two tiles photographed together — the thing that happens when a plank holds four of
    them — cannot be filed by picking one. Whichever detector happened to answer first
    would decide which board the evidence belongs to, and that is a coin toss dressed as
    an answer, so the route asks for one board at a time.
    """
    first = a_coded_board(client)
    second = a_coded_board(client)
    px = 12 / boardcode.plan(first["uid"])["module_mm"]
    left = render(boardcode.plan(first["uid"]), px_per_mm=px)
    right = render(boardcode.plan(second["uid"]), px_per_mm=px)
    pair = np.full((left.shape[0], left.shape[1] * 2 + 40), 255, dtype=np.uint8)
    pair[:, : left.shape[1]] = left
    pair[:, left.shape[1] + 40 :] = right
    data = photograph(pair, angle=0.0)
    assert sorted(boardcode.read(data)) == sorted([first["uid"], second["uid"]])

    response = upload(client, data)

    assert response.status_code == 409
    assert code_of(response) == "library.photo.manyBoards"
    for board in (first, second):
        assert (
            client.get(f"/api/library/testgrids/{board['id']}").json()["photo_path"]
            is None
        )


@needs_cv2
def test_a_frame_holding_both_boards_is_filed_under_the_one_you_picked(client):
    """
    The other side of the two-in-one-frame refusal: on the id route, a picture that holds
    the picked board's code *and* another board's is stored without a word.

    That is not laxness, it is the plank. Four tiles cut from one board are photographed
    together as often as they are apart, and the user has told this route which of them
    the picture is filed under — the code they named is in the frame, so nothing is being
    guessed. The refusal is for the id-*less* route, where nobody said which one it was.
    """
    mine = a_coded_board(client)
    other = a_coded_board(client)
    px = 12 / boardcode.plan(mine["uid"])["module_mm"]
    left = render(boardcode.plan(mine["uid"]), px_per_mm=px)
    right = render(boardcode.plan(other["uid"]), px_per_mm=px)
    pair = np.full((left.shape[0], left.shape[1] * 2 + 40), 255, dtype=np.uint8)
    pair[:, : left.shape[1]] = left
    pair[:, left.shape[1] + 40 :] = right
    data = photograph(pair, angle=0.0)
    assert sorted(boardcode.read(data)) == sorted([mine["uid"], other["uid"]])

    response = upload(client, data, grid_id=mine["id"])

    assert response.status_code == 200, response.text
    assert response.json()["photo_path"]


# ------------------------------------------------- without a decoder at all


def test_without_opencv_the_id_route_behaves_exactly_as_it_did(client, monkeypatch):
    """
    OpenCV is an optional extra of ours and must not become a requirement of uploading a
    photograph. Without it the board still burns its code, the printed line under it still
    identifies the board by hand, and the id route stores whatever it is given — which is
    what it did before any of this existed.

    The id-less route is the one that cannot work, and it says so with the install line
    rather than with "no code found": a reader who is told there is no code in their
    photograph will take another photograph, and it will fail in the same way.
    """
    monkeypatch.setattr(boardcode, "_opencv", lambda: None)
    board = client.post(
        "/api/library/testgrids", json={**FOUR_BY_FOUR, "code_enabled": True}
    ).json()

    stored = upload(client, b"pretend this is a photograph", grid_id=board["id"])
    assert stored.status_code == 200, stored.text
    assert stored.json()["photo_path"]

    refused = upload(client, b"pretend this is a photograph")
    assert refused.status_code == 409
    assert code_of(refused) == "library.photo.noDecoder"
    assert "opencv-python-headless" in refused.json()["detail"]
    assert "Choose the board yourself" in refused.json()["detail"]


def test_an_empty_upload_is_not_a_refusal_about_codes(client):
    """
    A phone that hands in nothing is a broken upload, not a board that cannot be named. It
    answers 422 on both routes, so the interface does not tell somebody to photograph the
    code more squarely when there is no photograph at all.
    """
    board = client.post("/api/library/testgrids", json=FOUR_BY_FOUR).json()

    assert upload(client, b"", grid_id=board["id"]).status_code == 422
    assert upload(client, b"").status_code == 422
