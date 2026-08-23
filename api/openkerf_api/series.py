"""
Series: one design, burned once per row of a list.

Fifty keyrings with fifty different names on them is one drawing and fifty burns.
The design carries a text that reads `{name}`; the list carries the names; each burn
takes the next row. This module is the arithmetic of that: reading the list, finding
the placeholders in a text, and working out how many rows one burn eats.

## Why the rows are ours and the substitution is not

The substitution belongs to the engine and stays there. `{name}` is the engine's own
syntax and the engine resolves it at three places we do not own — when a vector text
node is created (`extra/hershey.py:504`), when it is re-rendered
(`extra/hershey.py:355`), and once more while the cut plan is being built
(`core/cutplan.py:325`). Writing our own renderer would mean the bed and the burn
each substituting on their own, which is precisely the bug this feature exists to
end. So we hand the engine the rows and let it do the replacing.

The *reading* of the list is ours, because the engine's loader
(`core/wordlist.py:809`, `load_csv_file`) mishandles the files people actually have.
All four of these were measured this week against the working copy, on the exact
bytes the tests in `api/tests/test_series.py` use:

- **A Dutch Excel export is refused outright.** `load_csv_file` decodes through
  `EncodingDetectFile` (`extra/encode_detect.py`), which declares `ENCODING_CP1252`
  at line 17 and never returns it from any branch. So a semicolon file with `René`
  in it returns `(0, 0, [])` and one warning nobody sees.
- **A one-column list is read as gibberish, or crashes.** The loader hands a 1 kB
  buffer to `csv.Sniffer().sniff()` (`core/wordlist.py:865`) with no candidate list.
  Measured: `b"name\\r\\nAnna\\r\\nBram\\r\\n"` sniffs the delimiter `"a"` and loads as
  three rows over two columns called `column_1`/`column_2`; `b"serial\\r\\n001\\r\\n"`
  sniffs `"\\r"` and raises `ValueError: bad delimiter value None` straight out of
  the loader. That is why our delimiter is *counted* over a fixed set of four
  characters and can never be a carriage return.
- **A quote inside a cell throws the file away.** `core/wordlist.py:831` counts double
  quotes over the whole file and abandons the import on an odd number, so a size
  column reading `5" pipe` loses the list rather than the quote.
- **The header row is a coin flip.** `csv.Sniffer().has_header()`
  (`core/wordlist.py:852`) said False for `name,city` over two names, True for
  `code,size` over two codes, and raised on `serial` over three numbers. Guessing is
  fine; guessing silently is not. We guess, report the guess, and let the window ask.

## The engine facts this design rests on

- `_BRACKETS = re.compile(r"\\{[^}]+\\}")` (`core/wordlist.py:35`) is the whole of the
  template syntax. `placeholders()` below re-implements the parsing that follows it at
  `core/wordlist.py:507-535` exactly, quirks and all, because a preview that disagrees
  with the burn is worse than no preview.
- Keys are lower-cased and stripped on the way in (`_normalize_key`,
  `core/wordlist.py:143`). A column called `Naam` and one called `naam` are therefore
  one variable to the engine. We keep the reader's own spelling — a column name is
  their data, not our label — and put the case-insensitive comparison in one place,
  `find_column()`, so no caller has to remember.
- Names the engine keeps for itself are refused as columns. Measured:
  `set_value("date", …)` appends to the built-in and `{date}` still resolves to the
  built-in's own value, so a column called `date` would silently do nothing at all.
- An offset that reads past the end of the list is not substituted:
  `core/wordlist.py:597` only replaces when the value is not None, so `{name#+2}` on
  the last sheet stays in the text and is engraved as those nine characters. That is
  what `step_of()` is for and what the plan's overrun mutator removes.
- There is no escape for a curly bracket. Measured: a cell holding `a { b } c`
  survives one pass and renders `a  c` on the second, because the pattern is scanned
  once (`core/wordlist.py:507`) and anything the substitution inserts is scanned by
  whatever translates the text next. So a bracket in a cell cannot be burned
  faithfully and is refused here instead.

## What is in here, in two halves

Everything down to `burn_rows` is pure: bytes and strings in, dicts and numbers out,
no kernel, no files, no HTTP. That is deliberate — it is the half where a mistake
costs a plate of material, so it is the half that is fully tested under plain pytest.

Between the two halves sits `OverrunMutator`, the one thing in here that touches a
plan: it takes the places off the last sheet that the list has no rows left for, and
the jig frame off every burn after the first. It decides both with the engine's own
substitution rather than with arithmetic of ours, for the reason above.

`Series` below it is the state object, and it needs a kernel. It owns three things and
no more: the list on disk, which row the bed is pointing at, and the engine's wordlist
as a write-only register. Its shape is `tilerun.py`'s, down to `_read`/`_write` and a
sha1 fingerprint, because it is the same problem — an afternoon's work that has to
survive a page refresh — and two answers to one problem is one too many.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .edits import DesignError

#: How many rows we carry. A workshop does not read a two-thousand-row list, and
#: paging is code written for a reader who does not exist. If somebody arrives with
#: five thousand rows that is a measurement worth having before writing a pager, and
#: raising this number is a one-line change.
MAX_ROWS = 1000

#: The only characters we will treat as a delimiter, counted in this order so that a
#: tie goes to the comma. A carriage return is deliberately absent: it is what the
#: engine's sniffer picks for a one-column file, and it is what makes `csv.reader`
#: raise instead of read.
DELIMITERS = (",", ";", "\t", "|")

#: How many rows the delimiter vote looks at. Enough to see the shape of the file,
#: few enough that a thousand-row list is parsed in full exactly once.
PEEK_ROWS = 50

#: Names the engine keeps for itself, from `Wordlist.prohibited`
#: (`core/wordlist.py:124`) plus the `date@`/`time@` format forms it handles
#: specially at `core/wordlist.py:558-563`. A column with one of these names would be
#: accepted by `set_value` and then never resolve, because `translate` answers `date`
#: and `time` from the clock before it ever looks at the content.
RESERVED_COLUMNS = ("version", "date", "time")
RESERVED_PREFIXES = ("op_", "date@", "time@")

#: A part number is not twelve digits wide. Padding beyond this is a typo, and a typo
#: that would put a thousand rows of zeroes on somebody's material.
MAX_PADDING = 12


def reserved_column(name: str) -> bool:
    """
    Whether the engine would answer this name itself instead of from our rows.

    The interface needs the same answer for a column of a file and for a placeholder
    typed into a text, so the rule lives here once. Case-insensitive, because the
    engine lower-cases every key it is given (`core/wordlist.py:143`).
    """
    key = (name or "").strip().lower()
    if key in RESERVED_COLUMNS:
        return True
    return any(key.startswith(prefix) for prefix in RESERVED_PREFIXES)


def require_column_name(name: str) -> str:
    """
    The two refusals a column name can earn, in one place.

    Called for every name in an imported file and for the column name of a numbered
    list, so a name that is refused on import cannot arrive by the other door.
    """
    text = (name or "").strip()
    if "{" in text or "}" in text:
        raise DesignError(
            "A column name cannot contain a curly bracket, because that is what "
            "marks a placeholder. Rename the column in your file.",
            code="series.badColumnName",
        )
    if reserved_column(text):
        raise DesignError(
            "A column cannot be called date, time or version, or begin with op_ — "
            "the engine keeps those names. Rename the column in your file and "
            "import it again.",
            code="series.reservedColumn",
        )
    return text


def find_column(columns, name: str):
    """
    The column a placeholder means, matched the way the engine matches it.

    The engine lower-cases and strips every key (`core/wordlist.py:143`), so `{Naam}`
    and `{naam}` are the same variable and a file may not hold both as two columns.
    We keep the reader's own spelling in `columns` and do the comparison here, so
    that "does the list have this column" is answered identically by the preview, the
    refusal and the priming.

    Returns the column as it is spelled in the list, or None.
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    for column in columns or ():
        if str(column).strip().lower() == key:
            return column
    return None


@dataclass(frozen=True)
class Placeholder:
    """
    One `{…}` run in a text, read the way the engine reads it.

    `text` is the run exactly as it stands in the template, braces included, so a
    caller can find it again in the string. `column` is lower-cased and stripped
    because that is the key the engine will look up. `offset` is how many rows past
    the current one it reads; `absolute` marks the `{name#2}` form, which is a fixed
    row and therefore does not make a burn eat more rows. `reserved` marks the
    engine's own names, which are not ghosts when the list has no such column.
    """

    text: str
    column: str
    offset: int
    absolute: bool
    reserved: bool


def placeholders(text: str) -> list[Placeholder]:
    """
    Every placeholder in a template, with its column and its offset.

    This is the engine's own parsing, re-walked line for line from
    `core/wordlist.py:507-535`, including three quirks that a cleaner
    re-implementation would get wrong and that were measured on a five-name list with
    the pointer on row 1:

    - the `#` has to be after the first character (`pos > 0`), so `{#3}` is a column
      called `#3` and not an index;
    - an index string that does not *start* with `+` or `-` is an absolute row, so
      `{name#2}` reads row 2 whatever the pointer says — and `{name# +1}` reads row 1,
      because the space means the `+` is no longer first. Measured: it rendered
      `Bram`, the second name, where `{name#+1}` rendered `Cees`;
    - the whole bracketed run is lower-cased and stripped before anything else, so
      `{ Name #+1 }` is the column `name` at offset 1.

    An index that is not a number at all falls back to offset 0, exactly as the
    engine's `except ValueError` does.
    """
    found = []
    for run in re.findall(r"\{[^}]+\}", str(text or "")):
        key = run[1:-1].lower().strip()
        offset = 0
        absolute = False
        position = key.find("#")
        if position > 0:
            index_string = key[position + 1 :]
            key = key[:position].strip()
            if not index_string.startswith("+") and not index_string.startswith("-"):
                absolute = True
            try:
                offset = int(index_string)
            except ValueError:
                offset = 0
        found.append(
            Placeholder(
                text=run,
                column=key,
                offset=offset,
                absolute=absolute,
                reserved=reserved_column(key),
            )
        )
    return found


def shift_placeholders(text: str, by: int) -> str:
    """
    The same template reading `by` rows further down the list.

    This is what makes a repeat take the next name: copy 1 of a text reading `{name}`
    reads `{name#+1}`, copy 2 reads `{name#+2}`, and a text reading `Part {code#+1}`
    keeps its own head start and becomes `Part {code#+2}`. Adding to whatever offset is
    already there rather than overwriting it is the only rule that keeps `step_of()`
    honest, because that is what decides how many rows one burn eats.

    Rebuilt in one pass over the pattern and deliberately **not** with `str.replace`:
    over `"{name} {name#+1}"` a replace of the first run turns it into the second and
    the second replacement then hits both, which came out as `{name#+2} {name#+2}` —
    two places engraving one row.

    What is left alone: an absolute `{name#2}` (a fixed row is a fixed row, on every
    copy), the engine's own names (`{date}` is the same date on all of them), and
    anything that is not a placeholder. The key keeps the reader's own spelling; only
    the whitespace inside the braces goes, which nothing can see.
    """
    step = int(by)
    if not step:
        return str(text or "")

    def moved(match) -> str:
        run = match.group(0)
        holder = placeholders(run)[0]
        if holder.absolute or holder.reserved or not holder.column:
            return run
        inside = run[1:-1].strip()
        # `find("#")` on the stripped run and not on the raw one, because that is where
        # the engine looks (`core/wordlist.py:518`): in `{ #3 }` the hash is the first
        # character of the key and therefore part of the name, not an index.
        cut = inside.find("#")
        name = inside if cut <= 0 else inside[:cut].strip()
        offset = holder.offset + step
        if offset == 0:
            return "{" + name + "}"
        return "{" + name + ("#+" if offset > 0 else "#-") + str(abs(offset)) + "}"

    return re.sub(r"\{[^}]+\}", moved, str(text or ""))


def columns_used(templates) -> list[str]:
    """
    The columns a set of texts actually reads, in the order they were met.

    Priming the engine writes only these — at the thousand-row cap that is the
    difference between a thousand `set_value` calls per list change and one per
    column that is really used. The engine's own names are left out: they answer
    themselves.
    """
    seen = []
    for template in templates or ():
        for holder in placeholders(template):
            if holder.reserved or not holder.column:
                continue
            if holder.column not in seen:
                seen.append(holder.column)
    return seen


def unknown_columns(templates, columns) -> list[str]:
    """
    The columns these texts ask for that the list has not got.

    Each one is a shape that would burn nothing: measured, the engine replaces an
    unknown key with the empty string (`core/wordlist.py:568`), the node's bounds come
    back as `(nan, nan, nan, nan)` and it drops out of the snapshot while still
    counting as burnable. Hence a refusal rather than a blank plate.
    """
    missing = []
    for column in columns_used(templates):
        if find_column(columns, column) is None and column not in missing:
            missing.append(column)
    return missing


def no_such_column(column: str) -> DesignError:
    """
    The one sentence for a placeholder no column fills, wherever it is met.

    Two moments raise it: the text field, where somebody has just typed the name, and
    `vet()` at the burn, which catches the same text arriving with an imported SVG or
    surviving a swapped list. One code carries one translated sentence, so a second
    wording would be two sentences under one key and the interface would show whichever
    was written last.

    The sentence names both ways out, because either is right depending on which of the
    two the reader got wrong: the placeholder, or the list.
    """
    return DesignError(
        f"There is no column called {column} in the list, so this text would burn "
        "nothing. Take the placeholder out of the text, or add the column to the list "
        "and import it again.",
        code="series.unknownColumn",
        values={"column": column},
    )


def require_known_columns(text, columns) -> None:
    """
    Refuse a placeholder the attached list cannot fill, while the text is being typed.

    `vet()` refuses the same thing at the burn and that is the gate that saves the
    material, but by then the operator is standing at the machine with a plate clamped
    down. Here they are still looking at the text field, and what they typed is on the
    screen in front of them.

    What it buys, measured through the routes with a list holding only `name`: placing a
    text reading `{nope}` answered 201, and the shape came back with `_translated_text`
    `''`, bounds `(nan, nan, nan, nan)` and **nought** elements in
    `DesignReader.snapshot()` — so it cannot be seen, clicked or dragged — while the
    Engrave layer went on reporting one element and `burns` true. Editing a working
    `{name}` into `{nope}` answered 200 and did the same thing to a shape that was
    visible a moment earlier: it simply disappeared, with no word anywhere until
    `/api/job/start` answered 409 at the machine.

    `columns` is a tri-state and that is the whole design of this gate:

    - **a list of names** is the list speaking. It knows what it has, so a placeholder
      naming something else is a mistake now and is refused now.
    - **`None`** means nobody can say — no list is attached, or the `Drawing` has no
      series behind it at all — and then a placeholder gets the benefit of the doubt.

    That second case is a decision and it goes the operator's way on purpose. A text
    with a placeholder and no list attached renders as nothing either, so refusing it
    would be defensible; but it would mean the spreadsheet has to arrive before the
    drawing may be finished, and the natural order of the work is the other one — draw
    the keyring, put `{name}` on it, import the names when the order comes in. The app's
    own headline flow is that order. And unlike a misspelled column, the state cures
    itself: attaching a list re-renders every text through the engine's own updater and
    the shape appears. An un-cured one is what the Series window's ghost list is for,
    and the burn is refused before any material moves.

    What that decision costs, measured, so that whoever revisits it has the case in
    front of them: a text whose *whole* content is a placeholder has no geometry while
    no list is attached, and the engine's SVG writer writes it as `<path d="">`.
    Reloading that file gives an `elem point` with no `mktext` on it and bounds
    `(nan, nan, nan, nan)`, and `GET /api/design` then answers 500 — `ValueError: Out
    of range float values are not JSON compliant` — so the canvas cannot be drawn at
    all. A placeholder with literal text beside it (`Plate {name}`) has geometry and
    survives. That hole is older than this feature, it is reachable without a series
    anywhere in sight, and it belongs to whoever owns the snapshot; it is written down
    here because it is the one thing that argues the other way.
    """
    if columns is None:
        return
    for holder in placeholders(text):
        if holder.reserved or not holder.column:
            continue
        if find_column(columns, holder.column) is None:
            raise no_such_column(holder.column)


def step_of(templates) -> int:
    """
    How many rows one burn eats: one more than the largest step forward.

    A sheet with twelve tags on it, reading `{name}`, `{name#+1}` … `{name#+11}`,
    consumes twelve rows per burn. That is the engine's own page idea — the wx
    wordlist editor pages by exactly this number (`gui/wordlisteditor.py:181-213`) —
    and it is re-derived from the design on every read rather than frozen when a run
    starts, because nudging a rectangle must not re-partition rows that are already
    burned.

    Absolute forms do not count: `{name#2}` is always row 2, so a sheet full of them
    still walks the list one row at a time. The wx editor's `establish_max_delta`
    agrees — it only takes an offset whose index string starts with a sign
    (`gui/wordlisteditor.py:205`) — and so does the engine's own resolution, which
    ignores the pointer entirely for the absolute form. Backwards offsets do not count
    either; they are refused where the text is typed.
    """
    biggest = 0
    for template in templates or ():
        for holder in placeholders(template):
            if holder.absolute or holder.reserved:
                continue
            if holder.offset > biggest:
                biggest = holder.offset
    return biggest + 1


def blank_counts(columns, rows) -> dict:
    """
    How many rows have nothing in each column.

    The window shows this per column, because a column that is blank in half its rows
    is the difference between forty plates and eighty. Measured before this feature: a
    blank cell produced no warning anywhere and a plate with a frame and no name.
    """
    counts = {}
    for column in columns or ():
        counts[column] = sum(
            1 for row in rows or () if not str(row.get(column, "")).strip()
        )
    return counts


def require_values(column: str, rows) -> None:
    """
    Refuse a column the design uses that is empty in every row.

    Separate from `blank_counts` because this one is a gate and not a number on a
    screen: every row blank means every burn is a plate with the frame and no name.
    """
    if rows and all(not str(row.get(column, "")).strip() for row in rows):
        raise DesignError(
            f"Every row is missing a value in {column}, so there is nothing to burn. "
            "Fill the column in, or switch off skipping blank rows.",
            code="series.everyRowBlank",
            values={"column": column},
        )


def _decode(data) -> tuple[str, str]:
    """
    The bytes as text, through the chain that survives the files people have.

    Byte-order marks first, because Excel's "Unicode text" and its "CSV UTF-8" both
    write one and both mean it. Then utf-8 strict, then cp1252 strict — that last one
    is the whole reason this function exists rather than a call to the engine's
    detector, which declares cp1252 at `extra/encode_detect.py:17` and never returns
    it, so every Dutch Excel export comes back as "could not read".

    cp1252 decodes nearly any byte, so the refusal below fires mostly for a file that
    is not text at all: a spreadsheet rather than an export of one. A NUL byte is the
    tell, and it is checked after decoding so that a genuine utf-16 file with a mark
    on it still gets through.
    """
    if isinstance(data, str):
        # A caller that already has text, in a test or behind a route that decoded for
        # its own reasons. Going through the same path keeps one set of rules.
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise DesignError(
            "This file is not text this app can read. Save it from your spreadsheet "
            "as CSV UTF-8 and try again.",
            code="series.unreadable",
        )
    raw = bytes(data)

    attempts = []
    if raw.startswith(codecs.BOM_UTF8):
        attempts.append("utf-8-sig")
    elif raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        # "utf-16" reads the mark itself and picks the byte order from it.
        attempts.append("utf-16")
    attempts += ["utf-8", "cp1252"]

    for encoding in attempts:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if "\x00" in text:
            # Two bytes per character, no mark, or a zip file with an .csv name on it.
            break
        return text, encoding
    raise DesignError(
        "This file is not text this app can read. Save it from your spreadsheet as "
        "CSV UTF-8 and try again.",
        code="series.unreadable",
    )


def _lines(text: str) -> str:
    """
    One kind of line ending, so that no delimiter vote can ever fall on a `\\r`.

    A carriage return inside a quoted cell becomes a newline inside that cell, which
    keeps the cell whole; anywhere else it was a line ending anyway. This is the one
    line of code that makes the engine's `ValueError: bad delimiter value None`
    impossible here.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split(text: str, delimiter: str) -> list[list[str]]:
    """
    The rows for one candidate delimiter, blank lines dropped.

    `csv.reader` and not a `split()`, so that a quoted comma stays inside its cell and
    an inch mark in the middle of a cell stays an inch mark — the two cases the
    engine's whole-file quote count throws the list away for.

    An empty line is dropped — every text editor ends a file with one — but a line
    of empty *cells* (`;;`) is kept, because that is a row somebody left blank in
    their spreadsheet and it has to show up in the burn list where it can be seen.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        if not row:
            continue
        if len(row) == 1 and not row[0].strip():
            # One blank field is a line with nothing on it, not a row of one blank cell:
            # under a delimiter this file does not use, that is what an empty line looks
            # like.
            continue
        rows.append(row)
    return rows


def _delimiter_of(text: str) -> str:
    """
    The delimiter, counted rather than sniffed.

    Each candidate parses the first `PEEK_ROWS` rows; the winner is the one that gives
    the widest row shape that most rows agree on. Wide beats agreeable, because a
    semicolon file read with commas gives one very consistent column, which is exactly
    the wrong answer and exactly what the engine's sniffer produced.

    A file no candidate splits is a one-column list, and then the delimiter does not
    matter — it is reported as a comma so that the window has something honest to
    show.

    The vote reads a sample and not the file, so a thousand rows are parsed once for
    real and four times over the first fifty lines. Cutting the sample on a newline
    can split a quoted cell that spans lines; a half-open quote costs the vote one row
    of shape and never reaches the rows themselves, which are parsed from the whole
    text.
    """
    sample = "\n".join(text.split("\n")[: PEEK_ROWS + 1])
    best = None
    for candidate in DELIMITERS:
        rows = _split(sample, candidate)[:PEEK_ROWS]
        if not rows:
            continue
        widths = Counter(len(row) for row in rows)
        width, agreeing = widths.most_common(1)[0]
        if width < 2:
            continue
        score = (width, agreeing / len(rows))
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else ","


def _is_number(cell: str) -> bool:
    """
    Whether a cell reads as a number, for the header guess only.

    A Dutch comma counts, because `3,5` in a semicolon file is a number to the person
    who typed it and the guess is about what they meant.
    """
    text = cell.strip().replace(",", ".")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _looks_like_a_header(first: list[str], rest: list[list[str]]) -> bool:
    """
    Our guess at whether the first row names the columns.

    Offered, never enforced: the window shows it as a two-way choice pre-filled with
    this answer, because the engine's `csv.Sniffer().has_header()` gave three
    different kinds of answer to three files of the same shape (False, True, and an
    exception) and the cost of being wrong is a name burned as a column heading or a
    column nobody can reference by name.

    The rule is deliberately dull: names are present, none of them is a number, none
    of them is long enough to be a sentence, and the row does not appear again further
    down. Its known limit is the file that is nothing but names — `Anna/Bram/Cees`
    without a heading is guessed to have one, because nothing in the bytes says
    otherwise. That is why the choice is asked.

    A file of one single line is judged on that line alone, and a line of plausible
    names is read as a heading with nothing under it. That earns the `series.noRows`
    refusal, which is the useful answer: one row is not a series, and a heading-only
    export is the ordinary way this file arrives.

    Trailing empty cells are ignored first, because `name;city;` is what a spreadsheet
    writes when the sheet has one column more than it fills — a blank *heading*, not a
    blank data cell.
    """
    cells = list(first)
    while cells and not cells[-1].strip():
        cells.pop()
    if not cells:
        return False
    if any(not cell.strip() for cell in cells):
        return False
    if any(_is_number(cell) for cell in cells):
        return False
    if any(len(cell.strip()) > 64 for cell in cells):
        return False
    return not any(row == first for row in rest)


def _name_columns(cells, has_header: bool, warnings: list) -> list[str]:
    """
    Column names from the first row, or invented ones.

    Blank becomes `column_<n>` and a repeat gets `_2`, both like the engine's own
    `make_unique` (`core/wordlist.py:960-973`) so that a file loaded either way lands
    on the same names. The repeat test is case-insensitive because the engine's keys
    are (`core/wordlist.py:143`): a file with `Naam` and `naam` holds one variable, and
    two columns that quietly become one is a wrong name on a plate.

    Every invented or renamed column is reported, so the window can say why a column
    is called `column_2` instead of leaving the reader to wonder.
    """
    names = []
    taken = {}
    renamed = []
    for index, cell in enumerate(cells):
        wanted = str(cell).replace("\ufeff", "").strip() if has_header else ""
        if not wanted:
            wanted = f"column_{index + 1}"
            if has_header:
                renamed.append(wanted)
        require_column_name(wanted)
        key = wanted.lower()
        if key in taken:
            taken[key] += 1
            wanted = f"{wanted}_{taken[key]}"
            renamed.append(wanted)
        else:
            taken[key] = 1
        names.append(wanted)
    if renamed:
        warnings.append(
            {
                "code": "series.renamedColumns",
                "text": (
                    "Some columns had no name or the same name twice, so they are "
                    f"called {', '.join(renamed)} here."
                ),
                "values": {"columns": renamed},
            }
        )
    return names


def _require_no_braces(rows, columns) -> None:
    """
    No curly bracket in any cell, because one cannot be burned as a bracket.

    There is no escape in the engine's syntax and there cannot be one: the pattern is
    `\\{[^}]+\\}` (`core/wordlist.py:35`), so `{{name}` matches from the second brace
    and yields a stray `}`. Measured, a cell holding `a { b } c` renders `a { b } c`
    on the first pass and `a  c` on the second, and there are two passes in a burn
    (`extra/hershey.py:355` for the bed, `core/cutplan.py:325` for the plan). So the
    cell is refused at the door rather than losing three characters somewhere between
    the screen and the ply.
    """
    for number, row in enumerate(rows, start=1):
        for column in columns:
            value = str(row.get(column, ""))
            if "{" in value or "}" in value:
                raise DesignError(
                    # The column is quoted because the commonest column in this
                    # feature is called `name`, and "a curly bracket in the column name"
                    # reads as a sentence about the column's *name*.
                    f"Row {number} has a curly bracket in the column \u201c{column}\u201d, "
                    "and a curly bracket cannot be burned as a bracket. Take it out of "
                    "the cell.",
                    code="series.braceInCell",
                    values={"row": number, "column": column},
                )


def read_rows(data, has_header=None) -> dict:
    """
    A list of rows out of the bytes of a CSV file.

    `has_header` is a choice and not a sniff: None means "use our guess", and the
    answer we would have given comes back as `header_guess` so the window can offer it
    pre-filled. Everything else about the file is measured rather than assumed — see
    the module docstring for the four files this exists to survive.

    Returns a dict the upload preview, the persisted state and the priming all read
    from the same shape:

    - `columns`: the names, in file order, with the reader's own spelling
    - `rows`: one dict per row, every column present, missing cells as `""`
    - `has_header`: what we did; `header_guess`: what we would have done
    - `delimiter`, `encoding`: what actually read the file
    - `blanks`: per column, how many rows have nothing in it
    - `warnings`: `{code, text}` for everything we survived rather than refused

    Rows are dicts and not tuples on purpose: every consumer wants a cell by column
    name, and at a thousand rows over a handful of columns the extra keys are not a
    cost worth a class.
    """
    text, encoding = _decode(data)
    text = _lines(text)
    if not text.strip():
        raise DesignError(
            "This file is empty. Save your list from the spreadsheet again and "
            "check that there is something in it.",
            code="series.emptyFile",
        )

    delimiter = _delimiter_of(text)
    table = _split(text, delimiter)
    if not table:
        raise DesignError(
            "This file is empty. Save your list from the spreadsheet again and "
            "check that there is something in it.",
            code="series.emptyFile",
        )

    warnings: list = []
    guess = _looks_like_a_header(table[0], table[1:])
    header = guess if has_header is None else bool(has_header)
    body = table[1:] if header else table

    if not body:
        raise DesignError(
            "This file has column names but no rows under them.",
            # Its own code, and not `series.noRows`, which the attach half raises for a
            # list that arrives empty. One code carries one translated sentence, and
            # these two ask for different things: fill the file in, or pick another one.
            code="series.headerOnly",
        )
    if len(body) > MAX_ROWS:
        raise DesignError(
            f"This list has {len(body)} rows and this app carries at most "
            f"{MAX_ROWS}.",
            code="series.tooManyRows",
            values={"rows": len(body), "max": MAX_ROWS},
        )

    # The widest row decides how many columns there are, so a stray extra cell does not
    # get dropped without a word. The engine invents a name per extra cell as it goes;
    # doing it up front means the column list is complete before the first row is read.
    width = max([len(table[0])] + [len(row) for row in body])
    heading = list(table[0]) if header else []
    heading += [""] * (width - len(heading))
    columns = _name_columns(heading, header, warnings)

    rows = []
    ragged = 0
    for cells in body:
        if len(cells) != width:
            ragged += 1
        row = {}
        for index, column in enumerate(columns):
            cell = cells[index] if index < len(cells) else ""
            row[column] = str(cell).replace("\ufeff", "").strip()
        rows.append(row)
    if ragged:
        warnings.append(
            {
                "code": "series.raggedRows",
                "text": (
                    f"{ragged} of the {len(rows)} rows do not have {width} values; "
                    "the ones that were missing are read as blank."
                ),
                "values": {"rows": ragged, "columns": width},
            }
        )

    _require_no_braces(rows, columns)

    return {
        "columns": columns,
        "rows": rows,
        "has_header": header,
        "header_guess": guess,
        "delimiter": delimiter,
        "encoding": encoding,
        "blanks": blank_counts(columns, rows),
        "warnings": warnings,
    }


#: Which end of a numbered range a refusal is about, as a token the interface can
#: translate. The English word cannot travel in `values`: a Dutch sentence with
#: "first number" wedged into it reads worse than the English sentence it replaced,
#: and it would be the only English word in a translated refusal.
RANGE_ENDS = ("first", "last", "step", "padding")


def _whole_number(value, what: str) -> int:
    """
    One end of a numbered range, or a sentence saying which end was not a number.

    `int()` on its own is too willing: `int(1.5)` is 1, so a form that sent 1.5 would
    silently start at 1 and the reader would never learn that their number was thrown
    away. A float that is a whole number is accepted, because JSON has no integers and
    the route hands us 250.0.
    """
    NAMES = {
        "first": "first number",
        "last": "last number",
        "step": "step",
        # The word the field carries on screen ("Digits"), not the word the parameter
        # carries in the code: a refusal that names something the reader cannot see is
        # a refusal they cannot act on.
        "padding": "number of digits",
    }
    try:
        if isinstance(value, bool):
            raise ValueError(value)
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(value)
        number = int(value)
    except (TypeError, ValueError) as e:
        raise DesignError(
            f"Numbered rows run from one whole number to another, and the {NAMES[what]} "
            "is not a whole number.",
            code=f"series.notAWholeNumber.{what}",
            values={"which": what},
        ) from e
    return number


def rows_from_numbers(
    first, last, step=1, padding=0, column: str = "number"
) -> dict:
    """
    A list of rows built from a counted range, under one column name.

    "Numbered parts 001 to 250" is a real workshop job, and answering it with "go and
    make a spreadsheet first" would be a step that exists only for the software's
    convenience. So the rows can also come from four numbers — but they are still
    rows: the same column, the same list, the same attaching afterwards, and no
    counter anywhere near the engine. The engine's own counter type
    (`TYPE_COUNTER`, `core/wordlist.py:39`) is deliberately not used: it increments
    on every read, so re-rendering the bed to show you what is next would itself move
    it on.

    `padding` is how wide the number is written: 3 gives `001`, and 0 writes it plain.
    """
    start = _whole_number(first, "first")
    end = _whole_number(last, "last")
    stride = _whole_number(step, "step")
    width = _whole_number(padding, "padding")
    name = require_column_name(column or "number")
    if not name:
        raise DesignError(
            "A numbered list needs a column name, because that is what goes between "
            "the curly brackets in the text.",
            # Its own code: `series.badColumnName` is the one for a name that *has* a
            # curly bracket in it, and one code carries one translated sentence. Two
            # sentences under one code means one of the two surfaces says the wrong
            # thing the moment the catalogue answers it.
            code="series.needsColumnName",
        )

    if stride == 0:
        raise DesignError(
            "A step of nothing never reaches the last number. Count in ones, or in "
            "whatever step the parts really go up by.",
            code="series.numberStepZero",
        )
    if width < 0 or width > MAX_PADDING:
        raise DesignError(
            f"A number written {width} digits wide is not a part number. Use 0 for "
            f"no padding, or up to {MAX_PADDING}.",
            code="series.badPadding",
            values={"padding": width, "max": MAX_PADDING},
        )

    count = (end - start) // stride + 1 if (end - start) * stride >= 0 else 0
    if count < 1:
        raise DesignError(
            f"Counting from {start} to {end} in steps of {stride} makes no rows at "
            "all. Turn the step around, or swap the two ends.",
            code="series.emptyRange",
            values={"first": start, "last": end, "step": stride},
        )
    if count > MAX_ROWS:
        raise DesignError(
            f"This list has {count} rows and this app carries at most {MAX_ROWS}.",
            code="series.tooManyRows",
            values={"rows": count, "max": MAX_ROWS},
        )

    rows = [{name: f"{start + i * stride:0{width}d}"} for i in range(count)]
    return {
        "columns": [name],
        "rows": rows,
        # There was no file, so there is no header question, no delimiter and no
        # encoding. None rather than a plausible-looking default, because the window
        # shows these and a made-up comma would be a small lie.
        "has_header": None,
        "header_guess": None,
        "delimiter": None,
        "encoding": None,
        "blanks": blank_counts([name], rows),
        "warnings": [],
    }


def blank_rows(columns, rows) -> list[int]:
    """
    The rows that have nothing in one of the columns the design reads.

    Blank in *any* of them, not all: a plate whose name is missing is a plate with a
    frame and nothing in it, whichever of its two texts came up empty. Measured before
    this feature existed: a blank cell produced no warning anywhere and the plate came
    out of the machine with the frame burned and the name missing.

    `columns` are the row keys, already spelled the way the rows are — see
    `find_column` for why that mapping happens once, in the caller.
    """
    empty = []
    for index, row in enumerate(rows or ()):
        if any(not str(row.get(column, "")).strip() for column in columns or ()):
            empty.append(index)
    return empty


def burn_rows(rows, columns, step: int = 1, skip_blank: bool = True) -> list[list[int]]:
    """
    How the rows fall into burns: one list of row numbers per burn, in order.

    With `step` 1 that is one burn per row and a blank row can simply be left out. With
    a sheetful — twelve tags reading `{name}` … `{name#+11}` — it cannot, and that is
    not a choice we get to make: the engine resolves `{name#+1}` as the row *next to*
    the pointer (`core/wordlist.py:520-535`), so the twelve places on the sheet are
    always twelve consecutive rows. A blank row in the middle of a sheetful therefore
    leaves one tag empty rather than shifting the other eleven along, and skipping is
    honoured only where it can be honoured.

    The last burn is short when the rows run out. That is the burn the overrun mutator
    exists for: the places it has no rows for would otherwise engrave the placeholder
    itself, nine characters of `{name#+2}` in real geometry.
    """
    total = len(rows or ())
    if step <= 1:
        skip = set(blank_rows(columns, rows)) if skip_blank else set()
        return [[index] for index in range(total) if index not in skip]
    return [
        list(range(start, min(start + step, total)))
        for start in range(0, total, step)
    ]


def rows_in(ranges) -> set[int]:
    """
    The rows a run's `done` list covers.

    A run records what is burned as **inclusive** row ranges — `[[0, 18]]` is the first
    nineteen rows and one row on its own is `[7, 7]`. Inclusive rather than half-open
    because `openkerf-series.json` is a file somebody opens on the shop floor when a
    plate has come out wrong, and `[7, 8]` meaning "row 7" is a trap in that moment.

    Rows and not burn numbers, because the step is re-derived from the design on every
    read: add a thirteenth tag to a twelve-up sheet and every burn re-partitions, while
    "those rows are done" stays true. A malformed pair is passed over rather than
    raising — this is bookkeeping about work already done, and losing the whole run
    because one entry was hand-edited would be the worse answer.
    """
    rows: set[int] = set()
    for pair in ranges or ():
        try:
            first, last = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        rows.update(range(first, last + 1))
    return rows


def ranges_of(rows) -> list[list[int]]:
    """
    The other way round: rows into the shortest list of inclusive ranges.

    Adjacent rows coalesce, so burning a list from the top writes `[[0, 12]]` and not
    thirteen pairs. That is not only tidiness — the burn list in the window is drawn
    from this, and a file that grows a line per plate would be a file that grows for
    the length of the afternoon.
    """
    out: list[list[int]] = []
    for row in sorted({int(row) for row in rows or ()}):
        if out and row == out[-1][1] + 1:
            out[-1][1] = row
        else:
            out.append([row, row])
    return out


# --------------------------------------------------------------------------- #
# The one thing here that touches a plan
# --------------------------------------------------------------------------- #


class OverrunMutator:
    """
    The last plate: leave out the places the list has no rows left for, and the jig.

    A plan mutator on the existing contract — `callable(steps) -> steps`, applied right
    after `plan copy` (`commands.py:_apply_mutators`), the same seam print and cut and a
    tile run hang on. It works on the *copies*, so the drawing is never touched; the
    removal sticks because `core/cutplan.py:256` reifies each operation out of the
    mutated step.

    ## Why the overrun half exists

    A twelve-up sheet against a list of fifty leaves ten places on the last sheet with
    no row to fill them, and the engine does not leave those blank — it engraves the
    placeholder. `Wordlist.fetch_value` answers None past the end of the list
    (`core/wordlist.py:266-269`) and `translate` only substitutes when the value is not
    None (`core/wordlist.py:597`), so the nine characters `{name#+2}` stay in the text
    and are rendered as a path like any other. Measured on five names with the pointer
    on row 3 and three texts at offsets 0, 1 and 2: the plan held `Daan` at 175
    segments, `Eva` at 85, and a third shape of **326 segments** whose text was
    `{name#+2}` — real geometry in real cutcode, on somebody's ply.

    The decision is the engine's own substitution and not arithmetic of ours: the same
    `wordlist_translate(..., increment=False)` call the cut plan makes at
    `core/cutplan.py:325`. If a placeholder survives that call, the engine had nothing
    to put there and will engrave the braces. Re-deriving "would this read past the
    end" ourselves would be a second opinion about the very thing this feature exists
    to keep single, and it would have to reproduce the absolute-index and reserved-name
    forms as well. A value that happens to *contain* a placeholder cannot fool it:
    braces in cells are refused when the list is attached, and `_clear_register` wipes
    the engine's own strays before every burn.

    ## Why "burn only once" is the same pass

    A jig frame is cut once and then holds fifty pieces in turn. That is a capability
    the engine's own placements cannot express at all — `core/cutplan.py:225-338`
    replays the whole plan per placement — and here it is one condition on a walk we
    are already doing. `first` means "nothing has been burned in this run yet", not
    "this is burn number one of the list": an operator who starts a run at row 12 makes
    their first plate there, and the jig goes on the bed at that moment. Outside a
    series there is no mutator at all, so `mkonce` never withholds anything from an
    ordinary Burn.

    An operation left with nothing in it is dropped rather than passed on empty. Every
    operation in the plan is an RD layer, and this controller has answered "file
    invalid" at thirty-three of them.
    """

    def __init__(self, elements, first: bool = True):
        self.elements = elements
        self.first = first

    def __call__(self, steps):
        kept = []
        for step in steps:
            children = getattr(step, "children", None)
            if not children:
                # Not an operation with work in it. A `util console` step — what a Z
                # move per pass is made of — has an empty child list and has to travel
                # on untouched, and so does anything else that is not a layer.
                kept.append(step)
                continue
            if self._strip(step):
                kept.append(step)
        return kept

    def _strip(self, operation) -> bool:
        """Take out what this burn has nothing to put there. Returns what is left."""
        for child in list(operation.children):
            if self._leave_out(child):
                child.remove_node()
        return bool(operation.children)

    def _leave_out(self, node) -> bool:
        if not self.first and getattr(node, "mkonce", None):
            return True
        template = getattr(node, "mktext", None)
        if not template:
            return False
        rendered = self.elements.wordlist_translate(
            template, elemnode=node, increment=False
        )
        # One surviving placeholder is enough: a text reading "{name} of {name#+1}" with
        # only one row left would otherwise burn "Eva of {name#+1}", and half a sentence
        # engraved is worse than a place left empty.
        return any(holder.text in rendered for holder in placeholders(template))


# --------------------------------------------------------------------------- #
# The state object: the list on disk, the register in the engine
# --------------------------------------------------------------------------- #


class Series:
    """
    The list that is attached, which row the bed shows, and the gate a burn passes.

    Three pieces of state, deliberately in three places:

    - **the list, on disk beside the library** (`openkerf-series.json`). Fifty
      keyrings is an afternoon's work and a page refresh must not cost it — the same
      argument `tilerun.py` makes for a tile run, in the same file shape.
    - **the pointer, in that same file.** Which row the next burn takes.
    - **the rows, in the engine's wordlist, write-only.** We write that register
      before every burn and every row change and never read a value back out of it —
      only, in `_pointer_moved`, where its pointer stands. That is not tidiness:
      `spool` advances the wordlist index behind our back
      (`core/spoolers.py:57`), and the engine's `Wordlist` loads a shared,
      profile-blind `wordlist.json` at startup (`core/elements/elements.py:770-771`),
      so anything found in there is somebody else's. Writing and never reading makes
      both harmless. `save_data` is never called anywhere in this module, so that
      shared file is never written either.

    **The pointer sits beside the list and not inside the `run` block**, which is where
    the plan drew it. The bed shows the row that is about to burn *always*, run or no
    run — that is the one promise this feature has to keep — so the row belongs to the
    list. A run then holds only what is true while it lasts: which rows are done, what
    the design looked like when it began, and when that was.

    The list, the pointer and the register need a kernel and a path and nothing else.
    The run verbs at the bottom of the class need three collaborators and they are
    optional for that reason: a series that is only being looked at — a row shown on the
    bed, a sum in the pre-flight — must be constructible without a spooler.
    """

    def __init__(self, kernel, path, runner=None, tiles=None, sheets=None):
        self.kernel = kernel
        self.path = Path(path)
        # `runner` spools a burn, `sheets` says which sheet a run belongs to, and
        # `tiles` is the neighbour that also decides what the next burn is — see
        # `_refuse_other_run`. None of the three is reached above `start()`.
        self.runner = runner
        self.tiles = tiles
        self.sheets = sheets

    @property
    def elements(self):
        return self.kernel.elements

    @property
    def wordlist(self):
        return self.elements.mywordlist

    # ------------------------------------------------------------------ storage

    def _read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, data: dict | None) -> None:
        if data is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------- the design

    def _text_nodes(self) -> list:
        """
        Every node on the bed that carries a template.

        A sheet is a document of its own (see the head of `sheets.py`): switching sheets
        empties the element tree and loads the other one. So "every text on the active
        sheet" is every text in the tree, and there is nothing to filter.
        """
        return [node for node in self.elements.elems() if getattr(node, "mktext", None)]

    def templates(self) -> list[str]:
        """The templates on the bed, in tree order."""
        return [str(node.mktext) for node in self._text_nodes()]

    def _used_columns(self, data) -> list[str]:
        """
        The columns the design reads, spelled the way the rows are keyed.

        `columns_used` lower-cases, because that is what the engine looks up; the rows
        keep the reader's own spelling. `find_column` is where those two meet, and a
        caller that indexes a row with a placeholder's own name is the one trap this
        split leaves — so the mapping happens here, once, and everything downstream
        takes column names it can use directly.
        """
        columns = (data or {}).get("columns") or []
        found = []
        for name in columns_used(self.templates()):
            column = find_column(columns, name)
            if column is not None and column not in found:
                found.append(column)
        return found

    def columns(self):
        """
        The columns the attached list has, or None when there is no list.

        `None` and `[]` are two different answers here and the difference carries a
        refusal: `[]` cannot happen (a list with no columns is refused at `attach`), and
        `None` means "there is nothing to compare a placeholder against". That is exactly
        the tri-state `require_known_columns` needs, so the same value that says "no list"
        also says "no opinion" and there is one code path instead of two.

        Read off the file on every call rather than cached. A text is placed by hand, at
        human speed; the read is one small JSON file and the alternative is a cache that
        can be wrong about what the list holds — which is the one thing this gate is for.
        """
        data = self._read()
        return None if data is None else [str(name) for name in data.get("columns") or []]

    def row(self, data=None) -> int:
        """
        The row the bed shows, which is the row the next burn takes.

        Clamped rather than trusted: a shorter list can be attached while a pointer past
        its end is on disk, and `set_index` clamps silently anyway
        (`core/wordlist.py:408-446`). Clamping here means the number on the screen and
        the number in the engine are the same number.
        """
        data = self._read() if data is None else data
        if data is None:
            return 0
        rows = len(data.get("rows") or [])
        try:
            row = int(data.get("current_row") or 0)
        except (TypeError, ValueError):  # pragma: no cover - a hand-edited state file
            row = 0
        return max(0, min(row, rows - 1)) if rows else 0

    # ------------------------------------------------------- the engine register

    def _clear_register(self) -> None:
        """
        Everything out of the engine's wordlist except the names it keeps itself.

        `empty_csv()` alone is not enough, and that is the whole reason this exists: it
        removes `TYPE_CSV` entries only (`core/wordlist.py:801`), so a *static* called
        `name`, left in the shared `wordlist.json` by somebody's wxPython session, would
        still answer `{name}` — quietly, with one value, on every plate. Measured with
        such a static in place: a text reading `{name}` came out as `STRAY`.

        In memory only, and only names the engine does not reserve: `version`, `date`,
        `time` and the `op_*` family stay, because the engine answers those itself and
        deleting them would break `{op_speed}` for everybody.
        """
        wordlist = self.wordlist
        wordlist.empty_csv()
        for key in [
            key for key in list(wordlist.content) if key not in wordlist.prohibited
        ]:
            wordlist.delete(key)

    def _drifted(self, node) -> bool:
        """
        Whether this text on the bed says something else than it would burn.

        The comparison is `wordlist_translate(..., increment=False)`, which is the
        identical call the cut plan makes at `core/cutplan.py:325`. Anything it says has
        not moved cannot come out of the machine differently either, and that is the
        whole value of using the engine's own substitution rather than one of ours.
        """
        fresh = self.elements.wordlist_translate(
            node.mktext, elemnode=node, increment=False
        )
        return fresh != getattr(node, "_translated_text", None)

    def _render(self, nodes) -> None:
        """
        Re-render the texts whose value has moved, and only those.

        The updater is the engine's own — `path_updater/linetext`, registered outside
        the GUI at `extra/hershey.py:837`, so this is not a second `make_raster` case —
        and it is the same call `Drawing.update_text` makes. A render costs a font pass:
        measured 3.5 ms for twelve texts against 0.06 ms for twelve comparisons, so the
        comparison decides which ones get one.
        """
        moved = [node for node in nodes if self._drifted(node)]
        if not moved:
            return
        for node in moved:
            for updater in self.kernel.lookup_all("path_updater/.*"):
                updater(self.kernel.root, node)
        # The canvas has to be told, because the geometry under it changed. Deliberately
        # not through `Drawing._refresh`, which also marks the document as changed:
        # showing the next name is not an edit to the design, and a series of fifty
        # would otherwise offer to save fifty times.
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")

    def _prime(self, data=None) -> None:
        """
        Write the rows the design reads into the engine and point at the current row.

        Cleared first, then every column of the list, then the index, then the bed.
        Rebuilt in full on every row change rather than kept up to date: at the
        thousand-row cap a full push measured 0.19 ms for one column and 0.92 ms for
        five, and a remembered "we pushed already" flag would be one more thing that can
        be wrong about a register we deliberately never read.

        **Every column and not only the referenced ones**, which is where this parts
        company with the cost cut the plan asked for — and it has to. The design's
        references are what decide *which* columns are read, but they cannot decide what
        is in the register at the moment a text first asks for one: a text created with
        `{name}` in it renders while it is being created (`extra/hershey.py:504`), so a
        register holding only what was already referenced answers nothing. Measured
        through the routes: attach a list, then place a text reading `{name}`, and the
        node came out with `_translated_text` empty and bounds `(nan, nan, nan, nan)` —
        so the engine classified it into no layer at all and the spooler said there was
        nothing ready to burn. The cut saved 0.7 ms and cost the shape.

        With nothing attached this clears the register and lets the bed catch up, which
        is what detaching a list has to do: a text still reading `Anna` after the list
        is gone is the one thing this feature may not do.
        """
        data = self._read() if data is None else data
        self._clear_register()
        if data is None:
            self._render(self._text_nodes())
            return
        rows = data.get("rows") or []
        row = self.row(data)
        wordlist = self.wordlist
        for column in data.get("columns") or []:
            for index, entry in enumerate(rows):
                wordlist.set_value(
                    column,
                    str(entry.get(column, "")),
                    # The first call creates the entry as an array; every one after it
                    # appends. An explicit index would overwrite in place
                    # (`core/wordlist.py:378-406`) and the list would stay one long.
                    idx=None if index == 0 else -1,
                    wtype=1,
                )
            wordlist.set_index(column, row)
        self._render(self._text_nodes())

    def _pointer_moved(self, data) -> bool:
        """
        Whether the engine's own pointer still stands on the row we put it on.

        The half of the invariant that comparing the texts cannot see: when something
        moves the index *and* re-renders, the bed and the engine agree with each other
        and both disagree with us. Measured: with the pointer pushed to row 3 and the
        node re-rendered, every text matched its own translation and the next burn would
        have taken `Daan` while the state file said row 0.

        `IDX_POSITION` is index 1 of an entry and the values start at index 2
        (`core/wordlist.py:42-44`), which is the only arithmetic in here.

        This reads the register that is otherwise write-only, and that is not a
        contradiction: reading where the pointer stands is not trusting it for a value,
        it is the tripwire that says the register has to be written again.
        """
        row = self.row(data)
        for column in self._used_columns(data):
            entry = self.wordlist.content.get(str(column).strip().lower())
            if entry is None or entry[1] - 2 != row:
                return True
        return False

    def _ensure_primed(self) -> None:
        """
        The one enforced invariant: what is on the bed is what will burn.

        Everything else that primes — attaching a list, moving the row, a burn — is an
        optimisation. Correctness lives here, because one invariant with eight
        enforcement points is how the ninth gets missed, and the ninth is a plate with
        the wrong name on it.

        Two ways to drift, and both have happened. The engine's own: `spool` runs a
        `wordlist advance` inside itself (`core/spoolers.py:57`), so the row moves on
        after a burn without anybody asking — that one shows up as a text on the bed
        saying something else than it would burn. And ours: a state file that outlives
        the list it points into, so the row we mean is not the row the register stands
        on — that one shows up only in the pointer.

        **Only texts that read the list are asked whether they have drifted.** A text
        holding nothing but the engine's own names drifts every second by design:
        `{time}` renders off the clock (`core/wordlist.py:558-563`), so a fresh
        translation never equals the last one and this method would re-prime on every
        read. `state()` is read from the status payload several times a minute, and
        `_render` goes through the engine's own updater, which ends in `node.altered()`
        (`extra/hershey.py:387`) — and that pushes an undo state. Measured with a
        `{time}` beside a `{name}` and a list attached: one "Element altered" on the undo
        stack per beat, so a twenty-deep stack held nothing of the operator's own work
        after forty seconds of an app nobody was touching. A clock-only text cannot say
        anything about which row is next, which is the only thing this invariant is
        about, so it has no business deciding that the register must be written again.
        It is still re-rendered when a prime does happen — that is `_render`'s own
        comparison, and there it is the right one.
        """
        data = self._read()
        if data is None:
            return
        reading = [
            node for node in self._text_nodes() if columns_used([node.mktext])
        ]
        if self._pointer_moved(data) or any(self._drifted(node) for node in reading):
            self._prime(data)

    # ----------------------------------------------------------------- the sum

    def _fingerprint(self) -> str:
        """
        A cheap summary of the design, for "has this changed since the run began".

        sha1 and emphatically not `hash()`: Python salts the hash of strings per
        process, so a `hash()` written to disk comes back different after a restart and
        every resumed series would be stale — the same argument as `tilerun.py:556`,
        where the two processes gave 1444352915328149249 and 5992177919278113137 for one
        tuple.

        A text that reads from the list is summarised by its *template* and where it
        stands, never by its bounds. Its bounds change with every row by design:
        measured, `Anna` spans 51572–98931 engine units and `Bram` 53114–99586, so a
        fingerprint over those would call a series stale one burn after it began. The
        matrix does not move with the row — measured, `e` stayed 51602.4 over five rows
        and became 77403.5 when the same text was dragged 10 mm — so a nudge is still
        seen, which is the whole point.
        """
        import hashlib

        parts = []
        for node in self.elements.elems():
            template = getattr(node, "mktext", None)
            if template:
                matrix = getattr(node, "matrix", None)
                where = f"{matrix.e:.1f},{matrix.f:.1f}" if matrix is not None else "?"
                parts.append(
                    f"{node.type}:{template}:{getattr(node, 'mkfontsize', '')}:"
                    f"{getattr(node, 'mkalign', '')}:{where}"
                )
                continue
            bounds = getattr(node, "bounds", None)
            parts.append(
                f"{node.type}:"
                + ("-".join(f"{v:.1f}" for v in bounds) if bounds else "?")
            )
        return hashlib.sha1("|".join(parts).encode()).hexdigest()

    def _stale(self, data, step: int) -> tuple[bool, str, str]:
        """
        Whether the design moved under a running series, and which way it moved.

        Two things can change and the punishment differs, so the answer says which. The
        geometry changing means what is already burned belongs to another drawing. The
        number of places on a sheet changing means the rows re-partition: burn four
        sheets of a twelve-up design, add a thirteenth tag, and the rows a burn eats are
        no longer the rows it ate. Both are stale; only one of them is somebody's
        afternoon.

        Returns `(stale, reason, sentence)`, with the reason as the bare word the
        interface switches on and the sentence as what a client without a catalogue
        shows.
        """
        run = (data or {}).get("run") or {}
        if not run:
            return False, "", ""
        if run.get("step") is not None and int(run["step"]) != step:
            return (
                True,
                "places",
                "The design has changed since this series began: a sheet now holds a "
                "different number of places, so the rows fall into different burns. "
                "What is already burned belongs to the old design; carrying on would "
                "give you half old and half new.",
            )
        if run.get("fingerprint") != self._fingerprint():
            return (
                True,
                "geometry",
                "The design has changed since this series began: the shapes have moved "
                "or been altered. What is already burned belongs to the old design; "
                "carrying on would give you half old and half new.",
            )
        return False, "", ""

    def _renders(self, template: str) -> str:
        """
        What this placeholder puts on the material for the row the bed shows.

        Through the engine, never through a substitution of ours: the window, the
        pre-flight and the burn have to agree, and the only way to be sure of that is to
        ask the thing that does the burning. `increment=False` because reading must not
        move the pointer — that is the engine's counter trap, and it is why
        `{counter}` is not part of this feature at all.
        """
        return self.elements.wordlist_translate(
            template, elemnode=None, increment=False
        )

    def check(self) -> dict:
        """
        The one server sum: what the design asks of the list, and what it would get.

        Read by the Series window, folded into the pre-flight and read by the run, so
        that the preview, the button label and the refusals provably come out of one
        place. A sum and not a gate: it computes and never raises. `vet()` is what turns
        the same numbers into a refusal.
        """
        data = self._read()
        columns = (data or {}).get("columns") or []
        rows = (data or {}).get("rows") or []
        templates = self.templates()
        step = step_of(templates)
        used = self._used_columns(data)
        # Through `_burns`, so the numbered burn list the window draws from this and the
        # burn the run verbs act on are one computation and not two that agree today.
        burns = self._burns(data)
        stale, reason, message = self._stale(data, step)
        row = self.row(data)

        # One entry per distinct placeholder, not per shape: the window lists what the
        # design reads, and `{name}` on eight tags is one thing read eight times.
        uses = []
        seen = set()
        for template in templates:
            for holder in placeholders(template):
                if holder.text in seen:
                    continue
                seen.add(holder.text)
                uses.append(
                    {
                        "placeholder": holder.text,
                        "column": holder.column,
                        "offset": holder.offset,
                        "absolute": holder.absolute,
                        "reserved": holder.reserved,
                        "known": holder.reserved
                        or find_column(columns, holder.column) is not None,
                        "renders": self._renders(holder.text),
                    }
                )

        return {
            "attached": data is not None,
            "row_count": len(rows),
            "current_row": row,
            # Which burn the pointer stands in, counted the way a person counts: the
            # first burn is 1. None when the row falls in no burn at all, which is what
            # a blank row being skipped looks like.
            "current_burn": next(
                (number for number, group in enumerate(burns, 1) if row in group), None
            ),
            "burns": len(burns),
            "step": step,
            "used_columns": used,
            "uses": uses,
            "unknown": unknown_columns(templates, columns),
            "blanks": blank_counts(columns, rows),
            "blank_rows": len(blank_rows(used, rows)),
            "ghosts": self._ghosts(columns),
            "stale": stale,
            "stale_reason": reason,
            "message": message,
        }

    def _ghosts(self, columns) -> list[dict]:
        """
        The shapes that ask for a column the list has not got.

        Each one is a shape that burns nothing and cannot be clicked either. Measured on
        a text reading `{nope}` against a list without that column: it renders as the
        empty string (`core/wordlist.py:568`), `bounds` comes back
        `(nan, nan, nan, nan)`, the element count in `DesignReader.snapshot()` went from
        one to nought — and it still counts as burnable. So it is invisible on the
        canvas and present in the job, which is the worst of both and the reason this
        list exists rather than a marker drawn on the bed.
        """
        found = []
        for node in self._text_nodes():
            missing = []
            for holder in placeholders(node.mktext):
                if holder.reserved or not holder.column:
                    continue
                if find_column(columns, holder.column) is None:
                    if holder.column not in missing:
                        missing.append(holder.column)
            if missing:
                found.append(
                    {
                        "id": getattr(node, "id", None),
                        "label": getattr(node, "label", None),
                        "text": str(node.mktext),
                        "missing": missing,
                    }
                )
        return found

    def rows(self) -> list[dict]:
        """
        The rows themselves, for the window that shows them.

        Kept out of `state()` on purpose: `state()` rides in the status payload several
        times a minute, and a thousand rows in there is a thousand rows down every
        WebSocket for a number that fits in a word.
        """
        return (self._read() or {}).get("rows") or []

    def state(self) -> dict:
        """
        Everything a surface needs about the series, and the bed put right first.

        The one place in this module where a read has a side effect, and that is
        deliberate: `_ensure_primed()` is what keeps the promise that the bed shows the
        row that is about to burn. Anybody looking at the series is looking at the bed
        as well, and a canvas showing yesterday's name until somebody presses something
        is the bug this feature exists to end. It costs one comparison per text —
        measured 0.06 ms for twelve — and re-renders nothing that has not moved.
        """
        self._ensure_primed()
        data = self._read()
        return {
            **self.check(),
            "source": (data or {}).get("source"),
            "columns": (data or {}).get("columns") or [],
            "skip_blank": bool((data or {}).get("skip_blank", True)),
            "run": (data or {}).get("run"),
        }

    # --------------------------------------------------------------- the gates

    def vet(self) -> None:
        """
        The gate every burn passes, series or not.

        Two refusals, both measured to be worth having. A text that asks for a column
        the list has not got renders as nothing and disappears from the snapshot while
        still counting as burnable, so today it is a plate with a frame and no name and
        not a word said. And a column the design reads that is blank in every row is
        that same plate, once per row.

        Then the invariant: what is on the bed is what burns.
        """
        data = self._read()
        ghosts = self._ghosts((data or {}).get("columns") or [])
        if ghosts:
            if data is None:
                raise DesignError(
                    "No list is attached, so a text with a placeholder in it cannot "
                    "become anything. Attach a list in the Series window, or take the "
                    "placeholder out of the text.",
                    code="series.noList",
                )
            # The first missing column carries the sentence; the window lists them all.
            # A refusal that names one thing to fix is acted on, and one that names
            # seven is read as "something is wrong somewhere".
            #
            # The same sentence the text field says, from the same function: a placeholder
            # no column fills is one fact, and hearing it worded one way while typing and
            # another way at the machine would read as two different problems.
            raise no_such_column(ghosts[0]["missing"][0])
        if data is not None:
            for column in self._used_columns(data):
                require_values(column, data.get("rows") or [])
        self._ensure_primed()

    def vet_plain_job(self) -> None:
        """
        The ordinary Burn button, which may be pressed while a series is going.

        The run comes first: with a series going, that button burns one plate and counts
        nothing, and the operator finds out by counting plates against the burn list.
        Then the same gate every other burn passes.
        """
        data = self._read()
        if (data or {}).get("run"):
            raise DesignError(
                "A series is going, so this button would burn one plate and count "
                # Not "the Series panel": there is no such panel. The button that counts
                # the plates is "Burn this one", in the series block at the head of the
                # Job panel, and a refusal that sends the reader to a room that does not
                # exist is worse than one that says nothing.
                "nothing. Press Burn this one instead: that is the button that counts "
                "the plates.",
                code="series.runGoing",
            )
        self.vet()

    def vet_tile_run(self) -> None:
        """
        The mirror of `_refuse_other_run`: a tile run may not begin under a series.

        `_refuse_other_run` is one half of a promise, and a promise with one half is a
        trap. It stops a series while a tile run is going, but a tile run is begun from
        its own panel and knew nothing about a series, so the two could be started in
        either order and only one order was refused. Both decide what the next burn is —
        a tile run clips the design to a piece of a board, a series changes what a text
        says — and both keep a count of plates that the other one silently spoils.

        Its own code and its own sentence rather than `series.otherRunGoing`, for the
        reason `_refuse_while_running` gives: the two refusals are about the same fact
        but they ask for different things, and one code can carry only one translated
        sentence. This one says stop the series; that one says stop the tile run.
        """
        if (self._read() or {}).get("run"):
            raise DesignError(
                "A series is going, and a series and a tile run both decide what the "
                "next burn is. Finish or stop the series first.",
                code="series.runGoingTiles",
            )

    def vet_tile_burn(self) -> None:
        """
        A tile burn is a burn, and it was the one burn that passed no gate at all.

        Three ways into the spooler exist — the ordinary Burn button, a series burn and a
        tile burn (`tilerun.py`, the only other caller of `runner.start_job`) — and this
        gate is what makes them three doors into one room. Without it a tile of a board
        carrying a text that asks the list for a column it has not got came out with the
        frame burned and the name missing, and nothing was said: exactly the failure
        `vet()` was written for, reached by the one path that did not call it.

        The mirror refusal first and the gate second, the same order as
        `vet_plain_job`: which button to press is worth knowing before being told what is
        wrong with the design.
        """
        self.vet_tile_run()
        self.vet()

    def vet_new_design(self) -> None:
        """
        A running series may not have the design swapped out from under it.

        Opening a project replaces every shape on the bed. A run is a count of plates
        made from *this* drawing — `done` says which rows are burned, `fingerprint` says
        what they were burned from — so the moment the drawing goes, the count is about
        nothing, and `start` writes an empty `done`, so there is no way back to it.

        Refused rather than quietly ended, and asked *before* anything is replaced. The
        operator has plates on the bench and a number in their head; a sentence they can
        act on costs them one click, while ending the run for them costs them the count.
        Same fact as `_refuse_while_running` and its own code all the same, for the reason
        that one gives: one code carries one translated sentence, and this one says stop
        the series before you open a project.
        """
        if (self._read() or {}).get("run"):
            raise DesignError(
                "A series is going. Stop it before you replace the drawing, because the "
                "plates you have already burned belong to the design that would go.",
                code="series.runGoingProject",
            )

    # ------------------------------------------------------------ the list itself

    def _refuse_while_running(self, data) -> None:
        """
        A list may not be swapped or taken away under a run.

        Its own code and its own sentence, next to `series.runGoing`: the two refusals
        are about the same fact but they ask for different things — one says press the
        other button, this one says stop the run first — and one code can only carry one
        translated sentence.
        """
        if (data or {}).get("run"):
            raise DesignError(
                "A series is going. Stop it before you change the list, otherwise what "
                "has been burned no longer matches what is left.",
                code="series.listLocked",
            )

    def attach(self, read: dict, source=None, skip_blank=None) -> dict:
        """
        Take a list of rows as the one this design burns from.

        `read` is what `read_rows()` or `rows_from_numbers()` returned — the same shape
        from both doors, which is what makes "numbers" a way of filling in rows rather
        than a second kind of series. `source` is what the caller knows about where they
        came from; the four facts we measured ourselves (header, delimiter, encoding and
        the guess) are written over whatever it says about those.

        The column names are checked again here even though `read_rows` already did.
        This is a door, and a door validates: a hand-built dict from a route, a test or
        a future importer must not be able to plant a column called `date` that would
        silently never resolve.
        """
        data = self._read()
        self._refuse_while_running(data)
        columns = [str(name) for name in (read or {}).get("columns") or []]
        rows = list((read or {}).get("rows") or [])
        if not columns or not rows:
            raise DesignError(
                "This list has no rows in it, so there is nothing to burn.",
                code="series.noRows",
            )
        if len(rows) > MAX_ROWS:
            raise DesignError(
                f"This list has {len(rows)} rows and this app carries at most "
                f"{MAX_ROWS}.",
                code="series.tooManyRows",
                values={"rows": len(rows), "max": MAX_ROWS},
            )
        for name in columns:
            require_column_name(name)

        block = dict(source or {})
        block.setdefault(
            # A file answers the header question and a counted range does not, so a
            # `has_header` of None is the one place where the two doors are already
            # distinguishable. Said by the caller where possible, inferred here where
            # not, rather than defaulting to "file" and being wrong in the window.
            "kind",
            "file" if read.get("has_header") is not None else "numbers",
        )
        block.update(
            {
                "has_header": read.get("has_header"),
                "header_guess": read.get("header_guess"),
                "delimiter": read.get("delimiter"),
                "encoding": read.get("encoding"),
                "imported_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }
        )
        self._write(
            {
                "source": block,
                "columns": columns,
                "rows": rows,
                # Whether a row with nothing in it is passed over. Only possible where
                # one burn is one row — see `burn_rows` for why a sheetful cannot skip.
                "skip_blank": True if skip_blank is None else bool(skip_blank),
                "current_row": 0,
                "warnings": list((read or {}).get("warnings") or []),
            }
        )
        self._prime()
        return self.state()

    def detach(self) -> dict:
        """
        Take the list away, and stop the bed showing names that are not attached.

        Clearing the register leaves every text reading its own template again, which on
        the canvas means it renders as nothing and drops out of the snapshot — the ghost
        state, listed by `check()` with a way to fix or delete each one. That is the
        honest picture: a text that reads from a list has nothing to say once the list
        is gone, and leaving `Anna` on the bed would be a lie the next burn tells.
        """
        data = self._read()
        self._refuse_while_running(data)
        self._write(None)
        self._prime()
        return self.state()

    # ------------------------------------------------------- the project bundle

    #: What the list is called inside a `.openkerf` project file, beside `design.svg`,
    #: `library.json` and `sheets.json`. In the bundle and not folded into `library.json`
    #: for the reason that file exists at all: the library is what this workshop knows
    #: about its materials, and a list of names is what this project burns.
    BUNDLE_NAME = "series.json"

    def export_into(self, bundle) -> None:
        """
        Put the list into a project file — the list, and emphatically not the run.

        A project mailed to somebody has to carry the names, or it carries a design that
        cannot be burned: measured on a bundle written before this method existed, the
        text came back with `mktext` `{name}` and the geometry of the row the sender
        happened to be on (`Anna`), nothing attached, the Series window calling it a
        ghost, and `/api/job/start` answering 409 `series.noList`. The receiver has the
        drawing and no way to use it until they find the spreadsheet.

        What travels is the rows, the columns, where they came from and whether blank
        rows are skipped. What does not is the `run` and the pointer — those are half an
        afternoon at somebody else's machine, and resuming a stranger's count of plates
        is the one thing this file must never do. So the receiver gets the list standing
        on its first row, which is `attach`'s own starting state.

        Written even when nothing is attached, as `null`, and that is not noise: a bundle
        with no `series.json` at all was made before this feature and says nothing about
        lists, while `null` says "this project has no list". `import_from` needs to tell
        those two apart, because they call for opposite answers.
        """
        data = self._read()
        payload = None
        if data is not None:
            payload = {
                "source": data.get("source"),
                "columns": data.get("columns") or [],
                "rows": data.get("rows") or [],
                "skip_blank": bool(data.get("skip_blank", True)),
            }
        bundle.writestr(
            self.BUNDLE_NAME, json.dumps(payload, indent=1, ensure_ascii=False)
        )

    def import_from(self, bundle) -> None:
        """
        Take the list out of a project file, or leave what is attached alone.

        Three answers to three states of the bundle, and each of the three is a decision:

        - **no `series.json`** — a project from before this feature. It says nothing about
          lists, so it does not get to throw away the one that is attached. Silence is
          not an instruction.
        - **`null`** — this project has no list. Then the attached one goes, because the
          alternative is the worst outcome this feature can produce: yesterday's names
          satisfying today's `{name}`, fifty plates deep, with nothing on the screen
          disagreeing.
        - **a list** — attach it, through the same `attach()` every other door uses, so a
          hand-edited bundle meets the same refusals as a spreadsheet (a column called
          `date`, a brace in a cell, more rows than we carry).

        Called *after* the design is loaded, deliberately. Loading an SVG does not
        re-render a `mktext` node — measured, the node came back with `_translated_text`
        `None` and the geometry that was in the file — so the list has to arrive while the
        new texts are in the tree. `attach` then primes the register and re-renders them
        to the first row, which is the promise the whole feature stands on: the bed shows
        the row that is about to burn.

        One consequence of that order, stated because it is a choice: a refusal from here
        — a hand-edited bundle with a column called `date` in it, or more rows than we
        carry — arrives when the drawing is already open. That is the right way round.
        The project is the thing somebody wanted; the sentence names what is wrong with
        the list, and the list can be imported again from the spreadsheet. The one
        refusal that has to come *before* anything is replaced is a run going, and that
        one is `vet_new_design`.
        """
        if self.BUNDLE_NAME not in set(bundle.namelist()):
            return
        try:
            payload = json.loads(bundle.read(self.BUNDLE_NAME))
        except ValueError as e:
            # The design is already in by the time we get here, so refusing outright
            # would leave a project half opened. Saying what is wrong with the list and
            # keeping the drawing is the better half of a bad bargain.
            raise DesignError(
                "The list in this project file cannot be read, so the project has "
                "opened without it. Import the list again from your spreadsheet.",
                code="series.bundleUnreadable",
            ) from e
        if payload is None:
            if self._read() is not None:
                self.detach()
            return
        if not isinstance(payload, dict):  # pragma: no cover - a hand-edited bundle
            raise DesignError(
                "The list in this project file cannot be read, so the project has "
                "opened without it. Import the list again from your spreadsheet.",
                code="series.bundleUnreadable",
            )
        source = dict(payload.get("source") or {})
        self.attach(
            {
                "columns": payload.get("columns") or [],
                "rows": payload.get("rows") or [],
                # The four facts a reader of the window would otherwise lose. They ride
                # in `source` on disk and `attach` writes them from the read, so they
                # have to be handed back in the shape a read has. `imported_at` is not
                # among them: `attach` stamps it now, which is true — the list arrived in
                # *this* workshop when the project was opened.
                "has_header": source.get("has_header"),
                "header_guess": source.get("header_guess"),
                "delimiter": source.get("delimiter"),
                "encoding": source.get("encoding"),
            },
            source=source,
            skip_blank=payload.get("skip_blank"),
        )

    def set_row(self, row) -> dict:
        """
        Point the bed at another row.

        This is the primitive the run verbs are built on: starting at a row, stepping
        to the next burn and redoing one are each "point at this row" plus bookkeeping
        about what is done. It re-primes, so the bed shows the row that is about to
        burn before anybody presses anything — measured over five names, rows 0 to 4
        gave Anna, Bram, Cees, Daan and Eva, with the geometry going 126, 163, 148, 175
        and 85 segments.
        Without the re-render the geometry does not move at all: the node kept `Eva` and
        its 85 segments while the engine's pointer stood on `Anna`.
        """
        data = self._read()
        if data is None:
            raise DesignError(
                "No list is attached, so there is no row to burn. Import a list in the "
                "Series window first.",
                code="series.nothingAttached",
            )
        try:
            number = int(row)
        except (TypeError, ValueError) as e:
            raise DesignError(
                "A row is counted with a whole number, starting at the first row.",
                code="series.badRow",
            ) from e
        rows = len(data.get("rows") or [])
        if number < 0 or number >= rows:
            # The sentence counts from one because that is how the burn list is
            # numbered on the screen; the API counts from nought, like the rows.
            raise DesignError(
                f"This list has {rows} rows, so it cannot start at row {number + 1}.",
                code="series.startPastEnd",
                values={"rows": rows, "row": number + 1},
            )
        data["current_row"] = number
        self._write(data)
        self._prime(data)
        return self.state()

    # ------------------------------------------------------------------- the run

    def _run(self, data) -> dict:
        """The run block, or the refusal that says there is none."""
        run = (data or {}).get("run")
        if not run:
            raise DesignError("There is no series going.", code="series.noRun")
        return dict(run)

    def _burns(self, data) -> list[list[int]]:
        """
        How the rows of this list fall into burns, right now.

        Re-derived on every call and never stored: the step comes from the design and
        the design changes. `check()` computes the same partition for the window, so the
        numbered burn list on the screen and the burn this verb is about are the same
        thing by construction rather than by agreement.
        """
        return burn_rows(
            (data or {}).get("rows") or [],
            self._used_columns(data),
            step_of(self.templates()),
            bool((data or {}).get("skip_blank", True)),
        )

    def _blank_here(self, row: int) -> DesignError:
        """The refusal for a pointer parked on a row that is being skipped."""
        return DesignError(
            f"Row {row + 1} has nothing in it for the columns this design burns, and "
            "blank rows are being skipped, so there is no burn here. Switch off "
            "skipping blank rows, or move to another row.",
            code="series.blankRow",
            values={"row": row + 1},
        )

    def _burn_at(self, data, burns) -> int:
        """
        Which burn the pointer stands in, and a refusal when it stands in none.

        A blank row that is being skipped is not a burn, so a pointer parked on one has
        no plate to make. Along the ordinary route that cannot happen — `start` moves on
        to the first real burn and `advance` only ever lands on one — but a row set by
        hand can do it, and "burn the burn the pointer is in" when it is in none would
        otherwise be an index error over somebody's material.
        """
        row = self.row(data)
        for index, group in enumerate(burns):
            if row in group:
                return index
        raise self._blank_here(row)

    def _burn_from(self, burns, row: int) -> int:
        """
        The first burn that contains this row or comes after it.

        Used when a run begins, so that starting on a blank row that is being skipped
        moves on to the next real burn instead of refusing. That is not a silent jump:
        the answer carries the row it settled on and the bed re-renders to it, so the
        operator reads which plate is next before they press anything.
        """
        for index, group in enumerate(burns):
            if group and group[-1] >= row:
                return index
        raise self._blank_here(row)

    def _refuse_other_run(self) -> None:
        """
        Only one thing at a time may decide what the next burn is.

        A tile run and a series both answer "what goes to the machine when I press
        burn", and they answer it differently: a tile run clips the design to a piece of
        a board, a series changes what a text says. Both going at once is two sets of
        bookkeeping over one plate and neither of them right.

        Checked on `start` *and* on every `burn`, not on `start` alone, because a tile
        run can be begun from its own panel after a series has started — and it is the
        burn that costs the material. The mirror image of this refusal, a tile run
        refusing to start while a series is going, belongs in `tilerun.py`.
        """
        if self.tiles is None:
            return
        try:
            going = self.tiles.state()
        except Exception:  # pragma: no cover - a neighbour must not break a burn
            going = None
        if going:
            raise DesignError(
                "A tile run is going, and a tile run and a series both decide what the "
                "next burn is. Finish or stop one of the two.",
                code="series.otherRunGoing",
            )

    def _sheet_id(self):
        """Which sheet this run belongs to, for the record. Never a reason to fail."""
        if self.sheets is None:
            return None
        try:
            return (self.sheets.active() or {}).get("id")
        except Exception:  # pragma: no cover - a missing sheet is not a run's problem
            return None

    def start(self, row=None) -> dict:
        """
        Begin a run: this design, burned once per row from here on.

        `row` counts from nought and None means "where the bed is already pointing".
        That is not a convenience: the bed shows the row the next burn takes, so Start
        pressed with the twelfth name on the screen has to burn the twelfth name.
        Beginning again at the first row would burn a plate the operator is holding.

        What the run records is only what cannot be worked out again later — which rows
        are done, the step and the fingerprint of the design at this moment, the sheet,
        and when it began. The pointer is deliberately not in there; see the class
        docstring.
        """
        data = self._read()
        if data is None:
            raise DesignError(
                "No list is attached, so there is no row to burn. Import a list in the "
                "Series window first.",
                code="series.nothingAttached",
            )
        if data.get("run"):
            # Deliberately a refusal and not a restart. Starting over would throw away
            # which plates are already burned, and that is an afternoon's counting the
            # operator cannot get back by looking at the bed.
            raise DesignError(
                "A series is already going. Stop it first — starting another one would "
                "throw away which plates have been burned.",
                code="series.alreadyStarted",
            )
        self._refuse_other_run()
        # `vet()` before this, deliberately: a text asking for a column the list has not
        # got makes `_used_columns` empty too, and "none of the text reads the list"
        # would then be said about a text that plainly does. The refusal that names the
        # missing column is the one somebody can act on.
        self.vet()
        if not self._used_columns(data):
            raise DesignError(
                "None of the text on the bed comes from the list, so every burn would "
                "be the same. Put a column into a text first.",
                code="series.nothingVariable",
            )
        burns = self._burns(data)
        if not burns:
            # Every row blank in one of the columns the design reads, with skipping on.
            # `vet()` catches the simpler case where one column is blank all the way
            # down; this is the ragged one, where each row is missing a different value.
            raise DesignError(
                "Every row in this list is missing a value the design needs, so with "
                "blank rows skipped there is nothing to burn. Switch off skipping "
                "blank rows, or fill the list in.",
                code="series.noBurns",
            )
        # `set_row` owns the two refusals about a row — not a whole number, past the end
        # — so the wanted row goes through it first. Only then is it snapped forward to
        # the first burn that really exists, which is a second write and only when the
        # snap moves anything.
        self.set_row(self.row(data) if row is None else row)
        data = self._read()
        first = burns[self._burn_from(burns, self.row(data))][0]
        if first != self.row(data):
            self.set_row(first)
            data = self._read()
        data["run"] = {
            "done": [],
            "step": step_of(self.templates()),
            "fingerprint": self._fingerprint(),
            "sheet_id": self._sheet_id(),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._write(data)
        return self.state()

    def burn(self, confirm: bool = False, mutators=()) -> dict:
        """
        Send the burn the bed is showing to the spooler, and mark those rows done.

        The gates are in the order in which their answers matter, and it is
        `tilerun.py`'s order for the same reason: a run that has gone stale must be read
        as stale first. Somebody told "you have burned this one already — confirm to
        carry on" under a design that has changed since the run began would be
        confirming the wrong thing.

        The rows are marked done here and not in `advance`, because they are burned as
        soon as the plan reaches the spooler. Marking them on the way past would count a
        plate nobody made, every time somebody stepped over a burn.

        `mutators` is what the route has already composed — the zero point and a
        print-and-cut pose, exactly as an ordinary Burn gets them. Ours goes on the end
        here and not in the route, because it is the only place that knows which burn
        this is and whether anything has been burned yet.
        """
        data = self._read()
        run = self._run(data)
        self._refuse_other_run()
        stale, reason, message = self._stale(data, step_of(self.templates()))
        if stale:
            # Two codes for the two reasons, because the two sentences differ and one
            # code can carry only one translated sentence.
            raise DesignError(
                message,
                code=(
                    "series.stalePlaces"
                    if reason == "places"
                    else "series.staleGeometry"
                ),
            )
        burns = self._burns(data)
        index = self._burn_at(data, burns)
        rows = burns[index]
        done = rows_in(run.get("done"))
        if set(rows) <= done and not confirm:
            raise DesignError(
                "This one has already been burned. Burning it again means the laser "
                "goes over work that is already there — only do that when the last "
                "attempt was spoiled. Confirm to carry on.",
                code="series.alreadyBurned",
            )
        # Last, and immediately before the plan is built: this is where the invariant is
        # enforced, so between here and the spooler nothing may run that could move the
        # engine's pointer.
        self.vet()
        if self.runner is None:  # pragma: no cover - the server always wires one
            raise DesignError(
                "This series has no way to reach the machine.",
                code="series.noRunner",
            )
        # `not done` and not `index == 0`: "the first burn of this run" is the plate the
        # operator is making now, and a run may have been started at row 12. That is the
        # moment the jig goes on the bed, so that is the burn a `mkonce` shape belongs
        # to. See `OverrunMutator`.
        overrun = OverrunMutator(self.elements, first=not done)
        self.runner.start_job(
            f"Series {index + 1} of {len(burns)}",
            mutators=[*list(mutators), overrun],
        )
        run["done"] = ranges_of(done | set(rows))
        data["run"] = run
        self._write(data)
        # `state()` re-primes on the way out, and it has something to do: `spool` runs a
        # `wordlist advance` inside itself (`core/spoolers.py:57`), so the engine's
        # pointer has just moved off the row we are still standing on.
        return {**self.state(), "burned": index + 1, "burned_rows": rows}

    def burn_mutators(self) -> list:
        """
        What the next burn will leave out — for the burn, the clock and the picture.

        Four surfaces have to agree about this and they used to have three answers: the
        series burn applied the mutator, the plain Burn button applied nothing (so on the
        last plate it really engraved the nine characters `{name#+2}` — measured 409 cut
        objects against 172), and the pre-flight and the cut-path window described the
        drawing as it stands rather than the plate that is coming. One method, read by
        all four, is the only shape in which they cannot drift.

        `first` is "the first plate of *this run*", which is what a jig marked "burn only
        once" belongs to. With no run going there is no earlier plate, so it is the plate
        being made now.

        Nothing attached means nothing added, and that matters more than it looks: every
        job in the app passes this seam, and a plain design must take exactly the route
        it took before this feature existed.
        """
        data = self._read()
        if data is None:
            return []
        run = (data or {}).get("run") or {}
        first = not rows_in(run.get("done")) if run else True
        return [OverrunMutator(self.elements, first=first)]

    def plain_mutators(self) -> list:
        """
        The same, for the plain Burn button. Kept as its own name because the route reads
        better for it, and because a plain job with a run going is refused elsewhere
        (`vet_plain_job`) rather than mutated here.
        """
        return self.burn_mutators()

    def advance(self) -> dict:
        """
        Move on to the next burn that still has to happen.

        The next one is the first burn *after* this one that is not done, and when there
        is none, the first burn anywhere that is not done. That second half gives the
        operator their repair story for free: free rows 12 to 14, burn them, and the
        pointer goes on to 19 rather than back to 15. It also sweeps up a burn that was
        stepped over rather than burned, instead of calling the series finished with a
        hole in it.

        Nothing is marked done here — `burn` does that, because that is where the plate
        is made.
        """
        data = self._read()
        run = self._run(data)
        burns = self._burns(data)
        done = rows_in(run.get("done"))
        row = self.row(data)
        here = next((i for i, group in enumerate(burns) if row in group), -1)
        left = [i for i, group in enumerate(burns) if not set(group) <= done]
        ahead = [i for i in left if i > here]
        target = ahead[0] if ahead else (left[0] if left else None)
        if target is None:
            # The run is over and the list stays. The pointer stays too, on the last
            # thing that was burned, because that is what the operator is looking at.
            data.pop("run", None)
            self._write(data)
            return {**self.state(), "finished": True}
        data["current_row"] = burns[target][0]
        self._write(data)
        self._prime(data)
        return {**self.state(), "finished": False}

    def redo(self, row) -> dict:
        """
        Burn one of these again: point at its burn and mark that burn undone.

        Takes a row and not a burn number on purpose. A burn number moves when the
        design does — a thirteenth tag on a twelve-up sheet re-partitions every burn —
        while the row is the thing the operator can read off the plate in their hand.
        """
        data = self._read()
        run = self._run(data)
        try:
            number = int(row)
        except (TypeError, ValueError) as e:
            raise DesignError(
                "A row is counted with a whole number, starting at the first row.",
                code="series.badRow",
            ) from e
        burns = self._burns(data)
        index = next((i for i, group in enumerate(burns) if number in group), None)
        if index is None:
            raise DesignError(
                f"There is no burn for row {number + 1} in this series.",
                code="series.noSuchBurn",
                values={"row": number + 1},
            )
        run["done"] = ranges_of(rows_in(run.get("done")) - set(burns[index]))
        data["run"] = run
        data["current_row"] = burns[index][0]
        self._write(data)
        self._prime(data)
        return self.state()

    def stop(self) -> dict:
        """
        End the run and keep the list.

        The list stays and so does the pointer: a series stopped halfway is a plate half
        finished, and the operator is going to look at the bed to see where they were.
        Only this run's bookkeeping goes, which is why stopping and starting again is
        not a way to resume — `start` writes an empty `done`.

        Idempotent, deliberately. A Stop button that answers "there is no series going"
        is a dead end for somebody who pressed it twice, or who pressed it after the
        last burn had already finished the run.
        """
        data = self._read()
        if data is None or not data.get("run"):
            return self.state()
        data.pop("run", None)
        self._write(data)
        return self.state()
