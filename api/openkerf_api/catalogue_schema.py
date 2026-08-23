"""
What a catalogue entry has to look like before we touch it.

The Presetariat is the one feature in this layer whose input comes from strangers.
Everything else on the way to the laser is either the user's own drawing or the
engine's own registry; this arrives over HTTP from a repository anybody may open a
pull request against. So it is the one feature that has to assume the file is wrong.

Measured before this module existed, on the exact catalogue shape
`api/tests/test_presetariat.py` builds: a single bare string in the `presets` array
crashes `browse()` with `AttributeError: 'str' object has no attribute 'get'` at
`presetariat.py:114`, which leaves the route as a 500 with no sentence. One malformed
row therefore took the whole catalogue down — including the twenty-five good rows
beside it.

## Skip and count, never raise

A bad *entry* is skipped and counted; only a bad *envelope* is refused. That asymmetry
is deliberate. A reader whose catalogue is one row short can still work; a reader whose
catalogue is a 500 cannot do anything at all, and cannot tell why. The count travels
back so the interface can say "two entries in this catalogue were not understood"
instead of pretending the set is complete.

## Why the checks are shallow

These are not the repository's schema — that lives in the catalogue repository's own
`schema/*.json` and runs in CI, where a maintainer can act on a failure and a
contributor is told what to change. This is the client's own guard,
and its whole job is that no field we later read can be of a type we do not expect.
So it checks the types and the ranges that would otherwise reach a `float()`, a
`.get()` or the laser, and it lets everything else through. A stricter client would
reject rows a newer, still-compatible catalogue is entitled to add — which is what
`schema_version` is for, and that is checked once for the whole file rather than
guessed at per row.

No new dependency: `jsonschema` would be the obvious tool and it is one more wheel in
an install that already asks for numpy, Pillow and pyusb, for about sixty lines of
`isinstance`.
"""

from __future__ import annotations

import math
import re

# The four operations a preset may name (`library.py:132`), imported rather than
# repeated so that a fifth cannot be accepted here and refused two calls later inside
# `add_preset`. Those four are stored values and stay Dutch, per the carve-out in
# CLAUDE.md — they never reach a screen as themselves.
from .library import OPERATIONS

#: The highest `schema_version` this client understands. A catalogue that says more
#: than this is refused whole rather than read half — a field we silently ignore is
#: how a future "this preset needs two passes" becomes one pass on somebody's plate.
SUPPORTED_SCHEMA = 2

#: The laser kinds a catalogue entry may claim. `uv` is its own value and not an
#: alias of `fiber`: a UV laser is a frequency-tripled solid-state source and its
#: settings transfer to a fibre marker about as well as a CO2's would.
LASER_KINDS = frozenset(
    {"co2-glass", "co2-rf", "diode", "fiber", "uv", "unknown"}
)

#: `measured` means somebody burned it and there is a board behind it;
#: `starting_point` means somebody typed a number they believed. All twenty-six
#: entries in the live catalogue are the second kind, which is why the tier is a
#: label and a sort order and never a default filter.
TIERS = frozenset({"measured", "starting_point"})

#: Crockford base32 without I, L, O and U, the alphabet the board code is minted in
#: (`OK1` plus eight characters). Anchored, because a uid that is a prefix of a
#: filename is how a board photograph ends up filed under the wrong board.
BOARD_UID = re.compile(r"^OK1[0-9A-HJKMNP-TV-Z]{8}$")


def check_preset(entry) -> str | None:
    """
    Why this preset cannot be used, or `None` when it can.

    The reason is a short English phrase for a log and for the skipped-count in the
    response; it is not a sentence shown to a reader, because a reader cannot fix
    somebody else's catalogue. Returning the reason rather than a bool is what lets
    the caller say *which* two rows it dropped when a maintainer asks.
    """
    if not isinstance(entry, dict):
        # The measured crash: `presetariat.py:114` called `.get` on a bare string.
        return f"not an object but {type(entry).__name__}"

    for field in ("id", "material", "operation"):
        if not _text(entry.get(field)):
            return f"{field} is missing"
    if entry["operation"] not in OPERATIONS:
        return f"unknown operation {entry['operation']!r}"

    if (why := _positive(entry.get("speed_mm_s"), "speed_mm_s")) is not None:
        return why
    power = entry.get("power_percent")
    if (why := _positive(power, "power_percent")) is not None:
        return why
    if float(power) > 100:
        # A percentage above 100 is not a stronger burn, it is a controller that
        # clips or refuses. The live catalogue holds none; a typo would.
        return f"power_percent {power} is above 100"

    if (why := _optional_positive(entry.get("thickness_mm"), "thickness_mm")) is not None:
        return why
    if (why := _optional_positive(entry.get("passes"), "passes")) is not None:
        return why
    if (why := _optional_number(entry.get("focus_offset_mm"), "focus_offset_mm")) is not None:
        return why

    machine = entry.get("machine")
    if machine is not None:
        if not isinstance(machine, dict):
            # Measured shape of a hand-written entry: `"machine": "80W"`. Every
            # caller here does `machine.get("laser_type")`.
            return f"machine is {type(machine).__name__}, not an object"
        kind = machine.get("laser_type")
        if kind is not None and kind not in LASER_KINDS:
            return f"unknown laser_type {kind!r}"
        if (why := _optional_positive(machine.get("power_watt"), "power_watt")) is not None:
            return why
        if (why := _optional_positive(machine.get("lens_mm"), "lens_mm")) is not None:
            return why

    tier = entry.get("tier")
    if tier is not None and tier not in TIERS:
        return f"unknown tier {tier!r}"
    board = entry.get("board")
    if board is not None and not BOARD_UID.match(str(board)):
        return f"board {board!r} is not a board uid"

    source = entry.get("source")
    if source is not None and not isinstance(source, dict):
        # `_confidence` in presetariat.py reads `source["kind"]` to sort by.
        return f"source is {type(source).__name__}, not an object"
    synonyms = entry.get("synonyms")
    if synonyms is not None and not _list_of_text(synonyms):
        return "synonyms is not a list of names"
    return None


def check_board(entry) -> str | None:
    """
    Why this board cannot be used, or `None` when it can.

    A board is the evidence behind a measured preset: the tile, its photograph and
    the grid it was burned from. Less of it is read by this client than of a preset —
    today only the uid, to tie a preset to its picture — so the checks are the uid,
    the types of what we would show, and nothing else.
    """
    if not isinstance(entry, dict):
        return f"not an object but {type(entry).__name__}"
    uid = entry.get("uid")
    if not _text(uid) or not BOARD_UID.match(str(uid)):
        return f"uid {uid!r} is not a board uid"
    if (why := _optional_positive(entry.get("thickness_mm"), "thickness_mm")) is not None:
        return why
    for field in ("rows", "columns"):
        if (why := _optional_positive(entry.get(field), field)) is not None:
            return why
    machine = entry.get("machine")
    if machine is not None and not isinstance(machine, dict):
        return f"machine is {type(machine).__name__}, not an object"
    photo = entry.get("photo")
    if photo is not None and not _text(photo):
        return "photo is not a path"
    return None


# ------------------------------------------------------------------ the small print


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list_of_text(value) -> bool:
    return isinstance(value, list) and all(isinstance(s, str) for s in value)


def _number(value) -> float | None:
    """
    `value` as a float, or None when it is not a usable number.

    `bool` is excluded on purpose: `True` is an int in Python, so `"passes": true`
    would otherwise pass as one pass and burn.  NaN and infinity are excluded because
    they survive every comparison below and only fail at the machine.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive(value, field: str) -> str | None:
    number = _number(value)
    if number is None:
        return f"{field} is not a number"
    if number <= 0:
        return f"{field} is {value}"
    return None


def _optional_positive(value, field: str) -> str | None:
    return None if value is None else _positive(value, field)


def _optional_number(value, field: str) -> str | None:
    if value is None:
        return None
    return None if _number(value) is not None else f"{field} is not a number"
