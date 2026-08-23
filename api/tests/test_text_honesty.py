"""
Text that burns what the screen showed, and nothing else.

Three honesty faults in the same branch of `Drawing`, each one measured on the engine
before it was closed here:

- placing one line of text in a chosen typeface silently made that typeface the app-wide
  default, so the next text — and the captions on the next test board — came out in it;
- a curly bracket that does not open and close once around a name makes the engine
  swallow the text around it, or engrave a bracket nobody can use;
- a placeholder that counts backwards walks off the front of the list and engraves the
  list's own bookkeeping as real geometry.

None of the three announced itself. That is what these tests are for: each one names the
thing that would come out of the machine if it were removed.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer

#: The engine ships this one itself, so it is here on every machine the suite runs on —
#: `testgrid.LABEL_FONTS` starts with it for the same reason.
OWN_FONT = "meerk40t.jhf"


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def _font_of(kernel, element_id):
    return getattr(kernel.elements.find_node(element_id), "mkfont", None)


def _some_other_font(kernel):
    """
    A valid typeface on this computer that is not the engine's own.

    Needed to tell a restored preference apart from the engine's fallback: with no usable
    `last_font`, `retrieve_font` walks a candidate list that begins with "arial.ttf"
    (`meerk40t/extra/hershey.py:415-427`), so on a machine with Arial an assertion about
    Arial proves nothing at all.
    """
    registry = kernel.root.fonts
    for entry in registry.available_fonts():
        name = registry.short_name(entry[0])
        if name.lower() != OWN_FONT and registry._validate_font(entry[0]):
            return entry[0], name
    return None, None


def _wordlist_with_three_names(kernel):
    """A three-name list standing on its first row, as a series would leave it."""
    wordlist = kernel.elements.mywordlist
    wordlist.empty_csv()
    for name in ("Anna", "Bram", "Cees"):
        wordlist.set_value("name", name, idx=-1, wtype=1)
    wordlist.set_index("name", 0)
    return wordlist


# ----------------------------------------------------------------- the font trap


def test_placing_text_with_a_font_leaves_the_last_chosen_font_alone(kernel, drawing):
    """
    One text in a chosen typeface must not dress every text after it.

    `create_linetext_node` writes the typeface it used into `context.last_font`
    unconditionally (`meerk40t/extra/hershey.py:492`) and a `linetext` without `-f` reads
    that setting back (`hershey.py:894`). Measured before the guard, on this suite's
    kernel: with `last_font` standing on NewYork.ttf a text without a font came out in
    NewYork.ttf, then one text placed with `-f "meerk40t.jhf"` left `last_font` on
    'meerk40t.jhf', and the very same font-less request came out in meerk40t.jhf. That is
    how a test board once came out in Apple Chancery.

    Remove the guard in `Drawing._keep_last_font` and both halves of this go red: the
    setting keeps our caller's choice, and the next text inherits it.
    """
    full, short = _some_other_font(kernel)
    if full is None:
        pytest.skip("this computer has no typeface besides the engine's own")
    root = kernel.root
    root.setting(str, "last_font", "")
    root.last_font = full

    chosen = drawing.create("text", x_mm=10, y_mm=10, text="AB", font=OWN_FONT)
    # The text really was set in what we asked for; otherwise this test would pass on a
    # command that quietly did nothing.
    assert _font_of(kernel, chosen["ids"][0]) == OWN_FONT
    assert root.last_font == full

    after = drawing.create("text", x_mm=10, y_mm=40, text="CD")
    assert _font_of(kernel, after["ids"][0]) == short


def test_editing_text_leaves_the_last_chosen_font_alone(kernel, drawing):
    """
    The other door into the same setting, and today it is the quiet one.

    `update_linetext` re-renders without touching `last_font`
    (`meerk40t/extra/hershey.py:340-390`), so editing is safe as things stand. This test
    exists because that is an engine detail we lean on: a series re-renders every text on
    the bed on every row change, and if upstream ever gives `update_linetext` the same
    unconditional write its sibling has, fifty re-renders would spread the trap instead of
    one placement.
    """
    full, _short = _some_other_font(kernel)
    if full is None:
        pytest.skip("this computer has no typeface besides the engine's own")
    made = drawing.create("text", x_mm=10, y_mm=10, text="AB")
    kernel.root.last_font = full

    drawing.update_text(made["ids"][0], text="CD", font=OWN_FONT)

    assert kernel.root.last_font == full


# ------------------------------------------------------------------ braces


def test_a_brace_that_does_not_open_and_close_once_is_refused(drawing):
    """
    Each of these burns something the screen never showed.

    Measured on the engine's own `wordlist_translate` with a three-name list: 'a {{name}}'
    renders 'a }', '{{name}' renders '' — the inner pair is read as a key nobody has and
    deleted — while '{name' and '{}' survive as themselves and go on the workpiece as
    brackets. There is no escape in the engine's syntax, so none of the four can be
    honoured; the refusal is the only honest answer.
    """
    for bad in ("a {{name}}", "{{name}", "{name", "name}", "{}", "{ }"):
        with pytest.raises(DesignError) as refused:
            drawing.create("text", x_mm=10, y_mm=10, text=bad)
        assert refused.value.code == "draw.bracesInText", bad


def test_the_engine_swallows_what_a_doubled_brace_holds(kernel):
    """
    The counter-proof under the refusal above, and the tripwire under it.

    If upstream ever gives the wordlist a real escape, these renderings change and this
    test goes red — which is the moment to lift the refusal rather than the moment to
    discover the refusal was never needed. Values measured today, list standing on row 0.
    """
    _wordlist_with_three_names(kernel)
    translate = kernel.elements.wordlist_translate

    assert translate("a {{name}}", increment=False) == "a }"
    assert translate("{{name}", increment=False) == ""
    assert translate("{name", increment=False) == "{name"
    # And the one that is not swallowed but simply left standing.
    assert translate("{}", increment=False) == "{}"


def test_a_placeholder_a_list_can_fill_is_still_allowed(kernel, drawing):
    """
    The refusals must not take the feature away.

    Substitution is the engine's and it is why braces are in a text at all
    (`meerk40t/extra/hershey.py:355`). A guard that refused `{name}` would close the door
    this whole family of text is walking through, so the well-formed cases are pinned
    here beside the malformed ones.
    """
    _wordlist_with_three_names(kernel)

    for good in ("{name}", "{name#+1}", "Plate {name} of ours", "{name#2}", "{date}"):
        made = drawing.create("text", x_mm=10, y_mm=10, text=good)
        assert made["ids"], good


# ------------------------------------------------------- counting backwards


def test_a_placeholder_that_counts_backwards_is_refused(kernel, drawing):
    """
    A negative offset does not read an earlier row; it reads the list's own head.

    `fetch_value` guards only the upper bound (`meerk40t/core/wordlist.py:263-269`).
    Measured with a three-name list on its first row: '{name#-1}' renders '2' — the row
    pointer — and '{name#-2}' renders '1', the type field. Both doors are checked, because
    a placeholder typed into an existing shape burns exactly the same thing.
    """
    _wordlist_with_three_names(kernel)
    made = drawing.create("text", x_mm=10, y_mm=10, text="{name}")

    for bad in ("{name#-1}", "{name#-2}", "Plate {name#-10}"):
        with pytest.raises(DesignError) as placing:
            drawing.create("text", x_mm=10, y_mm=40, text=bad)
        assert placing.value.code == "draw.backwardsPlaceholder", bad

        with pytest.raises(DesignError) as editing:
            drawing.update_text(made["ids"][0], text=bad)
        assert editing.value.code == "draw.backwardsPlaceholder", bad


def test_the_engine_engraves_its_own_bookkeeping_for_a_backwards_placeholder(kernel):
    """
    What the refusal above buys, measured on a real node instead of on a string.

    The same `linetext` the API runs, driven straight from the console so it goes round our
    guard: the node's `_translated_text` — the text that became geometry — is '2', the
    list's row pointer, on a bed where the reader asked for a name.
    """
    _wordlist_with_three_names(kernel)

    kernel.console('linetext 10mm 10mm "{name#-1}"\n')

    node = next(n for n in kernel.elements.elems() if getattr(n, "mktext", None))
    assert node.mktext == "{name#-1}"
    assert node._translated_text == "2"


# --------------------------------------------------- refusals a reader can read


def test_a_font_name_with_a_quotation_mark_is_refused_in_a_sentence_with_a_code(drawing):
    """
    This refusal used to be the Dutch "Ongeldige fontnaam." with no code at all.

    A message without a code cannot be translated (`i18n/README.md`, "The engine layer"),
    and one in Dutch cannot be read by the curl user the engine layer is English for. The
    check itself stays: the name goes between quotes on the console line, so a quotation
    mark inside it ends the argument halfway through.
    """
    with pytest.raises(DesignError) as refused:
        drawing.create("text", x_mm=10, y_mm=10, text="AB", font='Ari"al.ttf')

    assert refused.value.code == "draw.badFontName"
    assert "quotation mark" in str(refused.value)


def test_an_unknown_alignment_is_refused_with_a_code(drawing):
    """
    Same fault, one field along: a refusal a panel could only show in English.

    The sentence names the three values on purpose, so a client without a catalogue reads
    what it may send.
    """
    made = drawing.create("text", x_mm=10, y_mm=10, text="AB")

    with pytest.raises(DesignError) as refused:
        drawing.update_text(made["ids"][0], align="left")

    assert refused.value.code == "draw.badAlign"
    assert "start, middle or end" in str(refused.value)


def test_the_refusal_reaches_the_client_as_a_code_and_not_a_500(client):
    """
    The code has to survive the route, or the interface cannot say any of this in Dutch.

    Placing a shape goes through `manage()`, which turns a refusal of ours into a 409 with
    the code in `X-OpenKerf-Error`. Without that, a doubled brace would arrive as a 500
    and the panel could only say that something went wrong.
    """
    response = client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 10, "y_mm": 10, "text": "a {{name}}"},
    )

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "draw.bracesInText"
    assert response.json()["detail"].startswith("A curly bracket")
