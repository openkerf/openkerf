"""
A series: reading a list, finding placeholders, and pointing the bed at a row.

The first half of this file is pure — bytes in, dicts out, no kernel. The second half,
from "the state object" onwards, is `Series` itself: the list on disk, the engine's
wordlist as a write-only register, and the sum every surface reads. Those tests take
the same kernel fixture the rest of `api/tests` uses and they are about one thing, the
promise this whole feature stands on: what is on the bed is what the next burn puts on
the material.

The pure half is tested to the depth it is because that is where a mistake costs a
plate of material: a list read one row out, or a column silently renamed, and fifty
keyrings carry the wrong name.

Several tests carry a measurement in their docstring. Those numbers came from running
the engine's own loader (`meerk40t/core/wordlist.py`) over the very same bytes, with
`meerk40t/.venv/bin/python`, on 22 August 2026 against the 0.9.9040 working copy.
They are in the docstrings because each one is the reason the test exists: without
them, "we read the CSV ourselves" is taste rather than evidence.
"""

import math

import pytest

from openkerf_api.commands import CommandRunner
from openkerf_api.design import DesignReader
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.series import (
    MAX_PADDING,
    MAX_ROWS,
    OverrunMutator,
    Placeholder,
    Series,
    blank_counts,
    blank_rows,
    burn_rows,
    columns_used,
    find_column,
    placeholders,
    read_rows,
    require_column_name,
    require_known_columns,
    require_values,
    reserved_column,
    rows_from_numbers,
    rows_in,
    shift_placeholders,
    step_of,
    unknown_columns,
)


def refusal(exception_info) -> str:
    """The code a refusal carries, because that is what the interface reads."""
    return exception_info.value.code


# --------------------------------------------------------------------------- #
# read_rows: the four files the engine's own loader mishandles
# --------------------------------------------------------------------------- #


def test_a_list_saved_by_windows_excel_is_read():
    """
    A Dutch Excel export: cp1252 bytes, semicolons, an accent.

    Measured on these exact bytes: the engine's `load_csv_file` returns `(0, 0, [])`
    and the single warning "Could not read CSV file …", because
    `EncodingDetectFile` declares `ENCODING_CP1252` at `extra/encode_detect.py:17`
    and never returns it from any branch. Anything that calls the engine's loader
    fails this test, which is exactly what it is for.
    """
    data = "naam;aantal\r\nRené;2\r\nJosé;3\r\nAnna;1\r\n".encode("cp1252")

    result = read_rows(data)

    assert result["columns"] == ["naam", "aantal"]
    assert len(result["rows"]) == 3
    assert result["rows"][0] == {"naam": "René", "aantal": "2"}
    assert result["delimiter"] == ";"
    assert result["encoding"] == "cp1252"


def test_a_one_column_list_of_names_keeps_its_header():
    """
    `b"name\\r\\nAnna\\r\\nBram\\r\\n"`: one column, CRLF, no delimiter anywhere.

    Measured, and worse than the plan claimed: `csv.Sniffer().sniff()` picks the
    delimiter `"a"` for these bytes, so the engine's loader returns three rows over
    two columns called `column_1`/`column_2` — "Anna" split down the middle, with
    the header read as data and no warning at all. On a very similar file
    (`b"serial\\r\\n001\\r\\n002\\r\\n"`) the same sniffer picks `"\\r"` and the loader
    raises `ValueError: bad delimiter value None` at the caller.

    Both are impossible here: the delimiter is counted over four fixed characters and
    a file no candidate splits is a one-column list.
    """
    result = read_rows(b"name\r\nAnna\r\nBram\r\n")

    assert result["columns"] == ["name"]
    assert [row["name"] for row in result["rows"]] == ["Anna", "Bram"]
    # Nothing split it, so the delimiter is reported honestly and not sniffed.
    assert result["delimiter"] == ","


def test_a_serial_number_list_does_not_crash_the_reader():
    """
    The file whose sniffed delimiter is a carriage return.

    Measured: `csv.Sniffer().sniff()` returns `'\\r'` for these bytes and the engine's
    loader dies with `ValueError: bad delimiter value None` — an uncaught exception
    out of a route, so a 500 rather than a refusal. Here it is three rows of serials.
    """
    result = read_rows(b"serial\r\n001\r\n002\r\n003\r\n")

    assert result["columns"] == ["serial"]
    assert [row["serial"] for row in result["rows"]] == ["001", "002", "003"]


def test_an_inch_mark_does_not_kill_the_import():
    """
    A cell reading `5" pipe` keeps its quote and the file keeps its rows.

    Measured: `core/wordlist.py:831` counts double quotes over the whole file and
    returns `(0, 0, [])` with "unmatched quotes detected" on an odd count — so one
    size written in inches throws the whole list away.
    """
    result = read_rows(b'part,size\npipe,5" pipe\nrod,3\n')

    assert result["rows"][0] == {"part": "pipe", "size": '5" pipe'}
    assert len(result["rows"]) == 2


def test_a_quoted_comma_stays_inside_its_cell():
    """
    `"Jansen, A."` is one name, not two cells.

    This is why the delimiter vote parses with `csv.reader` rather than counting
    characters: a count over the raw bytes sees two commas on that line and would
    split the name in half, and half a name is burned into the material before anybody
    notices.
    """
    result = read_rows(b'name,city\n"Jansen, A.",Delft\nBram,Gouda\n')

    assert result["delimiter"] == ","
    assert result["rows"][0] == {"name": "Jansen, A.", "city": "Delft"}


def test_a_semicolon_file_with_a_comma_inside_a_cell_still_splits_on_semicolons():
    """
    Excel on a Dutch machine: semicolons between cells, a comma inside one.

    The vote has to prefer the wider shape, because reading this file with commas
    gives one perfectly consistent column — the same wrong answer the engine's
    sniffer gives, and a confident one.
    """
    result = read_rows("naam;maat\r\nRené;3,5 mm\r\nAnna;4,0 mm\r\n".encode("cp1252"))

    assert result["delimiter"] == ";"
    assert result["rows"][0] == {"naam": "René", "maat": "3,5 mm"}


def test_a_byte_order_mark_is_not_part_of_the_first_column_name():
    """
    "CSV UTF-8" from Excel writes a BOM in front of the first column name.

    Without stripping it the column is called `\\ufeffname`, which no reader can type
    between curly brackets and which the window would show as an invisible character
    in front of their own word.
    """
    result = read_rows("﻿name,city\nAnna,Delft\n".encode("utf-8"))

    assert result["columns"] == ["name", "city"]
    assert result["encoding"] == "utf-8-sig"


def test_excel_unicode_text_with_a_byte_order_mark_is_read():
    """
    Excel's "Unicode text (*.txt)" is utf-16 with a mark and tabs between cells.

    Worth its own test because the encoding chain has to try the mark before utf-8:
    read as cp1252 these bytes are full of NULs, and a NUL is how this module tells
    "not text at all" from "text in another encoding".
    """
    data = "name\tcity\r\nRené\tDelft\r\n".encode("utf-16")

    result = read_rows(data)

    assert result["encoding"] == "utf-16"
    assert result["delimiter"] == "\t"
    assert result["rows"] == [{"name": "René", "city": "Delft"}]


def test_a_spreadsheet_instead_of_an_export_is_refused_in_words():
    """
    Somebody uploads the .xlsx itself. That has to be a sentence, not a table of junk.

    cp1252 decodes almost any byte, so without the NUL check this file would come back
    as columns named after fragments of a zip header — a list you could attach and
    burn. Catches any future rearrangement that drops that check.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"PK\x03\x04\x14\x00\x00\x00\x08\x00garbage\x00\x00binary")

    assert refusal(e) == "series.unreadable"


# --------------------------------------------------------------------------- #
# read_rows: the header is asked, not sniffed
# --------------------------------------------------------------------------- #


def test_the_first_row_can_be_declared_data():
    """
    The same bytes as the header test, with `has_header=False`.

    Pins that the header is a choice and not a sniff. Measured: the engine's
    `csv.Sniffer().has_header()` answered False for `name,city` over two names, True
    for `code,size` over two codes, and raised an exception on `serial` over three
    numbers — three kinds of answer to three files of one shape.
    """
    result = read_rows(b"name\r\nAnna\r\nBram\r\n", has_header=False)

    assert result["columns"] == ["column_1"]
    assert [row["column_1"] for row in result["rows"]] == ["name", "Anna", "Bram"]
    assert result["has_header"] is False


def test_the_guess_is_reported_even_when_it_is_overruled():
    """
    `header_guess` says what we would have done; `has_header` says what we did.

    The window pre-fills its two-way choice from the guess, so the guess has to
    survive being overruled. A single field would make the control impossible: after
    one click it would no longer know what to offer.
    """
    data = b"name\r\nAnna\r\nBram\r\n"

    assert read_rows(data)["header_guess"] is True
    assert read_rows(data, has_header=False)["header_guess"] is True
    assert read_rows(data, has_header=True)["header_guess"] is True


def test_a_row_of_numbers_under_a_word_is_a_header():
    """
    `serial` over `001/002/003` is a column name, and the guess has to say so.

    This is the file the engine's sniffer raised an exception on, which is how it ends
    up being treated as data: `except Exception: has_header = False`
    (`core/wordlist.py:853-857`).
    """
    assert read_rows(b"serial\n001\n002\n003\n")["header_guess"] is True


def test_a_first_row_that_repeats_further_down_is_data():
    """
    A value that appears again below is not a column name.

    Cheap and it catches the common export that has no header at all but does have the
    same name twice — a list of stock plates, say. Without it the reader loses a row
    and gains a column called after one of their own values.
    """
    result = read_rows(b"Anna\nBram\nAnna\n")

    assert result["header_guess"] is False
    assert len(result["rows"]) == 3


def test_a_number_in_the_first_row_means_there_is_no_header():
    """
    `1,Anna` cannot be a heading: a column is not called 1.

    The guess must not be clever here. The whole point of the pre-filled choice is
    that it is right on the ordinary files, and a leading number is the ordinary shape
    of a file exported without headings.
    """
    assert read_rows(b"1,Anna\n2,Bram\n")["header_guess"] is False


def test_a_list_of_nothing_but_names_is_guessed_wrong_and_that_is_why_it_is_asked():
    """
    The honest limit, pinned so that nobody 'fixes' it by sniffing harder.

    `Anna/Bram/Cees` with no heading is guessed to have one, because nothing in the
    bytes says otherwise: three text cells in one column look exactly like a heading
    over two names. The window therefore asks, and this test records both answers so
    that the cost of the guess is visible rather than surprising.
    """
    guessed = read_rows(b"Anna\nBram\nCees\n")
    assert guessed["columns"] == ["Anna"]
    assert len(guessed["rows"]) == 2

    told = read_rows(b"Anna\nBram\nCees\n", has_header=False)
    assert told["columns"] == ["column_1"]
    assert len(told["rows"]) == 3


# --------------------------------------------------------------------------- #
# read_rows: names, ragged rows, caps, refusals
# --------------------------------------------------------------------------- #


def test_a_column_with_no_name_gets_a_number():
    """
    A trailing semicolon in Excel leaves a nameless column, and it must be nameable.

    Without an invented name the cells in it could not be referenced at all, and
    silently dropping the column would lose data the reader can see in their own
    spreadsheet. The warning is there so the window can say why it is called
    `column_3`.
    """
    result = read_rows(b"name;city;\nAnna;Delft;x\n")

    assert result["columns"] == ["name", "city", "column_3"]
    assert result["rows"][0]["column_3"] == "x"
    assert [w["code"] for w in result["warnings"]] == ["series.renamedColumns"]


def test_two_columns_with_the_same_name_are_kept_apart():
    """
    `name;name` becomes `name` and `name_2`, case-insensitively.

    Case-insensitively because the engine lower-cases every key
    (`core/wordlist.py:143`), so `Naam` and `naam` are one variable there: two columns
    that quietly become one is the second column's values landing on the first
    column's plates.
    """
    result = read_rows(b"Naam;naam\nAnna;Bakker\n")

    assert result["columns"] == ["Naam", "naam_2"]
    assert result["rows"][0] == {"Naam": "Anna", "naam_2": "Bakker"}


def test_the_readers_own_spelling_of_a_column_name_is_kept():
    """
    A column called `Voornaam` is shown as `Voornaam` and not as `voornaam`.

    A column name is the reader's data, not our label. The engine's lower-casing is
    absorbed by `find_column` instead, so `{voornaam}` still resolves.
    """
    result = read_rows(b"Voornaam,Plaats\nAnna,Delft\n")

    assert result["columns"] == ["Voornaam", "Plaats"]
    assert find_column(result["columns"], "voornaam") == "Voornaam"
    assert find_column(result["columns"], " VOORNAAM ") == "Voornaam"
    assert find_column(result["columns"], "achternaam") is None


def test_a_ragged_row_is_padded_and_said_so():
    """
    A row with a cell missing is read as blank in that column, with a warning.

    Refusing the file would be wrong — the row is real work and the reader can see it
    in their spreadsheet — and padding in silence would be worse, because a blank name
    is a plate with a frame on it and nothing else.
    """
    result = read_rows(b"name,city\nAnna,Delft\nBram\nCees,Gouda,extra\n")

    assert result["columns"] == ["name", "city", "column_3"]
    assert result["rows"][1] == {"name": "Bram", "city": "", "column_3": ""}
    assert result["rows"][2]["column_3"] == "extra"
    codes = [w["code"] for w in result["warnings"]]
    assert "series.raggedRows" in codes


def test_a_file_of_column_names_with_nothing_under_them_is_refused():
    """
    Column names and no rows: nothing to burn, so it must be said and not accepted.

    Measured: the engine's loader returns `(0, 2, ['name', 'city'])` for these bytes —
    two column names for two variables it never creates, so the caller believes it has
    a list and the wordlist has nothing in it.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"name,city\n")

    # Its own code beside `series.noRows`, which is what an empty *list* raises: the
    # two sentences ask for different things, and one code carries one translation.
    assert refusal(e) == "series.headerOnly"


def test_a_file_of_one_line_is_read_as_a_heading_and_can_be_overruled():
    """
    One line of plausible names is a heading with nothing under it, and says so.

    A deliberate choice with a cost, recorded here so the next reader knows it was a
    choice: one row is not a series, and a spreadsheet exported with the heading row
    selected is the ordinary way this file arrives. Somebody who really did mean one
    row still gets it by saying the first row is data, which is the same two-way
    control every other file gets.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"Anna\n")
    assert refusal(e) == "series.headerOnly"

    told = read_rows(b"Anna\n", has_header=False)
    assert told["rows"] == [{"column_1": "Anna"}]


def test_an_empty_file_says_it_is_empty():
    """
    An empty file is not "column names with no rows under them".

    Two different mistakes with two different repairs: one means the export went
    wrong, the other means the reader exported the heading row only.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"\r\n\r\n")

    assert refusal(e) == "series.emptyFile"


def test_a_list_longer_than_the_cap_is_refused_with_both_numbers():
    """
    1001 rows: the refusal names the size of the list and the size of the cap.

    Both numbers, because "too many rows" without them leaves the reader guessing how
    much to cut. They travel in `values` as well, so a translated sentence can carry
    them — a code alone cannot.
    """
    data = b"name\n" + b"".join(b"Anna%d\n" % i for i in range(MAX_ROWS + 1))

    with pytest.raises(DesignError) as e:
        read_rows(data)

    assert refusal(e) == "series.tooManyRows"
    assert e.value.values == {"rows": MAX_ROWS + 1, "max": MAX_ROWS}
    assert "1001" in str(e.value) and "1000" in str(e.value)


def test_exactly_the_cap_is_still_read():
    """The cap is a cap, not a limit one below it."""
    data = b"name\n" + b"".join(b"Anna%d\n" % i for i in range(MAX_ROWS))

    assert len(read_rows(data)["rows"]) == MAX_ROWS


def test_a_column_may_not_take_a_name_the_engine_keeps():
    """
    A header `date;qty` is refused, because a column called `date` would do nothing.

    Measured: `set_value("date", "2026-01-01", idx=-1, wtype=1)` appends to the
    built-in entry and `{date}` still renders the clock's own `08/22/26`, because
    `translate` answers `date` from `strftime` before it ever looks at the content
    (`core/wordlist.py:538-546`). So the column would be accepted, stored, and never
    reach a plate.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"date;qty\n2026-01-01;2\n")

    assert refusal(e) == "series.reservedColumn"

    for name in ("Date", "time", "version", "op_power", "date@%Y"):
        assert reserved_column(name), name
    assert not reserved_column("name")
    assert not reserved_column("operator")  # starts with op, not with op_


def test_a_column_name_with_a_curly_bracket_is_refused():
    """
    `{name}` as a column name would make `{{name}}` in a text, which cannot resolve.

    The engine's pattern is `\\{[^}]+\\}`, so it would match from the second brace and
    yield a stray `}` on the material.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"{name},city\nAnna,Delft\n")

    assert refusal(e) == "series.badColumnName"


def test_a_curly_bracket_in_a_cell_is_refused_by_row_and_column():
    """
    A cell holding `a { b } c` cannot be burned faithfully, so it is refused.

    Measured on the engine: that value survives one substitution pass unchanged and
    renders `a  c` on the second, and a burn has two passes — `extra/hershey.py:355`
    for the bed and `core/cutplan.py:325` for the plan. There is no escape to offer
    instead: `{{name}` matches the engine's own regex from the second brace.

    The refusal names the row and the column, because in a list of two hundred rows
    "somewhere there is a bracket" is not something a person can act on.
    """
    with pytest.raises(DesignError) as e:
        read_rows(b"name,note\nAnna,plain\nBram,a { b } c\n")

    assert refusal(e) == "series.braceInCell"
    assert e.value.values == {"row": 2, "column": "note"}
    assert "Row 2" in str(e.value) and "note" in str(e.value)


def test_blank_cells_are_counted_per_column():
    """
    How many rows are missing a value, per column, because the window shows it.

    Measured before this feature existed: a blank cell produced no warning anywhere
    and a plate with a frame and no name.
    """
    result = read_rows(b"name,city\nAnna,\nBram,Gouda\n,Delft\n")

    assert result["blanks"] == {"name": 1, "city": 1}
    assert blank_counts(["name"], result["rows"]) == {"name": 1}


def test_a_column_that_is_blank_in_every_row_is_refused_when_it_is_used():
    """
    Every row blank in a column the design reads means every burn is a blank plate.

    A gate and not a number on a screen, which is why it is a separate call: the
    parsing accepts the file (the other columns are fine), and the refusal fires when
    a text actually asks for that column.
    """
    rows = read_rows(b"name,city\nAnna,\nBram,\n")["rows"]

    require_values("name", rows)  # has values: no refusal
    with pytest.raises(DesignError) as e:
        require_values("city", rows)

    assert refusal(e) == "series.everyRowBlank"
    assert e.value.values == {"column": "city"}


def test_cells_are_trimmed_because_a_leading_space_moves_the_engraving():
    """
    ` Anna` and `Anna ` are one name. The space is invisible on screen and not on ply.

    A leading space shifts the text along the line; a trailing one changes nothing
    visible but does change the width the pre-flight reports. The engine trims too
    (`core/wordlist.py:999`), so trimming here keeps the bed and the burn agreeing.
    """
    result = read_rows(b"name , city\n Anna , Delft \n")

    assert result["columns"] == ["name", "city"]
    assert result["rows"][0] == {"name": "Anna", "city": "Delft"}


def test_a_blank_line_in_the_middle_is_not_a_row():
    """
    An empty line is not a plate. A row of empty cells (`;;`) still is.

    The difference matters: the first is how every text editor ends a file, the second
    is a row somebody left blank in their spreadsheet, and only the second should show
    up in the burn list where it can be seen and dealt with.
    """
    result = read_rows(b"name;city\nAnna;Delft\n\nBram;Gouda\n")
    assert len(result["rows"]) == 2

    with_blank = read_rows(b"name;city\nAnna;Delft\n;\nBram;Gouda\n")
    assert len(with_blank["rows"]) == 3
    assert with_blank["rows"][1] == {"name": "", "city": ""}


def test_text_is_read_by_the_same_rules_as_bytes():
    """
    A caller that already has a string gets the same reading, not a second path.

    Two readers of one format is how the preview and the burn come to disagree, which
    is the whole complaint this feature answers.
    """
    assert read_rows("name;city\nAnna;Delft\n") == read_rows(
        b"name;city\nAnna;Delft\n"
    )


# --------------------------------------------------------------------------- #
# placeholders: the engine's own parsing, quirks included
# --------------------------------------------------------------------------- #


def test_a_plain_placeholder_is_the_column_at_offset_nothing():
    """`{name}` is the column `name` at the row the pointer is on."""
    assert placeholders("Hello {name}!") == [
        Placeholder(
            text="{name}", column="name", offset=0, absolute=False, reserved=False
        )
    ]


def test_an_offset_placeholder_reads_further_down_the_list():
    """
    `{name#+2}` is two rows on, which is what makes a twelve-up sheet possible.

    Measured on the engine with the pointer on row 1 of Anna/Bram/Cees/Daan/Eva:
    `{name}` rendered `Bram`, `{name#+1}` rendered `Cees` and `{name#+2}` rendered
    `Daan`.
    """
    found = placeholders("{name} {name#+1} {name#+2}")

    assert [p.offset for p in found] == [0, 1, 2]
    assert [p.absolute for p in found] == [False, False, False]


def test_an_index_without_a_sign_is_a_fixed_row_and_not_an_offset():
    """
    `{name#2}` is always row 2, whatever the burn is on.

    Measured with the pointer on row 1: `{name#2}` rendered `Cees` (the third name)
    while `{name#+2}` rendered `Daan` (two on from Bram). Reading it as an offset
    would make `step_of` over-count and hand every burn two rows it does not use.
    """
    found = placeholders("{name#2}")

    assert found[0].absolute is True
    assert found[0].offset == 2
    assert step_of(["{name#2}"]) == 1


def test_a_space_before_the_sign_turns_an_offset_into_a_fixed_row():
    """
    `{name# +1}` is row 1, not one row on. The engine's quirk, reproduced on purpose.

    Measured with the pointer on row 1 of five names: `{name# +1}` rendered `Bram` —
    row 1 counted from the top — where `{name#+1}` rendered `Cees`. The cause is
    `core/wordlist.py:526-531`: the sign test is `startswith` on the raw index string,
    so a space in front of the `+` makes it an absolute index, while `int(" +1")`
    still parses as 1. A tidier re-implementation would strip first and disagree with
    the burn, which is the one thing this function may never do.
    """
    found = placeholders("{name# +1}")

    assert found[0].absolute is True
    assert found[0].offset == 1


def test_the_column_name_is_lower_cased_and_trimmed_like_the_engine_does():
    """
    `{ Name #+1 }` is the column `name` at offset 1.

    Measured: it rendered `Cees` with the pointer on Bram, so the engine really does
    lower-case, strip, and then split on the hash.
    """
    found = placeholders("{ Name #+1 }")

    assert found[0].column == "name"
    assert found[0].offset == 1
    assert found[0].text == "{ Name #+1 }"  # the run as typed, so it can be found again


def test_a_hash_at_the_start_is_part_of_the_column_name():
    """
    `{#3}` is a column called `#3`, because the engine needs the hash after the first
    character (`pos > 0`, `core/wordlist.py:520`). Reading it as an index would invent
    a row nobody asked for.
    """
    found = placeholders("{#3}")

    assert found[0].column == "#3"
    assert found[0].offset == 0
    assert found[0].absolute is False


def test_an_index_that_is_not_a_number_falls_back_to_the_current_row():
    """
    `{name#abc}` is the current row, exactly as the engine's `except ValueError` does.

    Worth pinning because the tempting alternative — refusing it — would refuse a
    text the engine renders perfectly happily, and a refusal the engine does not
    share is a text you cannot place and cannot explain.
    """
    found = placeholders("{name#abc}")

    assert found[0].offset == 0
    assert found[0].absolute is True  # no sign, so the engine reads it as index 0


def test_backwards_offsets_are_reported_rather_than_hidden():
    """
    `{name#-1}` parses. It is refused where a text is typed, not here.

    Both halves matter: parsing it is what lets the refusal say what it found, and the
    measurement behind that refusal is that the engine leaks its own bookkeeping —
    with the pointer on row 0, `{name#-1}` engraves `2` (the position field) and
    `{name#-2}` engraves `1` (the type field).
    """
    found = placeholders("{name#-1} {name#-2}")

    assert [p.offset for p in found] == [-1, -2]
    assert step_of(["{name#-1}"]) == 1  # a backwards read eats no extra rows


def test_the_engines_own_names_are_marked_and_not_treated_as_columns():
    """
    `{date}` is not a ghost and not a column: the engine answers it from the clock.

    Without the mark, a design with a date in it would be refused for a column that
    could never be in the list, and the priming would push a column nobody reads.
    """
    found = placeholders("{name} {date} {op_power} {date@%Y}")

    assert [p.reserved for p in found] == [False, True, True, True]
    assert columns_used(["{name} {date} {op_power}"]) == ["name"]
    assert unknown_columns(["{name} {date}"], ["name"]) == []


def test_a_text_without_a_placeholder_has_none():
    """A plain label is not a series text, and neither is `{}` — the engine's own
    pattern needs at least one character between the brackets."""
    assert placeholders("Anna") == []
    assert placeholders("{}") == []
    assert placeholders("") == []
    assert placeholders(None) == []


def test_the_columns_a_design_reads_are_listed_once_in_the_order_they_were_met():
    """
    Priming writes these and only these.

    At the thousand-row cap that is the difference between a thousand `set_value`
    calls per list change and one per column that is really used — and the order is
    the reading order so that the window's column table does not shuffle between
    reloads.
    """
    used = columns_used(["{name} {city}", "{name#+1}", "{code}"])

    assert used == ["name", "city", "code"]


def test_a_placeholder_no_column_fills_is_named():
    """
    The ghost list: which columns the design asks for that the list has not got.

    Measured on the engine: an unknown key is replaced with the empty string
    (`core/wordlist.py:569`), the node's bounds come back `(nan, nan, nan, nan)` and it
    drops out of the snapshot while still counting as burnable — so the shape is
    invisible, unclickable, and burns nothing. Naming it is what makes the refusal
    actionable.
    """
    missing = unknown_columns(["{name} {nope}", "{ALSO}"], ["Name"])

    assert missing == ["nope", "also"]


def test_a_placeholder_is_only_refused_by_a_list_that_can_say_so():
    """
    The tri-state at the text field: a list has an opinion, no list has none.

    `None` is not "no columns" and the difference is the whole of the decision. With a
    list attached, the list knows what it has, so `{nope}` is a mistake now. With no
    list — or with no series wired to the `Drawing` at all — nobody can say, and a
    design may be drawn before the spreadsheet arrives.

    Fails on the plausible implementation that treats a missing list as an empty column
    list, which would refuse every placeholder anybody ever types until they have been
    to the Series window first.
    """
    require_known_columns("{nope}", None)
    require_known_columns("Plate {name} of {total}", None)

    with pytest.raises(DesignError) as e:
        require_known_columns("Plate {nope}", ["name"])
    assert refusal(e) == "series.unknownColumn"
    assert e.value.values == {"column": "nope"}

    # A column the list has, spelled the reader's way and asked for another way: the
    # engine lower-cases every key (`core/wordlist.py:143`), so these are one variable
    # and refusing here would refuse a text that burns perfectly well.
    require_known_columns("{NAAM}", ["Naam"])
    # And the engine's own names, which answer themselves and are in no list.
    require_known_columns("{date} {time} {version}", ["name"])


# --------------------------------------------------------------------------- #
# shift_placeholders: what a repeat does to a template
# --------------------------------------------------------------------------- #


def test_a_copy_reads_the_next_row_down():
    """
    The whole of "each copy takes the next name": cell 1 reads one row further down.

    Fails on the implementation the engine leaves you with, which is no implementation
    at all: `core/elements/grid.py:237-241` copies with a plain `copy(node)`, so three
    copies of `{name}` all read `Anna`. Measured, three times `Anna` on three plates.
    """
    assert shift_placeholders("{name}", 1) == "{name#+1}"
    assert shift_placeholders("{name}", 2) == "{name#+2}"


def test_a_head_start_is_kept_and_added_to():
    """
    A text already reading one row ahead keeps its lead.

    Adding to the offset rather than overwriting it is what keeps `step_of` honest: a
    sheet of `{name}` and `{name#+1}` repeated twice reads rows 0..3 and must count as a
    step of four. Overwriting would give offsets 0, 1, 1, 2 and a step of three, and the
    third plate would repeat a name off the second.
    """
    assert shift_placeholders("Part {code#+1}", 2) == "Part {code#+3}"


def test_two_placeholders_in_one_text_do_not_cascade():
    """
    The measured trap, and the reason this is a one-pass rebuild and not `str.replace`.

    Over `"{name} {name#+1}"`: replacing the first run turns it into the second, and the
    second replacement then hits both. Measured on that implementation:
    `{name#+2} {name#+2}` — two places engraving one row, on every plate.
    """
    assert (
        shift_placeholders("{name} {name#+1}", 1) == "{name#+1} {name#+2}"
    )


def test_a_fixed_row_stays_where_it_is():
    """
    `{name#2}` is row two on every copy, so a repeat may not move it.

    An absolute index ignores the pointer altogether (`core/wordlist.py:526-535`), which
    is how somebody puts one heading on a whole sheet. Shifting it would give each copy
    a different heading and nobody would see why.
    """
    assert shift_placeholders("{name#2}", 3) == "{name#2}"


def test_the_engines_own_names_are_not_shifted():
    """
    `{date}` is the same date on all fifty plates; there is no next date to take.
    """
    assert shift_placeholders("{date} {name}", 1) == "{date} {name#+1}"


def test_shifting_by_nothing_changes_nothing():
    """
    Cell nought keeps its own template, so repeating a repeat does not shift twice.

    Also the guard on the original: the first cell in reading order is the shape the
    user drew, and it must come out of a repeat exactly as it went in.
    """
    for template in ("{name}", "{name#+2}", "Part {code} of {code#+1}", "plain"):
        assert shift_placeholders(template, 0) == template


def test_the_column_keeps_the_spelling_it_was_typed_with():
    """
    A template is read by a person: `{Name}` stays `{Name}`.

    The engine lower-cases every key it looks up (`core/wordlist.py:143`), so this
    changes nothing about the burn — and everything about the panel, which quotes the
    template back at whoever typed it.
    """
    assert shift_placeholders("{Naam}", 1) == "{Naam#+1}"
    assert shift_placeholders("{ name #+1 }", 1) == "{name#+2}"


def test_a_text_with_no_placeholder_comes_back_untouched():
    assert shift_placeholders("Serial 0042", 3) == "Serial 0042"


# --------------------------------------------------------------------------- #
# step_of
# --------------------------------------------------------------------------- #


def test_the_step_is_one_more_than_the_biggest_offset():
    """
    `{name}` plus `{name#+3}` means four rows go on one sheet.

    This is the number that makes a twelve-up sheet consume twelve rows per burn, and
    it is re-derived from the design on every read rather than frozen at the start of
    a run: freezing it meant that nudging a rectangle re-partitioned the burns and
    voided the done-marks.
    """
    assert step_of(["{name}", "{name#+3}"]) == 4
    assert step_of(["{name#+11}"]) == 12


def test_a_shape_with_no_placeholder_does_not_change_the_step():
    """A rectangle is not a place on the sheet. Only a text that reads the list is."""
    assert step_of(["{name}", "", None, "Serial no."]) == 1


def test_a_design_that_reads_nothing_still_has_a_step_of_one():
    """
    The minimum is one, so that dividing by it is always safe.

    A step of 0 would make the burn count infinite and the progress line meaningless,
    and this function is read by the panel, the pre-flight and the advance.
    """
    assert step_of([]) == 1
    assert step_of(None) == 1


def test_two_columns_at_different_offsets_take_the_furthest_one():
    """
    A sheet of tags with a name and a code on each: the step is the furthest read.

    Taking the largest over all columns and not per column, because one burn covers
    one sheetful, and a sheetful is as deep as its deepest place.
    """
    assert step_of(["{name} {code}", "{name#+1} {code#+1}", "{name#+2}"]) == 3


# --------------------------------------------------------------------------- #
# rows_from_numbers
# --------------------------------------------------------------------------- #


def test_numbered_parts_are_rows_like_any_other():
    """
    001 to 250 is a list of 250 rows in one column, padded to three digits.

    "Numbered parts" is a real workshop job and answering it with "go and make a
    spreadsheet first" would be a step that exists for the software's convenience. It
    is deliberately not the engine's counter type: that increments on every read, so
    re-rendering the bed to show what is next would itself move it on.
    """
    result = rows_from_numbers(1, 250, padding=3, column="part")

    assert result["columns"] == ["part"]
    assert len(result["rows"]) == 250
    assert result["rows"][0] == {"part": "001"}
    assert result["rows"][-1] == {"part": "250"}
    assert step_of(["{part}"]) == 1


def test_numbers_carry_no_delimiter_and_no_encoding():
    """
    There was no file, so those fields are absent rather than plausible.

    The window shows the delimiter and encoding it read; a made-up comma there would
    be a small lie about where the rows came from.
    """
    result = rows_from_numbers(1, 3)

    assert result["delimiter"] is None
    assert result["encoding"] is None
    assert result["has_header"] is None
    assert result["columns"] == ["number"]


def test_a_step_carries_the_numbers_up_in_the_step_it_asks_for():
    """Every fifth part, and the last number is included when it is reached."""
    assert [r["number"] for r in rows_from_numbers(0, 20, step=5)["rows"]] == [
        "0",
        "5",
        "10",
        "15",
        "20",
    ]
    # A last number the step does not land on stops before it, rather than past it.
    assert [r["number"] for r in rows_from_numbers(0, 22, step=5)["rows"]][-1] == "20"


def test_counting_down_needs_a_negative_step():
    """
    250 down to 1 is a list; 250 down to 1 in steps of +1 is nothing, and says so.

    An empty range has to be a refusal and not an empty list, because an empty list
    attaches, starts, and burns nothing while looking like it worked.
    """
    down = rows_from_numbers(5, 1, step=-1)
    assert [r["number"] for r in down["rows"]] == ["5", "4", "3", "2", "1"]

    with pytest.raises(DesignError) as e:
        rows_from_numbers(250, 1)
    assert refusal(e) == "series.emptyRange"
    assert e.value.values == {"first": 250, "last": 1, "step": 1}


def test_a_step_of_nothing_is_refused():
    """A step of 0 never reaches the last number, so it would count for ever."""
    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 10, step=0)

    assert refusal(e) == "series.numberStepZero"


def test_a_single_number_is_a_list_of_one():
    """
    First and last the same is one row. Odd, but it is what somebody typing a
    correction for one plate means, and refusing it would send them to a CSV.
    """
    assert rows_from_numbers(7, 7, padding=2)["rows"] == [{"number": "07"}]


def test_a_range_over_the_cap_is_refused_by_the_same_sentence_as_a_file():
    """
    Two thousand numbers get the cap refusal a two-thousand-row file gets.

    One cap and one sentence, because "this app carries at most 1000" is a fact about
    the app and not about where the rows came from.
    """
    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 2000)

    assert refusal(e) == "series.tooManyRows"
    assert e.value.values == {"rows": 2000, "max": MAX_ROWS}


def test_a_padding_wider_than_a_part_number_is_refused():
    """
    Twenty digits of padding is a typo, and a typo that would fill every plate.

    Zero is allowed and means "write the number plainly", which is the ordinary case.
    """
    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 3, padding=MAX_PADDING + 1)
    assert refusal(e) == "series.badPadding"
    assert e.value.values == {"padding": MAX_PADDING + 1, "max": MAX_PADDING}

    assert rows_from_numbers(1, 2, padding=0)["rows"][0] == {"number": "1"}


def test_something_that_is_not_a_whole_number_is_refused_by_name():
    """
    The refusal says which of the four numbers was not one, because "not a number" in
    a form of four fields is not something a person can act on.

    Which end it was rides in the *code* and not only in `values`: a translated
    sentence cannot have the English words "first number" wedged into it, and that
    would be the only English left in a Dutch refusal.
    """
    for value, which in ((1.5, "first"), ("x", "first")):
        with pytest.raises(DesignError) as e:
            rows_from_numbers(value, 10)
        assert refusal(e) == f"series.notAWholeNumber.{which}"
        assert e.value.values == {"which": which}

    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 10, step="two")
    assert refusal(e) == "series.notAWholeNumber.step"
    assert e.value.values == {"which": "step"}


def test_a_numbered_column_may_not_be_called_something_the_engine_keeps():
    """
    The same two column-name refusals as a file, through the same function.

    A name refused on import must not be able to arrive by the other door — that is
    the whole reason `require_column_name` is one function and not a check in each
    reader.
    """
    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 3, column="date")
    assert refusal(e) == "series.reservedColumn"

    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 3, column="{n}")
    assert refusal(e) == "series.badColumnName"

    # And a name that is not there at all is its own refusal, because it asks for
    # something else: one code carries one translated sentence.
    with pytest.raises(DesignError) as e:
        rows_from_numbers(1, 3, column="   ")
    assert refusal(e) == "series.needsColumnName"

    assert require_column_name("  part  ") == "part"


# --------------------------------------------------------------------------- #
# burn_rows: how rows fall into burns
# --------------------------------------------------------------------------- #


def test_one_row_is_one_burn():
    """
    The ordinary case, and the one the pre-flight multiplies by: five rows, five burns.

    Fails on any partition that counts the rows of the *last* burn as a whole one, which
    is the off-by-one that makes a series of fifty show the time of forty-nine.
    """
    rows = [{"name": n} for n in ("Anna", "Bram", "Cees")]

    assert burn_rows(rows, ["name"]) == [[0], [1], [2]]


def test_a_blank_row_is_passed_over_unless_it_is_asked_for():
    """
    Four burns out of five rows, because one row has no name in it.

    Measured before this feature: a blank cell produced no warning anywhere and the
    plate came out of the machine with the frame burned and the name missing.
    """
    rows = [{"name": n} for n in ("Anna", "", "Cees", "  ", "Eva")]

    assert burn_rows(rows, ["name"]) == [[0], [2], [4]]
    assert burn_rows(rows, ["name"], skip_blank=False) == [[0], [1], [2], [3], [4]]
    assert blank_rows(["name"], rows) == [1, 3]


def test_a_sheetful_cannot_skip_a_blank_row_and_does_not_pretend_to():
    """
    Three places per sheet over seven rows: 3 + 3 + 1, blanks and all.

    This is the honest half of `skip_blank` and it is not a choice we get to make: the
    engine resolves `{name#+1}` as the row *next to* the pointer
    (`core/wordlist.py:520-535`), so the three places on a sheet are always three
    consecutive rows. Skipping the blank one would shift the other two along and the
    remaining rows would land on the wrong tags. Fails on any implementation that
    filters first and groups afterwards.
    """
    rows = [{"name": n} for n in ("Anna", "", "Cees", "Daan", "Eva", "Finn", "Gerda")]

    assert burn_rows(rows, ["name"], step=3) == [[0, 1, 2], [3, 4, 5], [6]]


# --------------------------------------------------------------------------- #
# The state object: the list, the register, the bed
# --------------------------------------------------------------------------- #

FIVE = ("Anna", "Bram", "Cees", "Daan", "Eva")


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def series(kernel, tmp_path):
    return Series(kernel, tmp_path / "openkerf-series.json")


def a_list(names=FIVE, column="name"):
    """
    A list as it arrives from a real file, through the real reader.

    Through `read_rows` and not hand-built, because that is the seam: a state object
    that only understands dicts of its own making would pass every test here and refuse
    the first spreadsheet.
    """
    text = column + "\n" + "\n".join(names) + "\n"
    return read_rows(text.encode("utf-8"))


def a_text(drawing, template, x=20.0, y=20.0, size=8.0):
    """One vector text on the bed, carrying a template. Returns its id."""
    return drawing.create(
        "text", x_mm=x, y_mm=y, text=template, font_size_mm=size
    )["ids"][0]


def node_of(kernel, element_id):
    for node in kernel.elements.elems():
        if getattr(node, "id", None) == element_id:
            return node
    raise AssertionError(f"There is no element {element_id} in the tree.")


def a_run(series, done=None):
    """
    The `run` block that `start()` will write, until step 6 writes it.

    Kept in the test as one function so that the shape is stated once: `done` as row
    ranges, the step and the fingerprint of the moment it began, and the sheet it
    belongs to. Everything about a run that these tests exercise — stale, the plain-job
    refusal, the locked list — reads exactly these fields.
    """
    data = series._read()
    data["run"] = {
        "done": done if done is not None else [],
        "step": step_of(series.templates()),
        "fingerprint": series._fingerprint(),
        "sheet_id": None,
        "started_at": "2026-08-22T10:00:00+00:00",
    }
    series._write(data)
    return data["run"]


def test_the_bed_shows_the_row_that_is_about_to_burn(series, drawing, kernel):
    """
    The promise the whole feature stands on: the canvas shows the next burn, always.

    Measured over these five names with the pointer walked from 0 to 4: the node's own
    text went Anna, Bram, Cees, Daan, Eva and its geometry went 126, 163, 148, 175 and
    85 segments. Fails on the plausible wrong implementation — set the engine's index
    and stop there — because then the geometry never moves at all: measured, the node
    kept `Eva` and its 85 segments while the engine's pointer stood on `Anna`, and the
    machine would have burned Anna while the screen said Eva.
    """
    element = a_text(drawing, "{name}")
    node = node_of(kernel, element)

    series.attach(a_list())
    assert node._translated_text == "Anna"

    seen = []
    for row in range(5):
        series.set_row(row)
        seen.append((node._translated_text, node.geometry.index))

    assert [name for name, _ in seen] == list(FIVE)
    # Five different names cannot have one geometry. The counts themselves are this
    # machine's font; what matters is that they move with the name.
    assert len({segments for _, segments in seen}) > 1


def test_attaching_a_list_clears_whatever_the_engine_had(series, drawing, kernel):
    """
    A stray static named `name` must not be able to answer `{name}`.

    The engine loads a shared, profile-blind `wordlist.json` at startup
    (`core/elements/elements.py:770-771`), so an entry left there by somebody's wxPython
    session is in our register before we write a thing. Measured with such a static in
    place: a text reading `{name}` came out as `STRAY`. Fails on `empty_csv()` alone,
    which removes `TYPE_CSV` entries only (`core/wordlist.py:801`) and leaves a static
    exactly where it was.
    """
    wordlist = kernel.elements.mywordlist
    wordlist.set_value("name", "STRAY", wtype=0)
    wordlist.set_value("leftover", "gone", wtype=1)
    element = a_text(drawing, "{name}")
    assert node_of(kernel, element)._translated_text == "STRAY"

    series.attach(a_list())

    assert wordlist.content["name"] == [1, 2, *FIVE]
    assert "leftover" not in wordlist.content
    assert node_of(kernel, element)._translated_text == "Anna"


def test_the_bed_is_put_right_when_the_engine_index_moves_behind_our_back(
    series, drawing, kernel
):
    """
    `spool` advances the wordlist index inside itself (`core/spoolers.py:57`).

    So after a burn the engine's pointer stands one row on from ours, and the bed would
    quietly show the row after the one the next burn takes. Reading the series puts it
    back. Fails on any design where priming happens only at attach and at a row change:
    then nothing on the way to the next burn ever notices.
    """
    element = a_text(drawing, "{name}")
    series.attach(a_list())

    kernel.elements.mywordlist.set_index("name", 3)
    for updater in kernel.lookup_all("path_updater/.*"):
        updater(kernel.root, node_of(kernel, element))
    assert node_of(kernel, element)._translated_text == "Daan"

    state = series.state()

    assert state["current_row"] == 0
    assert node_of(kernel, element)._translated_text == "Anna"
    # And the burn agrees, through the identical call the cut plan makes at
    # `core/cutplan.py:325`. That is the assertion that would still hold if the bed and
    # the engine were both wrong together.
    assert (
        kernel.elements.wordlist_translate("{name}", increment=False) == "Anna"
    )


def test_a_clock_in_the_design_does_not_re_render_the_bed_on_every_read(
    series, drawing, kernel
):
    """
    `{time}` drifts by the second, and it must not drag the whole bed along with it.

    `state()` is read from the status payload several times a minute and it re-primes
    when something has drifted. A text holding nothing but the engine's own names drifts
    every second by design — `{time}` is answered off the clock
    (`core/wordlist.py:558-563`) — and the re-render goes through the engine's own
    updater, which ends in `node.altered()` (`extra/hershey.py:387`) and therefore pushes
    an undo state.

    Measured before the guard: one "Element altered" on a twenty-deep undo stack per
    heartbeat, so after forty seconds of an app nobody was touching, the operator's own
    last twenty edits were gone. Fails on the plausible reading of the invariant — ask
    every text whether it has drifted — which is what was written first.
    """
    name = node_of(kernel, a_text(drawing, "{name}"))
    clock = node_of(kernel, a_text(drawing, "{time}", y=40.0))
    series.attach(a_list())
    # The drift a clock makes, put there rather than waited for: what the engine renders
    # `{time}` into is never what it rendered a second ago.
    clock._translated_text = "00:00:00"
    stack = len(kernel.elements.undo._undo_stack)

    series.state()
    series.state()

    assert clock._translated_text == "00:00:00", "the clock text was re-rendered"
    # And the half that must not be lost to the guard: the row is still right.
    assert name._translated_text == "Anna"
    assert len(kernel.elements.undo._undo_stack) == stack


def test_we_never_write_the_engine_wordlist(series, drawing, monkeypatch, kernel):
    """
    Nothing in this module may touch `~/…/MeerK40t/wordlist.json`.

    That file is shared by every profile and every session — the same trap CLAUDE.md
    records for `operations.cfg` — so writing our fifty names into it would put them in
    somebody's wxPython session and leave them there. The register is memory only.
    """
    from pathlib import Path

    wordlist = kernel.elements.mywordlist
    shared = Path(wordlist.default_filename)
    before = (shared.exists(), shared.stat().st_mtime if shared.exists() else None)

    def boom(*args, **kwargs):
        raise AssertionError("save_data was called")

    monkeypatch.setattr(type(wordlist), "save_data", boom)

    a_text(drawing, "{name}")
    series.attach(a_list())
    series.set_row(2)
    series.state()
    series.detach()

    assert (shared.exists(), shared.stat().st_mtime if shared.exists() else None) == before


def test_the_engine_csv_loader_is_never_called(series, drawing, monkeypatch, kernel):
    """
    The rows go in through `set_value`, never through the engine's own loader.

    Fails on the plausible wrong implementation — the console's `wordlist load` — which
    mishandles four of the files people actually have (see the module docstring) and
    then raises `KeyError('values')` after loading, which our runner would answer as a
    500.
    """
    wordlist = kernel.elements.mywordlist

    def boom(*args, **kwargs):
        raise AssertionError("the engine's loader was called")

    monkeypatch.setattr(type(wordlist), "load_csv_file", boom)
    monkeypatch.setattr(type(wordlist), "load_data", boom)

    a_text(drawing, "{name}")
    series.attach(a_list())

    assert series.check()["row_count"] == 5


def test_a_text_asking_for_a_column_the_list_has_not_got_stops_the_burn(
    series, drawing, kernel
):
    """
    The refusal, and the plate it buys.

    The companion assertions are the argument for it: measured on a text reading
    `{nope}` against a list without that column, the engine replaces the key with the
    empty string (`core/wordlist.py:568`), `bounds` comes back `(nan, nan, nan, nan)`
    and the element count in `DesignReader.snapshot()` goes to nought — while the shape
    is still in the tree and still counts as burnable. Invisible on the canvas, present
    in the job.
    """
    element = a_text(drawing, "{nope}")
    series.attach(a_list())

    with pytest.raises(DesignError) as e:
        series.vet()
    assert refusal(e) == "series.unknownColumn"
    assert e.value.values == {"column": "nope"}

    node = node_of(kernel, element)
    assert math.isnan(node.bounds[0])
    assert DesignReader(kernel).snapshot()["elements"] == []
    assert series.check()["ghosts"] == [
        {
            "id": element,
            "label": node.label,
            "text": "{nope}",
            "missing": ["nope"],
        }
    ]


def test_a_burn_with_no_list_at_all_says_that_rather_than_naming_a_column(
    series, drawing
):
    """
    A placeholder and nothing attached is a different sentence from a missing column.

    "There is no column called name in the list" is nonsense when there is no list, and
    a reader who is told that goes looking at their spreadsheet instead of at the Series
    window. A design with no placeholder in it passes, which is the case that matters
    most: every ordinary job in the app goes through this gate.
    """
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=10)
    series.vet()

    a_text(drawing, "{name}")
    with pytest.raises(DesignError) as e:
        series.vet()
    assert refusal(e) == "series.noList"


def test_a_placeholder_no_column_fills_is_refused_at_the_text_field(
    series, drawing, kernel
):
    """
    The list can say a placeholder is wrong, so it says so while the text is typed.

    `vet()` above catches the same thing, but only when somebody presses Burn — and the
    shape has been invisible since the moment it was made. Measured through the routes
    with a list holding only `name`: placing a text reading `{nope}` answered **201**,
    and the node came back with `_translated_text` `''`, bounds `(nan, nan, nan, nan)`
    and **nought** elements in `DesignReader.snapshot()`, so it could not be seen,
    selected or dragged — while the Engrave layer went on reporting one element with
    `burns` true. Editing a working `{name}` into `{nope}` answered **200** and did the
    same to a shape that had been visible a second earlier: it simply disappeared, and
    nothing said a word until `/api/job/start` answered 409 at the machine.

    Both doors are here because a placeholder typed into an existing shape burns exactly
    the same nothing, and the last block is the counter-proof: the same `Drawing` with
    the series binding taken away is the app as it was, and it makes the invisible shape
    the paragraph above describes.
    """
    drawing.series = series
    series.attach(a_list())
    good = a_text(drawing, "{name}")

    with pytest.raises(DesignError) as placing:
        a_text(drawing, "{nope}", y=40.0)
    assert refusal(placing) == "series.unknownColumn"
    assert placing.value.values == {"column": "nope"}
    # Refused means not made: a half-placed shape would be the ghost all over again.
    assert [node.id for node in kernel.elements.elems()] == [good]

    with pytest.raises(DesignError) as editing:
        drawing.update_text(good, text="{nope}")
    assert refusal(editing) == "series.unknownColumn"
    assert node_of(kernel, good).mktext == "{name}"
    assert node_of(kernel, good)._translated_text == "Anna"

    # And what the refusal buys, measured on the same design without it.
    drawing.series = None
    ghost = a_text(drawing, "{nope}", y=40.0)
    node = node_of(kernel, ghost)
    assert node._translated_text == ""
    assert math.isnan(node.bounds[0])
    assert [e["id"] for e in DesignReader(kernel).snapshot()["elements"]] == [good]


def test_a_placeholder_may_be_typed_before_the_list_arrives(series, drawing, kernel):
    """
    The other way round would be a step that exists for the software's convenience.

    Drawing the keyring and putting `{name}` on it comes first; the spreadsheet arrives
    with the order. So a placeholder with **no** list attached is allowed — the refusal
    above needs a list to have an opinion at all — and the state cures itself the moment
    one is attached: the engine's own updater re-renders every text and the shape
    appears. Measured here: `''` and then `Anna`, without anything being re-typed.

    Fails on the plan's original reading of this refusal, which was to say "no list is
    attached" at the text field. That would mean the spreadsheet has to exist before the
    drawing may be finished, and the app's own headline flow is the other order.
    """
    drawing.series = series
    element = a_text(drawing, "{name}")
    assert node_of(kernel, element)._translated_text == ""

    series.attach(a_list())

    assert node_of(kernel, element)._translated_text == "Anna"
    # The engine's own names never needed a list and still do not.
    assert a_text(drawing, "{date}", y=40.0)


def test_a_column_blank_in_every_row_stops_the_burn_whatever_its_spelling(
    series, drawing
):
    """
    Every row blank in a column the design reads is every plate missing its text.

    Spelled `Naam` in the file and `{naam}` in the text on purpose: the engine
    lower-cases every key (`core/wordlist.py:143`) while the rows keep the reader's own
    spelling, so a gate that looks up `row["naam"]` finds nothing, sees no values and
    lets the burn through — or refuses every list. `find_column` is the one place those
    two meet.
    """
    a_text(drawing, "{naam}")
    # Two columns, because a file of nothing but blank lines has no rows at all — the
    # blank is in a column beside one that is filled in, which is how it arrives.
    series.attach(read_rows(b"Naam,qty\n,1\n,2\n,3\n"))

    with pytest.raises(DesignError) as e:
        series.vet()
    assert refusal(e) == "series.everyRowBlank"
    assert e.value.values == {"column": "Naam"}


def test_the_plain_burn_button_is_refused_while_a_series_is_going(series, drawing):
    """
    With a series going, the ordinary Burn button burns one plate and counts nothing.

    The operator finds that out by counting plates against the burn list, which is the
    kind of discovery that costs an afternoon. Without a run going the same call passes,
    because every ordinary job in the app goes through it.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    series.vet_plain_job()

    a_run(series)
    with pytest.raises(DesignError) as e:
        series.vet_plain_job()
    assert refusal(e) == "series.runGoing"


def test_the_list_may_not_be_swapped_or_taken_away_under_a_run(series, drawing):
    """
    Its own code, because it asks for something else than the plain-burn refusal.

    One says "press the other button", this one says "stop the run first", and one code
    can carry only one translated sentence. Fails on the plan's own wording, which gave
    both of them `series.runGoing`.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    a_run(series)

    with pytest.raises(DesignError) as e:
        series.detach()
    assert refusal(e) == "series.listLocked"

    with pytest.raises(DesignError) as e:
        series.attach(a_list(("Finn", "Gerda")))
    assert refusal(e) == "series.listLocked"


def test_a_pointer_past_the_end_of_a_shorter_list_is_pulled_back(series, drawing):
    """
    A state file can outlive the list it points into.

    The engine clamps the index silently (`core/wordlist.py:408-446`), so without
    clamping here the screen would say row 10 while the machine burned row 3 — the two
    numbers disagreeing is precisely what this feature must not do.
    """
    element = a_text(drawing, "{name}")
    series.attach(a_list())
    series.set_row(4)

    series.attach(a_list(("Finn", "Gerda")))
    assert series.state()["current_row"] == 0

    data = series._read()
    data["current_row"] = 9
    series._write(data)

    assert series.state()["current_row"] == 1
    assert node_of(series.kernel, element)._translated_text == "Gerda"


def test_starting_past_the_end_is_refused_with_both_numbers(series, drawing):
    """
    The sentence carries the numbers, so it counts from one like the burn list does.

    The API counts rows from nought, the screen counts burns from one, and a refusal is
    read by a person: "it cannot start at row 10" is the row they typed.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())

    with pytest.raises(DesignError) as e:
        series.set_row(9)
    assert refusal(e) == "series.startPastEnd"
    assert e.value.values == {"rows": 5, "row": 10}

    with pytest.raises(DesignError) as e:
        series.set_row("third")
    assert refusal(e) == "series.badRow"


def test_moving_the_row_does_not_make_a_running_series_stale(series, drawing):
    """
    The trap the fingerprint has to avoid, and the reason it is not the tile run's.

    A text's bounds change with every row by design — measured, `Anna` spans
    51572–98931 engine units and `Bram` 53114–99586 — so a fingerprint over the bounds
    of every element, which is what `tilerun.py:556` does, would call a series stale one
    burn after it began and void the whole afternoon.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    a_run(series)

    for row in range(5):
        series.set_row(row)
        assert series.state()["stale"] is False


def test_a_changed_design_makes_a_running_series_stale_and_says_which_way(
    series, drawing
):
    """
    Geometry moving and the number of places changing are both stale, and differently.

    One means what is already burned belongs to another drawing; the other means the
    rows re-partition, so "those rows are done" still holds but the burns no longer line
    up with it. The message names which, because the repair differs.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    a_run(series)

    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=10)
    state = series.state()
    assert state["stale"] is True
    assert state["stale_reason"] == "geometry"
    assert "shapes have moved" in state["message"]

    # A second place on the sheet, where the run began with one: three rows per burn
    # now. Both things have changed by this point, and the sheet is the one that says
    # what to do about it, so it is the one the message names.
    a_text(drawing, "{name#+2}", x=60.0)
    state = series.state()
    assert state["step"] == 3
    assert state["stale"] is True
    assert state["stale_reason"] == "places"
    assert "different number of places" in state["message"]


def test_done_marks_survive_a_change_in_the_step(series, drawing):
    """
    Why `done` holds row ranges and not burn numbers (K8), in one assertion.

    Twelve names against a design with one place is twelve burns; add a second place and
    it is six, and every burn after the first covers different rows than it did. "Rows 0
    to 2 are burned" is still true through that — those three plates are on the bench —
    while "burns 1, 2 and 3 are done" would silently come to mean rows 0 to 5 and hand
    the operator three unburned plates as finished work.

    Fails on any implementation that stores burn numbers, and also on one that freezes
    the step when the run begins: then the re-partition never happens and this test
    measures nothing. The second half is what shows it did happen — the burn that now
    holds row 3 is not done, even though row 2 beside it is.
    """
    a_text(drawing, "{name}")
    series.attach(a_list(tuple(f"N{index:02d}" for index in range(12))))
    a_run(series, done=[[0, 2]])
    assert series.check()["burns"] == 12

    # A second place on the sheet: one burn now eats two rows.
    a_text(drawing, "{name#+1}", x=70.0)

    state = series.state()
    assert state["step"] == 2
    assert state["burns"] == 6
    assert rows_in(state["run"]["done"]) == {0, 1, 2}
    # The re-partition really moved the boundaries: rows 2 and 3 are one burn now, and
    # that burn is not finished because row 3 has never been on the machine.
    burns = series._burns(series._read())
    assert burns[1] == [2, 3]
    assert not set(burns[1]) <= rows_in(state["run"]["done"])


def test_the_fingerprint_is_sha1_and_not_hash(series, drawing):
    """
    Python salts the hash of strings per process.

    So a `hash()` written to disk comes back different after a restart and every resumed
    series is stale — the case this state file exists for, and one that no test making
    two objects in one process can see. Same argument as `tilerun.py:556`, where two
    processes gave 1444352915328149249 and 5992177919278113137 for one tuple.
    """
    a_text(drawing, "{name}")

    fingerprint = series._fingerprint()

    assert len(fingerprint) == 40
    assert int(fingerprint, 16) >= 0
    assert fingerprint == series._fingerprint()


def test_the_sum_says_what_every_placeholder_renders_now(series, drawing):
    """
    One sum, so the preview, the button label and the refusals cannot disagree.

    `renders` goes through the engine's own substitution, which is the only way to be
    sure the window and the machine agree — and `{name#+1}` reading the *next* row is
    the engine's rule, not ours (`core/wordlist.py:520-535`).
    """
    a_text(drawing, "Tag {name}")
    a_text(drawing, "and {name#+1}", x=60.0)
    series.attach(a_list())

    check = series.check()
    renders = {use["placeholder"]: use["renders"] for use in check["uses"]}

    assert renders == {"{name}": "Anna", "{name#+1}": "Bram"}
    assert check["step"] == 2
    assert check["burns"] == 3
    assert check["current_burn"] == 1
    assert check["used_columns"] == ["name"]
    assert check["unknown"] == []


def test_detaching_a_list_leaves_no_names_on_the_bed(series, drawing, kernel):
    """
    A text still reading `Anna` after the list is gone is a lie the next burn tells.

    So detaching clears the register and lets the bed catch up. The text then reads its
    own template again, which on the canvas means it renders as nothing — the ghost
    state, and `check()` names it with its id so the window can offer to fix or delete
    it.
    """
    element = a_text(drawing, "{name}")
    series.attach(a_list())
    assert node_of(kernel, element)._translated_text == "Anna"

    state = series.detach()

    assert state["attached"] is False
    assert node_of(kernel, element)._translated_text == ""
    assert [ghost["id"] for ghost in state["ghosts"]] == [element]


def test_the_list_survives_a_restart_and_primes_the_engine_again(
    series, drawing, kernel, tmp_path
):
    """
    A second `Series` over the same file finds the bed empty and fills it in.

    After a restart the engine's wordlist is whatever the shared file holds, which is
    not our list — so the first thing anybody reads has to put the bed right. Fails on
    an implementation that primes only when something is attached or a row is set: then
    the bed shows nothing until the operator changes something, and a restart mid-series
    looks like the list is gone.
    """
    element = a_text(drawing, "{name}")
    series.attach(a_list())
    series.set_row(3)

    # What a fresh process looks like: the register holds whatever the shared
    # `wordlist.json` holds, which is not our list, and the sheet's texts were rendered
    # against that when the SVG was loaded. Measured on a real restart: the text came
    # back as nothing at all.
    series._clear_register()
    for updater in kernel.lookup_all("path_updater/.*"):
        updater(kernel.root, node_of(kernel, element))
    assert node_of(kernel, element)._translated_text == ""

    again = Series(kernel, tmp_path / "openkerf-series.json")
    state = again.state()

    assert state["current_row"] == 3
    assert node_of(kernel, element)._translated_text == "Daan"


def test_the_series_state_file_sits_beside_the_library_without_a_rename(
    kernel, tmp_path
):
    """
    `ApiServer._beside` used to insist on a legacy Dutch name to move from.

    Every other state file beside the library has one, because they were all named
    before the interface became English. This one never will, and passing its own name
    twice would have meant "rename this onto itself" — true today, and a trap for
    whoever read it next. Fails on the old two-argument signature.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "library.db")

    assert server._beside("openkerf-series.json") == tmp_path / "openkerf-series.json"


# --------------------------------------------------------------------------- #
# The overrun mutator: the last plate, and the jig that is cut once
# --------------------------------------------------------------------------- #


def burnable(kernel):
    """
    Switch 'burn along' on for every layer that holds something.

    The engrave layer a vector text is classified into arrives with `output` off in this
    kernel, and a plan over a layer that does not burn is an empty plan. Switching it on
    is what the operator does in the Layers panel and it is not what these tests are
    about — but without it they would all measure nothing.
    """
    for operation in kernel.elements.ops():
        if list(operation.children):
            operation.output = True


def plan_texts(steps) -> list:
    """What the plan would actually engrave, in the engine's own words."""
    return [
        getattr(child, "_translated_text", None)
        for step in steps
        for child in getattr(step, "children", None) or []
        if getattr(child, "mktext", None)
    ]


def plan_children(steps) -> list:
    return [
        child for step in steps for child in getattr(step, "children", None) or []
    ]


def a_sheetful(drawing, series, row=3):
    """
    Three places on one sheet reading three rows, with the pointer near the end.

    Five names and a step of three means the second burn covers rows 3 and 4, and the
    third place on that sheet has no row at all. That is the plate this mutator exists
    for.
    """
    for index, template in enumerate(("{name}", "{name#+1}", "{name#+2}")):
        a_text(drawing, template, x=10 + index * 45)
    series.attach(a_list())
    series.set_row(row)


def test_the_last_sheet_leaves_out_the_places_it_has_no_rows_for(
    kernel, drawing, series
):
    """
    The place with no row left is taken out of the plan, not engraved as its own syntax.

    Measured on exactly this design before the mutator existed — five names, the pointer
    on row 3, three texts at offsets 0, 1 and 2 — the plan came out holding `Daan` at
    175 geometry segments, `Eva` at 85, and a third shape of **326 segments** whose text
    was the nine characters `{name#+2}`. `Wordlist.fetch_value` answers None past the end
    of the list (`core/wordlist.py:266-269`) and `translate` substitutes only when the
    value is not None (`core/wordlist.py:597`), so the braces stay in the text and are
    rendered like any other path. This test fails on any implementation that leaves the
    child in and hopes the engine will notice.
    """
    a_sheetful(drawing, series)
    burnable(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan([OverrunMutator(kernel.elements)])

    assert plan_texts(steps) == ["Daan", "Eva"]


def test_without_the_mutator_the_placeholder_itself_becomes_real_geometry(
    kernel, drawing, series
):
    """
    The counter-proof, and the reason the mutator is not a precaution.

    Same design, no mutator: the plan carries `{name#+2}` as a shape with geometry in it,
    which is what a customer's ply came out with. Kept as a test rather than a note in a
    docstring because the day the engine starts leaving those out by itself, the mutator
    is dead code and this is the test that says so.
    """
    a_sheetful(drawing, series)
    burnable(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan()

    assert "{name#+2}" in plan_texts(steps)
    literal = [
        child
        for child in plan_children(steps)
        if getattr(child, "_translated_text", None) == "{name#+2}"
    ]
    # Not merely present: rendered. Nine characters of syntax at burn power.
    assert literal and literal[0].geometry.index > 100


def test_the_shapes_on_the_bed_are_untouched_by_a_mutated_plan(
    kernel, drawing, series
):
    """
    The plan may be mangled; the drawing may not.

    The mutator removes nodes, and if it ever got hold of the real tree instead of the
    plan's reified copies the operator would lose a shape to a burn — silently, and only
    on the last plate of a series.
    """
    a_sheetful(drawing, series)
    burnable(kernel)
    before = [
        (node.type, str(node.mktext)) for node in kernel.elements.elems()
    ]

    CommandRunner(kernel).build_plan([OverrunMutator(kernel.elements)])

    assert [
        (node.type, str(node.mktext)) for node in kernel.elements.elems()
    ] == before


def test_a_layer_left_with_nothing_in_it_does_not_travel_as_a_layer(
    kernel, drawing, series
):
    """
    An empty operation is dropped rather than sent on.

    Every operation in the plan becomes a layer in the RD file, and this controller
    answered "file invalid" at thirty-three of them with the laser standing still
    (CLAUDE.md, the pass-layers row). A layer holding only places this burn has no rows
    for is a layer with nothing to do.
    """
    a_text(drawing, "{name#+2}")
    series.attach(a_list(FIVE[:1]))
    burnable(kernel)

    steps = CommandRunner(kernel).build_plan([OverrunMutator(kernel.elements)])

    # Not "no children left" but no step at all: an operation passed on with an empty
    # child list is still an RD layer in the file.
    assert steps == []


def test_a_step_that_is_not_a_layer_goes_through_untouched():
    """
    A step with no children of its own is not an empty layer and must be passed on.

    The Z step per pass is built out of `util console` steps between the copies of an
    operation (`commands.py:_multi_pass_layers`), and those carry no children at all. An
    implementation that dropped every childless step would take the `z_move` out of the
    plan and the head would burn every pass at the first height — measured nowhere,
    because it must never happen.
    """

    class Step:
        def __init__(self, children=None):
            self.children = children

    class Other:
        """Something in the plan that is not a node at all."""

    console_step, plain = Step([]), Other()

    assert OverrunMutator(None)([console_step, plain]) == [console_step, plain]


def a_jig(drawing, kernel, x=5.0):
    """A frame that is cut once and then holds every piece in turn."""
    element = drawing.create(
        "rect", x_mm=x, y_mm=5.0, width_mm=120.0, height_mm=40.0
    )["ids"][0]
    node_of(kernel, element).mkonce = "1"
    return element


class Spool:
    """
    A runner that builds the plan the mutators produce and never spools it.

    `CommandRunner.build_plan` is the only place where a plan is still inspectable —
    `blob` replaces the operations with one `CutCode` — so this stands in for the
    spooler and keeps what each burn would have sent.
    """

    def __init__(self, kernel):
        self.runner = CommandRunner(kernel)
        self.plans = []
        self.names = []

    def start_job(self, name, mutators=()):
        self.names.append(name)
        self.plans.append(self.runner.build_plan(list(mutators)))


def test_a_shape_marked_burn_once_is_in_the_first_burn_only(kernel, drawing, series):
    """
    The jig is cut on the first plate and left off every plate after it.

    This is the capability the engine's own placements cannot express at all: a
    placement replays the whole plan (`core/cutplan.py:225-338`), so a frame in the
    design is burned once per piece. Fails on the plausible reading of "burn once",
    which is to strip `mkonce` on every burn including the first — then the jig is never
    cut and the pieces have nothing to sit in.
    """
    a_text(drawing, "{name}")
    series.attach(a_list(FIVE[:3]))
    a_jig(drawing, kernel)
    burnable(kernel)
    series.runner = Spool(kernel)
    series.start()

    series.burn()
    series.advance()
    series.burn()

    frames = [
        [child.type for child in plan_children(plan) if getattr(child, "mkonce", None)]
        for plan in series.runner.plans
    ]
    assert frames == [["elem rect"], []]
    # And the pieces themselves are on both plates, or the removal took too much.
    assert [plan_texts(plan) for plan in series.runner.plans] == [["Anna"], ["Bram"]]


def test_a_run_started_halfway_puts_the_jig_on_its_own_first_plate(
    kernel, drawing, series
):
    """
    "The first burn" is the first plate of this run, not burn number one of the list.

    An operator who has already made two keyrings and comes back after lunch starts at
    row 2, and that is the moment the jig goes on the bed. Fails on the reading this test
    exists to rule out — `index == 0`, the first burn of the *list* — under which
    starting anywhere but the top means the jig is never cut at all.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    a_jig(drawing, kernel)
    burnable(kernel)
    series.runner = Spool(kernel)
    series.start(row=2)

    series.burn()

    assert series.state()["current_row"] == 2
    assert plan_texts(series.runner.plans[0]) == ["Cees"]
    assert [
        child.type
        for child in plan_children(series.runner.plans[0])
        if getattr(child, "mkonce", None)
    ] == ["elem rect"]


def test_the_route_s_own_mutators_are_kept_and_ours_goes_last(kernel, drawing, series):
    """
    A zero point or a print-and-cut pose still applies to a series burn.

    `burn()` is handed the mutators the route composed (`spooling()` in server.py) and
    must add to them, not replace them. Fails on `mutators=[ours]`, which would quietly
    ignore the zero point — and you would only see that on the material.
    """
    a_text(drawing, "{name}")
    series.attach(a_list())
    burnable(kernel)
    seen = []

    class Recorder:
        def start_job(self, name, mutators=()):
            seen.append(list(mutators))

    series.runner = Recorder()
    series.start()
    marker = object()

    series.burn(mutators=[marker])

    assert len(seen) == 1
    assert seen[0][0] is marker
    assert isinstance(seen[0][-1], OverrunMutator)


# --------------------------------------------------------------------------- #
# Burn only once: the flag on the shape
# --------------------------------------------------------------------------- #


def reload_design(kernel, drawing) -> None:
    """
    Write the design out and read it back, with nothing kept in between.

    `clear_all()` empties the element tree, so nothing survives in memory: what comes
    back has been through MeerK40t's own SVG writer and reader, which is exactly the
    journey a sheet, the recovery file and a project bundle make.
    """
    written = drawing.export_svg("once.svg")
    kernel.elements.clear_all()
    drawing.runner.run(f'load "{written}"')


@pytest.fixture
def drawing_with_runner(kernel):
    return Drawing(kernel, CommandRunner(kernel))


def test_burn_once_survives_a_project_save_and_reopen(kernel, drawing_with_runner):
    """
    `mkonce` comes back after a save and a reopen, and a name without `mk` does not.

    The prefix is the whole mechanism and it is worth pinning in both directions: the
    SVG writer emits every non-underscore attribute of scalar type in one generic loop
    (`core/svg_io.py:457-473`) while the reader restores only the ones beginning with
    `mk` (`core/svg_io.py:872-899`). Measured: `mkonce` came back as the string `'1'`
    and a `burnonce` beside it was written into the file and was gone on reload. So a
    differently named flag would work all afternoon and be lost the first time somebody
    saved.
    """
    drawing = drawing_with_runner
    element = drawing.create(
        "rect", x_mm=10, y_mm=10, width_mm=40, height_mm=20
    )["ids"][0]
    drawing.once([element])
    node_of(kernel, element).burnonce = "1"

    reload_design(kernel, drawing)

    back = [node for node in kernel.elements.elems()]
    assert len(back) == 1
    assert bool(getattr(back[0], "mkonce", None)) is True
    assert getattr(back[0], "burnonce", None) is None


def test_burning_every_time_again_deletes_the_flag_instead_of_writing_false(
    kernel, drawing_with_runner
):
    """
    Switching it off must take the attribute away, because `False` comes back truthy.

    Measured, and it is the one mistake there is no way back from inside a saved file:
    `mkonce = False` is written as the four characters `False` and the reader hands that
    string straight back, so `bool(node.mkonce)` is True for ever after. Every shape
    anybody ever switched off would then be left off every plate but the first.
    """
    drawing = drawing_with_runner
    element = drawing.create(
        "rect", x_mm=10, y_mm=10, width_mm=40, height_mm=20
    )["ids"][0]
    drawing.once([element])

    answer = drawing.once([element], once=False)

    assert answer == {"ids": [element], "once": False, "changed": 1}
    assert not hasattr(node_of(kernel, element), "mkonce")
    reload_design(kernel, drawing)
    assert bool(getattr(list(kernel.elements.elems())[0], "mkonce", None)) is False


def test_asking_twice_for_the_same_thing_changes_nothing(kernel, drawing_with_runner):
    """
    The menu row is one row with two wordings, so it is pressed at whatever it says.

    `changed` is what tells the panel something happened; reporting a change that did not
    happen would put an entry on the undo stack for a press that did nothing.
    """
    drawing = drawing_with_runner
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=40, height_mm=20)[
        "ids"
    ][0]
    drawing.once([element])

    assert drawing.once([element])["changed"] == 0


def test_the_snapshot_says_whether_a_shape_burns_only_once(kernel, drawing_with_runner):
    """
    The flag rides in every snapshot, like the lock does.

    Without it the right-click row cannot know which of its two wordings to show, and
    the Series window cannot say which shape is the jig. Fails on an implementation that
    keeps `mkonce` on the node and never reports it — which looks fine until somebody
    opens the menu.
    """
    drawing = drawing_with_runner
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=40, height_mm=20)[
        "ids"
    ][0]
    reader = DesignReader(kernel)

    assert [e["once"] for e in reader.snapshot()["elements"]] == [False]

    drawing.once([element])

    assert [e["once"] for e in reader.snapshot()["elements"]] == [True]


# ------------------------------------------------- the corpse of a placeholder


def test_a_shape_with_no_box_does_not_brick_the_canvas(kernel, tmp_path):
    """
    A snapshot carrying `nan` answered 500, and the project could not be opened at all.

    How one gets made, measured this week: a text whose *whole* content is a placeholder
    has no geometry while no list is attached, the engine writes it into the SVG as
    `<path d="">`, and reading that file back gives an `elem point` with
    `bounds == (nan, nan, nan, nan)`. `nan` is not JSON and FastAPI serialises strictly,
    so `GET /api/design` answered `ValueError: Out of range float values are not JSON
    compliant` — a 500 on the one route the canvas cannot live without. The shape could
    not be clicked away either, because nothing of it renders.

    Reachable with no series in sight, which is why this test is about the snapshot and
    not about a list. What it pins: the answer is JSON, the shape is still named so that
    something can offer to delete it, and it says it is broken.
    """
    import json

    from openkerf_api.design import DesignReader

    kernel.elements.elem_branch.add(
        type="elem point", x=float("nan"), y=float("nan")
    )
    kernel.elements.validate_ids()

    snapshot = DesignReader(kernel).snapshot()

    # `allow_nan=False` is what FastAPI does; with the old code this raised.
    json.dumps(snapshot, allow_nan=False)
    broken = [e for e in snapshot["elements"] if e["broken"]]
    assert len(broken) == 1, snapshot["elements"]
    assert broken[0]["bounds"] is None
    assert broken[0]["id"], "a shape nobody can name is a shape nobody can delete"
