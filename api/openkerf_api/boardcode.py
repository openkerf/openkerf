"""
The code a test board carries, so a photograph finds its own board.

Eleven of the author's thirty-two boards are physically indistinguishable from another
one — same material, same square size, same sweep, burned minutes apart — so filing a
photograph is guesswork by the time the wood is off the machine. A board that says who it
is takes the guess out: the code goes on the plank, the phone reads it back, and the
photograph lands on the board it is actually of.

**What is in the code.** `OK1:` and eight characters from Crockford's base32 — the
alphabet without I, L, O and U, because those are exactly the characters somebody
mistypes off a photograph, and the printed line under the code is meant to be typed. Eight
characters is 40 bits from `secrets`, not a timestamp and not the row id: boards 28 and 29
in the live library were created 21 seconds apart, and a board's row id is whatever
SQLite hands out (`add_test_grid`, `library.py:1637`, and `_insert_grid` on the import
route, `:2142`), so a restore renumbers every board it touches.

**What was measured, and what was not.** The pixels below are measured, on this laptop,
with OpenCV 5.0.0 and segno 1.6.6. The millimetres are arithmetic on top of them. **No
board with a code has been burned yet** — not one, on any material — so the 18 mm default
is a size that reads on a screen, not a size that read off wood. Char bleeding into the
quiet zone, a module that closes up on birch, the difference between 3 mm ply and cast
acrylic: none of that is in these numbers. Whoever writes the handbook page has to say so
there as well, and the size stays settable for the same reason: when the wood disagrees,
the default moves.

Three measurements decided the code that is here:

1. **`segno.make` was unreadable and `segno.make_qr` is not.** `make` returns a *Micro* QR
   for a payload this short — `OK1:7X4MQB2K` gives M4-Q — and OpenCV decodes a micro code
   as the empty string even from a noise-free render at 12 px per module. See
   `generators.qr_squares`, which is where that fix lives and which this module borrows.
   With `make_qr` the same payload is 1-Q: 21 modules, **29 with the 4-module quiet zone**,
   and 300 of 300 randomly minted uids gave exactly that, so the footprint of a board code
   never changes.
2. **Which OpenCV detector, and what actually goes wrong.** One harness, named so it can
   be repeated: `test_boardcode.on_a_board()` — this module's own millimetres rendered
   nearest-neighbour, stamped on a grey plank beside sixteen grey squares — put through
   `test_boardcode.photograph()`, which turns it 5 degrees, blurs it (Gaussian, sigma 1.1),
   speckles it (sigma 5) and saves it as JPEG 85. Twenty freshly minted uids per rung, an
   18 mm code on a 300 mm board:

   | frame width | px per module | plain, one shot | plain, multi | Aruco | `read` |
   |-------------|---------------|-----------------|--------------|-------|--------|
   | 1600 px     | 3.3           | 0/20            | 0/20         | 0/20  | 6/20   |
   | 2000 px     | 4.1           | 0/20            | 0/20         | 7/20  | 20/20  |
   | 2400 px     | 5.0           | 1/20            | 0/20         | 19/20 | 20/20  |
   | 3200 px     | 6.6           | 9/20            | 20/20        | 20/20 | 20/20  |
   | 4000 px     | 8.3           | 5/20            | 20/20        | 20/20 | 20/20  |

   So Aruco wins the first pass by a wide margin, which is why `read` asks it first. What
   this table does **not** say is why, and the earlier version of this docstring said the
   wrong thing: it blamed the board's own grid of dark squares. Measured against that, with
   the sixteen squares taken out of the same picture and everything else identical: at
   2400 px plain read 0/20 without them against 1/20 with them, Aruco 19/20 against 18/20.
   The squares are worth nothing either way. Take the *photograph* away instead — the same
   plank with its squares, unturned, unblurred, uncompressed — and plain reads 59 of 60 at
   2400 px, and 20 of 20 at every width from 1200 px up. It is the photograph, and of its
   four steps the blur is the one that decides (see the note under the table below). A board
   photograph is exactly what this route gets, so the order stands; the plain detector stays
   as the fallback for an OpenCV older than 4.7, where it is all there is.
3. **How big the code has to be in the frame.** Same harness, forty freshly minted uids per
   rung, through `read` (so counting its 2x retry): 1200 px 0/40, 1600 px **16/40**,
   2000 px 40/40, 2400 px 40/40, 3200 px 40/40 — 2.5, 3.3, 4.1, 5.0 and 6.6 px per module.
   So 4 px per module is where it starts working; 3.3 is the rung where it depends on the
   uid (16/40 here, 6/20 and 10/20 in two smaller runs of the same harness), and that is
   the one to distrust. For an 18 mm code that means a 300 mm board photographed at 2000 px
   across or better. Any phone does that; **the 1600 px copy a contribution keeps does
   not**. Decode the upload, never the downsized copy.

   Two things the same harness says about the numbers themselves. The retry is what carries
   the middle of the table: at 4.1 px per module Aruco alone read 7/20 and `read` 20/20.
   And the pixel floor is a property of the *picture*, not of the code — drop only the blur
   out of `photograph()` and 1200 px goes from 0/20 to 14/20 or better. An earlier round
   quoted a far more forgiving pair for the two bottom rungs (1200 px 34/40, 1600 px 36/40)
   in a commit message and in `docs/test-grid.md`; it is not reproducible with the blur on,
   and both have been corrected to the table above. Anybody measuring this again: blur and
   compress, or you are measuring a screen and not a plank.

**How it burns.** As a raster layer at `CODE_DPI`, never an engrave layer:
`op_engrave.as_cutobjects` (`meerk40t/core/node/op_engrave.py:358+`) takes
`final_geometry(...).as_path()` and traces it — fill is never consulted — so 212 filled
modules come out of the machine as 212 little outlines with unburned wood inside each one,
and nothing reads that. Measured on a headless kernel with our own rasteriser, an 18 mm
code at the caption layer's 80 mm/s:

| layer                        | cut objects | seconds |
|------------------------------|-------------|---------|
| `op engrave` (unreadable)    | 848         | 7.9     |
| `op raster` @ 500 dpi        | 1           | 46.4    |
| `op raster` @ 250 dpi        | 1           | 23.5    |
| **`op raster` @ `CODE_DPI`** | **1**       | **15.8**|
| `op raster` @ 125 dpi        | 1           | 12.0    |

So a code adds **one** cut object and about 16 s to a board that takes 57–60 s. The 500 dpi
row is why the dpi is pinned here rather than left to a form: 46 s of code nearly doubles a
small board, and that is the kind of number that gets a feature switched off. The seconds
move with the speed the caption burns at — the same code is 6.3 s at 200 mm/s — and with the
size: 9.9 s at 14 mm, 23.1 s at 22 mm.

The module has no kernel and no library in it on purpose: arithmetic and pixels only, so
`plan` can be previewed and `read` can be tried without a machine. The drawing, the
refusals about board room and the missing-rasteriser guard belong to `testgrid.py`.
"""

from __future__ import annotations

import secrets

from .edits import DesignError, _finite, _positive
from .generators import qr_squares

#: Which scheme this is, so a second one can exist later without a reader having to
#: guess. `MK1` is a machine (`machines.UID_PREFIX`), `OK1` is a board.
UID_PREFIX = "OK1"

#: Crockford base32: no I, L, O or U. A board code is printed under the code in
#: human-readable form precisely so it can be typed when no camera is at hand, and these
#: four are the characters that get typed as something else. Same alphabet as the machine
#: uid (`machines.UID_ALPHABET`), for the same reason.
UID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
UID_LENGTH = 8

#: What a reader may write instead. Crockford's own rule: I and L are ones, O is a zero.
#: U is refused rather than guessed — it is not in the alphabet, so a U means the reader
#: has read something else wrong as well and a silently corrected uid would name a board
#: nobody meant.
CONFUSIONS = {"I": "1", "L": "1", "O": "0"}

#: Four modules of empty material, the standard quiet zone, where the public QR generator
#: draws two (`generators.QR_QUIET_DEFAULT`). Re-measured, because what stood here was true
#: of one harness and read as true of all of them: with the code rendered on its own, so the
#: pattern runs to the edge of the picture, no quiet zone never decodes (0 of 20 at 3, 6 and
#: 12 px per module) while two and four both read 20 of 20 at 6 — and at 3 px per module two
#: read 16 of 20 against four's 13, which is the other way round from what was claimed.
#: On a *plank*, which is what a photograph of a board is, even a quiet zone of zero read
#: 20 of 20 at 6 px per module: the unburned material around the code is the quiet zone.
#: So this default is not what makes a code readable in a frame — it is the margin that
#: keeps the caption, the squares and the rim out of the pattern, which is why the code also
#: gets `testgrid.CODE_GAP_MM` of board to itself. The cost at the default module size is 4.97 mm of
#: the 18 mm footprint. Wood is not paper: char at the edge of the pattern eats into that
#: margin, and that is exactly the direction no measurement covers yet.
QUIET_MODULES = 4

#: The line spacing the code burns at, in dots per inch — pinned here rather than settable.
#: Measured on a headless kernel for an 18 mm code: 15.8 s at 167 dpi, 23.5 s at 250,
#: 46.4 s at 500 (the engine's default) and 12.0 s at 125. 167 dpi is 0.15 mm per line,
#: roughly four overlapping lines across a 0.62 mm module, and a quarter of the burn time
#: of a small board rather than the whole of it.
CODE_DPI = 167

#: The default footprint, quiet zone included. 18 mm over 29 modules is a 0.621 mm module,
#: which clears the rule of thumb that a module wants to be at least three kerfs wide
#: (0.2 mm on a CO2 tube). Settable, because nobody has burned one yet.
DEFAULT_SIZE_MM = 18.0

#: Below this the code is refused outright rather than warned about: 12 mm over 29 modules
#: is a 0.414 mm module — two kerfs wide, so the laser would decide where the module edges
#: are — and 5 px per module then wants a 300 mm board photographed at 3600 px across. A
#: code that cannot be read is not a smaller feature, it is burn time and a board that
#: still cannot say who it is.
MIN_SIZE_MM = 12.0

#: Between `MIN_SIZE_MM` and this it is drawn with a warning. 14 mm is a 0.483 mm module,
#: which asks for a 3100 px photograph of a 300 mm board where 18 mm asks for 2400 — the
#: difference between every phone and a good one.
SMALL_SIZE_MM = 14.0

#: The same shape as `camera.IMPORT_HINT`, and for the same reason: OpenCV is not part of
#: MeerK40t's installation and must not become a dependency of this app. Without it the
#: board still burns its code and the picker still works — only the reading back is gone.
NO_DECODER_HINT = (
    "Reading codes from photographs needs OpenCV. Install it beside the engine with "
    "'pip install opencv-python-headless'."
)


# ------------------------------------------------------------------- identity


def mint_uid() -> str:
    """A fresh board uid: 40 bits from `secrets`, spelled in Crockford base32."""
    return "".join(secrets.choice(UID_ALPHABET) for _ in range(UID_LENGTH))


def payload(uid: str) -> str:
    """What goes in the QR code: `OK1:7X4MQB2K`."""
    return f"{UID_PREFIX}:{_valid(uid)}"


def human(uid: str) -> str:
    """
    What goes in the caption under it: `7X4M QB2K`.

    Two groups of four, because that is how a person reads eight characters back off a
    plank without losing their place. The prefix is left off: it is the same on every
    board, so it would be four characters of noise in a caption that is already competing
    for room with the material, the thickness and the date.
    """
    uid = _valid(uid)
    return f"{uid[:4]} {uid[4:]}"


def parse(text: str | None) -> str | None:
    """
    The uid in whatever a reader gives us, or None when there is none.

    Three sources feed this and all three are messy: a QR code that decoded (`OK1:7X4MQB2K`),
    a person typing what is printed on the board (`7x4m qb2k`), and a photograph that
    happened to catch somebody's Wi-Fi sticker as well. So: case is ignored, spaces and
    hyphens are ignored, the prefix is optional, I and L become 1 and O becomes 0 — and
    anything that is not eight characters of this alphabet afterwards is not a board code
    and gets None rather than a guess.
    """
    if not text:
        return None
    cleaned = str(text).strip().upper()
    for junk in (" ", "-", "_", "\t"):
        cleaned = cleaned.replace(junk, "")
    if cleaned.startswith(UID_PREFIX + ":"):
        cleaned = cleaned[len(UID_PREFIX) + 1 :]
    elif cleaned.startswith(UID_PREFIX) and len(cleaned) == len(UID_PREFIX) + UID_LENGTH:
        # A decoder that swallowed the colon, and a person who never typed one.
        cleaned = cleaned[len(UID_PREFIX) :]
    cleaned = "".join(CONFUSIONS.get(char, char) for char in cleaned)
    if len(cleaned) != UID_LENGTH:
        return None
    if any(char not in UID_ALPHABET for char in cleaned):
        return None
    return cleaned


def _valid(uid: str) -> str:
    """A uid we minted ourselves, or a clear refusal — never a code that reads back wrong."""
    parsed = parse(uid)
    if parsed is None:
        raise DesignError(
            f"'{uid}' is not a board code.",
            code="library.grid.codeUnreadable",
        )
    return parsed


# ------------------------------------------------------------------- drawing


def plan(
    uid: str,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    size_mm: float = DEFAULT_SIZE_MM,
    quiet: int = QUIET_MODULES,
) -> dict:
    """
    The code as filled squares in millimetres, ready for the board to place.

    `x_mm, y_mm` is the top-left of the whole footprint, quiet zone included, and
    `size_mm` is that footprint's side — so the caller reserves `size_mm` of board and
    everything inside it is this code's business. What comes back:

    - `squares`: one closed four-point polygon per dark module, in millimetres. Filled,
      not outlined, and that word is load-bearing — see the module docstring on
      `op_engrave.as_cutobjects`.
    - `modules` 29 and `dark` the number of them that burn. That varies with the uid,
      since the payload does: measured over 500 minted uids, 202 to 242 of the 441, mean
      226. `7X4MQB2K` is 212.
    - `module_mm`: 0.621 at the default size.
    - `quiet_mm`: what the quiet zone costs on **one** side, 2.48 mm at the default — so
      4.97 mm of an 18 mm code is empty material and the pattern itself is 13.03 mm.
    - `dpi`: `CODE_DPI`, for the raster layer the caller makes.
    - `warnings`: `boardcode.smallCode` below `SMALL_SIZE_MM`, with the numbers in it.

    A size under `MIN_SIZE_MM` is refused rather than warned about, because a code that
    cannot be read is not a smaller version of the feature — measured, a 12 mm code is
    still 7.3 s of burning for a board that afterwards still cannot say who it is.
    """
    uid = _valid(uid)
    size = _positive(size_mm, "size_mm")
    quiet = int(_finite(quiet, "quiet"))
    if not 0 <= quiet <= 8:
        raise DesignError("The quiet zone has to be between 0 and 8 modules.")
    if size < MIN_SIZE_MM:
        raise DesignError(
            f"A board code smaller than {MIN_SIZE_MM:g} mm cannot be read back; "
            f"{size:g} mm was asked for.",
            code="library.grid.codeTooSmall",
            values={"min_mm": MIN_SIZE_MM, "asked_mm": round(size, 2)},
        )

    squares, modules = qr_squares(
        payload(uid), _finite(x_mm, "x_mm"), _finite(y_mm, "y_mm"), size, quiet
    )
    module_mm = size / modules

    warnings = []
    if size < SMALL_SIZE_MM:
        warnings.append(
            {
                "code": "boardcode.smallCode",
                "text": (
                    f"A {size:g} mm code has {module_mm:.2f} mm modules; photograph the "
                    "board from close by, or make the code bigger."
                ),
                "values": {"size_mm": round(size, 2), "module_mm": round(module_mm, 3)},
            }
        )

    return {
        "uid": uid,
        "payload": payload(uid),
        "human": human(uid),
        "x_mm": _finite(x_mm, "x_mm"),
        "y_mm": _finite(y_mm, "y_mm"),
        "size_mm": size,
        "modules": modules,
        "quiet": quiet,
        "dark": len(squares),
        "module_mm": module_mm,
        "quiet_mm": quiet * module_mm,
        "dpi": CODE_DPI,
        "squares": squares,
        "warnings": warnings,
    }


# ------------------------------------------------------------------- reading


def available() -> bool:
    """Whether this copy of OpenKerf can read a code from a photograph at all."""
    return _opencv() is not None


def read(image) -> list[str]:
    """
    The board uids in a photograph, most likely one — and `[]` when there are none.

    Takes the bytes of an upload, a path, or an image OpenCV already has. Never raises for
    a picture it cannot read: no OpenCV, an unreadable file, a photograph of a thumb, a QR
    code that turns out to be somebody's Wi-Fi — all of those are "no board named itself
    here", which is a fallback to the picker and not an error. The refusals that *are*
    errors (no decoder installed, a code naming a different board) are the caller's, where
    the caller knows what the user asked for.

    Two decoders and one retry, all three measured on the synthetic board photograph the
    module docstring tabulates. Aruco first because it wins the first pass on a photograph
    by a distance — 19 of 20 against 1 of 20 at 5.0 px per module — and not because of the
    board's own dark squares, which measure the same with them and without them.
    `detectAndDecodeMulti` because a photograph of a board may hold more than one code. And
    a 2x cubic upscale when nothing was found, which is what carries the middle of that
    table: at 4.1 px per module Aruco alone read 7 of 20 and this function 20 of 20. The
    retry costs nothing when the first pass already read the code.
    """
    cv2 = _opencv()
    if cv2 is None:
        return []
    picture = _as_grey(cv2, image)
    if picture is None:
        return []

    found = _decode(cv2, picture)
    if not found:
        try:
            bigger = cv2.resize(
                picture, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC
            )
        except Exception:  # pragma: no cover - a picture OpenCV will not resize
            bigger = None
        if bigger is not None:
            found = _decode(cv2, bigger)

    uids: list[str] = []
    for text in found:
        uid = parse(text)
        if uid is not None and uid not in uids:
            uids.append(uid)
    return uids


def _opencv():
    """OpenCV, or None. Optional on purpose; see `NO_DECODER_HINT`."""
    try:
        import cv2
    except ImportError:
        return None
    return cv2


def _detectors(cv2) -> list:
    """
    The detectors to try, in the order that was measured.

    `QRCodeDetectorAruco` is OpenCV 4.7 and up; without it the plain detector is all there
    is. On its own that one reads a clean render at any size and a board photograph only
    from about 6.6 px per module — a 300 mm board at 3200 px across — but with the 2x retry
    `read` does around it, it measured 20 of 20 at 4.1 px per module, so an older OpenCV is
    a slower first pass rather than a broken feature. And the printed line under the code is
    still there for whoever has neither.
    """
    detectors = []
    for name in ("QRCodeDetectorAruco", "QRCodeDetector"):
        maker = getattr(cv2, name, None)
        if maker is None:
            continue
        try:
            detectors.append(maker())
        except Exception:  # pragma: no cover - a build that ships the name but not the code
            continue
    return detectors


def _decode(cv2, picture) -> list[str]:
    """Every string any detector reads out of this picture."""
    texts: list[str] = []
    for detector in _detectors(cv2):
        for attempt in ("detectAndDecodeMulti", "detectAndDecode"):
            method = getattr(detector, attempt, None)
            if method is None:
                continue
            try:
                result = method(picture)
            except Exception:
                # OpenCV throws on some pictures rather than saying "nothing here".
                continue
            if attempt == "detectAndDecodeMulti":
                ok, decoded = result[0], result[1] if len(result) > 1 else []
                if ok and decoded is not None:
                    texts += [str(t) for t in decoded if t]
            else:
                text = result[0] if isinstance(result, tuple) else result
                if text:
                    texts.append(str(text))
            if texts:
                # The multi call already answered; the single one would only repeat one of
                # the codes it found, and on a 12-megapixel photograph that is not free.
                break
        if texts:
            break
    return texts


def _as_grey(cv2, image):
    """
    Whatever the caller has, as a single-channel picture — or None.

    Grey and not colour because every detector wants grey anyway, and because a phone
    photograph of a plank is 12 megapixels: converting once here is cheaper than letting
    two detectors and a retry each do it.
    """
    import numpy as np

    if isinstance(image, (bytes, bytearray, memoryview)):
        buffer = np.frombuffer(bytes(image), dtype=np.uint8)
        if not buffer.size:
            return None
        return cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if isinstance(image, np.ndarray):
        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image
    try:
        return cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
    except Exception:  # pragma: no cover - a path OpenCV will not even look at
        return None
