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
2. **Which OpenCV detector.** On a synthetic photograph of a whole board — the code plus
   sixteen grey squares, 5 degrees of rotation, blur and JPEG 85 —
   `QRCodeDetector().detectAndDecode` read 1 of 10 at 8.3 px per module, while
   `QRCodeDetectorAruco().detectAndDecodeMulti` read 9 of 10 at 5 px per module. The dark
   squares of the board itself are what the plain detector loses the code in, and a board
   photograph always has them. So `read` asks Aruco first and keeps the plain detector as
   the fallback for an older OpenCV.
3. **How big the code has to be in the frame.** Same synthetic board, an 18 mm code on a
   300 mm board, counting the 2x retry `read` does: 1200 px wide 0/20, 1600 px **6/20**,
   2000 px 20/20, 2400 px 20/20, 3200 px 20/20. In modules that is 2.5, 3.3, 4.1, 5.0 and
   6.6 px per module. So about 4 px per module is where it starts working and 5 is where it
   is comfortable — for an 18 mm code, a 300 mm board photographed at 2400 px across. Any
   phone does that; **the 1600 px copy a contribution keeps does not**, at 6 of 20. Decode
   the upload, never the downsized copy. On a clean render straight from `plan` the floor is
   far lower, 2 px per module, which is the difference between a screen and a plank.

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
#: draws two (`generators.QR_QUIET_DEFAULT`). Through a simulated photograph two decoded 16
#: of 20 at 6 px per module against four at 20 of 20, and zero never decodes at all: 0 of
#: 20 from 1 to 12 px per module. What the two extra modules a side cost, at the default
#: module size, is 1.24 mm a side — 2.48 mm of board width, and 4.97 mm of the 18 mm
#: footprint is quiet zone rather than pattern. Wood is not paper: char at the edge of the
#: pattern eats into that margin, and that is exactly the direction no measurement covers
#: yet.
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

    Two decoders and one retry, all three measured on a synthetic board photograph (see the
    module docstring): Aruco first because the plain detector loses the code among the
    board's own dark squares (1 of 10 against 9 of 10), `detectAndDecodeMulti` because a
    photograph of a board may hold more than one code, and a 2x cubic upscale when nothing
    was found — that retry took 10 of 20 to 20 of 20 at 4.1 px per module and 18 of 20 to
    20 of 20 at 5.0, and costs nothing when the first pass already read the code.
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
    is, which reads a clean render fine and a board photograph badly. Better than nothing,
    and the printed line under the code is the answer for whoever is stuck with it.
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
