"""
A minimal MeerK40t kernel for tests.

Mirrors upstream `test/bootstrap.py`, trimmed to the plugins the API touches,
and with our own plugin added so the console command is registered exactly as
it would be through the entry point.

It also fences two of the developer's own files off — the library
(`_library_of_its_own`) and the layer list the engine keeps between sessions
(`_operations_of_its_own`). Both are autouse, because a fence with a gate per test
only has to be forgotten once.
"""

import pytest
from meerk40t.core.elements import elements as elements_module
from meerk40t.kernel import Kernel

from openkerf_api import server as server_module
from openkerf_api.plugin import plugin as openkerf_plugin


def _bootstrap(profile="OpenKerf_TEST"):
    kernel = Kernel("MeerK40t", "0.0.0-testing", profile, ansi=False, ignore_settings=True)

    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import cag, coolant, hershey
    from meerk40t.fill import fills
    from meerk40t.camera import plugin as camera_plugin
    from meerk40t.extra import param_functions, potrace, vectrace
    from meerk40t.image import imagetools
    from meerk40t.network import kernelserver
    from meerk40t.ruida import plugin as ruidadevice

    # coolant before the drivers: Ruida's service claims a coolant channel at init.
    for mod in (
        kernelserver,
        basedevice,  # registers the `device` commands (add/activate/duplicate)
        dummydevice,
        core,
        imagetools,
        vectrace,  # `vectrace`: afbeelding naar paden
        param_functions,  # `shape`: veelhoeken en sterren
        camera_plugin,  # camerabeeld; trekt zichzelf terug zonder OpenCV
        potrace,
        fills,
        cag,  # union/difference/intersection/xor
        coolant,
        hershey,  # provides `linetext`: vector text for the grid labels
        svg_io,
        ruidadevice,
    ):
        kernel.add_plugin(mod.plugin)
    kernel.add_plugin(openkerf_plugin)

    kernel(partial=True)
    kernel.console("service device start dummy 0\n")
    return kernel


@pytest.fixture(autouse=True)
def _library_of_its_own(tmp_path, monkeypatch):
    """
    No test may open the library the developer actually uses.

    `ApiServer(kernel)` without a `library_path` falls back to `default_path(kernel)`,
    and that path is keyed to `kernel.name` — never to the profile, whatever `-P` says
    (see `library.default_path` and the `-P/--profile` row in CLAUDE.md). Our own
    `profile="OpenKerf_TEST", ignore_settings=True` therefore isolates the *engine's*
    settings and not the library: eleven fixtures across this suite were opening
    `~/Library/Application Support/MeerK40t/openkerf-library.db`, the author's real
    204 KB file with 7 profiles, 20 materials, 35 presets and 32 boards in it.

    Measured, and this is not hypothetical: a `pytest api/tests` run took that file from
    `PRAGMA user_version` 0 to 1 and relabelled its 26 imported notes, because the
    library grew a migration this round. Nothing was lost — verified on the file, same
    counts before and after — but the next migration would land on somebody's real
    database before anyone had reviewed it. And the library's path decides more than the
    database: `ApiServer._beside` puts the sheets directory, the provenance, the palette
    and the tile series next to it, and *moves* the pre-language-round Dutch names on the
    way, so a test run was also rearranging live work.

    Autouse and in one place rather than a keyword on every `ApiServer(...)`, because a
    fence with eleven gates only has to be forgotten once. An explicit `library_path`
    still wins, so the fixtures that already pass one are unaffected.
    """
    library = tmp_path / "openkerf-library.db"
    monkeypatch.setattr(server_module, "default_path", lambda kernel: library)
    return library


@pytest.fixture(autouse=True)
def _operations_of_its_own(tmp_path, monkeypatch):
    """
    No test may write the layer list the developer's own app starts with.

    `Elements` keeps that list in a file of its own (`core/elements/elements.py:764`:
    `Settings(self.kernel.name, "operations.cfg", create_backup=True)`), reads it back at
    boot (`:773`, `load_persistent_operations("previous")`) and writes it again at
    shutdown (`:1526`). The directory comes from the **kernel name**, so neither our
    `profile="OpenKerf_TEST"` nor `ignore_settings=True` reaches it — the same hole as the
    library had, and the `-P/--profile` row in CLAUDE.md is the same hole a third time.

    Measured, and not hypothetical: one run of `pytest api/tests/test_testgrid.py` took
    `~/Library/Application Support/MeerK40t/operations.cfg` from 3 `[previous]` sections
    to **20**, among them "Board code" and "Board labels" — a whole test board's worth of
    layers, which is what the real app would then have offered as its layer list.

    It is also why a green single-file run was not evidence. Every kernel writes the file
    on teardown and the next kernel reads it, so tests handed each other layers *within*
    one run: `test_import_hygiene.py` alone was 2 failed / 16 passed straight after a
    `test_testgrid.py` run and 18 passed straight after itself. Redirecting the path
    closes both directions at once — nothing is read in, nothing is written out.

    `Settings(None, <name>)` keeps the name as the whole path (`kernel/settings.py:30-35`),
    which is how an absolute one gets in. The wordlist follows it, because `elements.py:770`
    takes its directory from this file's.
    """
    real = elements_module.Settings

    def of_its_own(directory, filename, *args, **kwargs):
        return real(None, str(tmp_path / filename), *args, **kwargs)

    monkeypatch.setattr(elements_module, "Settings", of_its_own)
    return tmp_path / "operations.cfg"


@pytest.fixture(autouse=True)
def _projects_of_their_own(tmp_path, monkeypatch):
    """
    No test may write into the projects folder of the developer's own app.

    `ApiServer(kernel)` without `projects` falls back to `projects/` beside the library
    file, and the library's default path is keyed to the kernel name (see the fixture
    above). So every test server is handed a folder under `tmp_path` here, the way the
    library and the layer list are.

    `projects` is not yet a keyword `ApiServer.__init__` accepts — the class this fixture
    fences has no routes yet, only `openkerf_api.projects.Projects` used directly by its
    own tests. The `kwargs.setdefault("projects", folder)` line that actually hands the
    folder to `ApiServer` arrives with the routes, in the next round; until then this
    patch is a no-op that only reserves the shape.
    """
    folder = tmp_path / "projects"
    original = server_module.ApiServer.__init__

    def patched(self, *args, **kwargs):
        return original(self, *args, **kwargs)

    monkeypatch.setattr(server_module.ApiServer, "__init__", patched)
    return folder


@pytest.fixture
def kernel():
    k = _bootstrap()
    try:
        yield k
    finally:
        k()
