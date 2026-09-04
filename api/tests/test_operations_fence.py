"""
The fence around the engine's layer list.

`openkerf -o <path>` is what keeps a script that makes layers — the handbook's
screenshot set does — out of the layer list of the app the user works in. That list
lives in `Settings(kernel.name, "operations.cfg")` (`core/elements/elements.py:764`),
so it is keyed to the name of the engine and not to the profile: `-P/--profile` does
not reach it, and neither does `ignore_settings`. `conftest.py` fences it off for
this suite by patching `Settings`; a server in another process cannot be patched,
which is why `operations.fence_operations` exists.

Everything here runs on the in-process kernel this suite already builds and writes
only under `tmp_path`. No engine is started, nothing is served, and no path outside
`tmp_path` is opened for writing — which was the question this test had to answer
before it could be written.

The one thing worth knowing about the arrangement: `conftest._operations_of_its_own`
has already replaced `elements_module.Settings` with a factory that puts every file
in *its* `tmp_path`. `fence_operations` passes an absolute path, and an absolute path
wins when `pathlib` joins (`Path("/a") / "/b" == Path("/b")`), so the file still lands
where the fence asks. `test_the_path_is_the_one_that_was_asked_for` holds that down,
because if it ever stopped being true the fence would quietly write somewhere else.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from openkerf_api.operations import fence_operations
from openkerf_api.server import ApiServer


def _layers(kernel):
    return [
        (node.type, getattr(node, "label", None)) for node in kernel.elements.op_branch.children
    ]


def _a_layer(kernel, label, speed=123.0):
    return kernel.elements.op_branch.add(type="op engrave", label=label, speed=speed, power=400)


def test_the_path_is_the_one_that_was_asked_for(kernel, tmp_path):
    """The layer list ends up in the file the fence names, and nowhere else."""
    wanted = tmp_path / "fenced" / "operations.cfg"
    fence_operations(kernel, wanted)

    assert Path(kernel.elements.op_data._config_file) == wanted
    # The directory is made, because the caller gives a path and not a place that
    # already exists — a scratch server names one that has never been used before.
    assert wanted.parent.is_dir()


def test_the_layers_the_engine_booted_with_are_dropped(kernel, tmp_path):
    """
    Redirecting the file is only half a fence.

    The layers that are in memory came out of the user's own `operations.cfg` at
    boot, before anything could be redirected. Left in place they are photographed
    and they end up in what the fenced file saves — so the fence has to forget them.

    Who does the forgetting is the engine: `load_persistent_operations` clears
    before it reads. This asks for the outcome and not for the line, which is why it
    stayed green when the explicit `clear_operations()` was taken out of the fence
    again — and why it is still the assertion worth having: the day that default
    changes, this fails.
    """
    _a_layer(kernel, "From the user's own file")
    assert _layers(kernel)

    fence_operations(kernel, tmp_path / "operations.cfg")

    assert _layers(kernel) == []


def test_the_layers_of_the_fenced_file_are_read_back(kernel, tmp_path):
    """A second run against the same scratch file finds what the first one left."""
    fenced = tmp_path / "operations.cfg"
    fence_operations(kernel, fenced)
    _a_layer(kernel, "Logo area")
    kernel.elements.save_persistent_operations_list("previous")
    kernel.elements.op_data.write_configuration()
    assert fenced.exists(), "the fenced file is where the writing goes"

    # A fence a second time, as a restart of that scratch server would do.
    _a_layer(kernel, "Something else entirely")
    fence_operations(kernel, fenced)

    assert [label for _, label in _layers(kernel)] == ["Logo area"]


def test_the_defaults_come_from_the_fenced_file_too(kernel, tmp_path):
    """
    The third reader of the same file, and the one that actually bit.

    `init_default_operations_nodes` (`elements.py:1872`) loads the `[_default …]`
    sections as the set the engine files a new shape under when its colour has no
    layer yet. That is where the pre-flight picture's stray "Engrave, 20 mm/s, 100%"
    came from: not from the seeding, but from the developer's own file. Recomputing
    it is part of the fence, so the defaults are the engine's own make-up set and
    not somebody's.
    """
    _a_layer(kernel, "A default of the user's own", speed=20.0)
    kernel.elements.save_persistent_operations_list("_default")
    kernel.elements.op_data.write_configuration()
    kernel.elements.init_default_operations_nodes()
    assert "A default of the user's own" in [
        getattr(op, "label", None) for op in kernel.elements.default_operations
    ]

    fence_operations(kernel, tmp_path / "elsewhere" / "operations.cfg")

    labels = [getattr(op, "label", None) for op in kernel.elements.default_operations]
    assert "A default of the user's own" not in labels
    # And not empty: with nothing to read the engine makes its own set, which is the
    # same set on every machine — which is what makes a picture reproducible.
    assert kernel.elements.default_operations


def test_the_wordlist_follows_the_layer_list(kernel, tmp_path):
    """
    `elements.py:770` takes the wordlist's directory from this file's, so a fence
    that moves one and not the other leaves the app writing lists beside the user's
    layers. Measured here by the directory it ends up in, not by the file: the
    wordlist writes on demand.
    """
    fenced = tmp_path / "beside" / "operations.cfg"
    fence_operations(kernel, fenced)

    assert Path(kernel.elements.mywordlist.default_filename).parent == fenced.parent


def test_without_a_path_nothing_changes(kernel):
    """
    The ordinary case: an engine started without `-o` is the engine it always was.

    A fence that only exists when asked for is the difference between a flag and a
    change of behaviour, and this is the assertion that says so.
    """
    before = Path(kernel.elements.op_data._config_file)

    server = ApiServer(kernel)

    assert server.operations_path is None
    assert Path(kernel.elements.op_data._config_file) == before


def test_the_server_says_which_layer_list_it_got(kernel, tmp_path):
    """
    `/api/health` is how a script finds out, and `docs-shots.mjs` refuses to seed
    layers unless it answers "own". Both answers are checked here, because the
    refusal is only worth anything if the other answer really happens.
    """
    with TestClient(ApiServer(kernel).build_app()) as client:
        assert client.get("/api/health").json()["operations"] == "shared"

    fenced = ApiServer(kernel, operations_path=str(tmp_path / "operations.cfg"))
    with TestClient(fenced.build_app()) as client:
        assert client.get("/api/health").json()["operations"] == "own"
    assert Path(kernel.elements.op_data._config_file) == tmp_path / "operations.cfg"
