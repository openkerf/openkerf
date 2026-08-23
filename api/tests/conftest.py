"""
A minimal MeerK40t kernel for tests.

Mirrors upstream `test/bootstrap.py`, trimmed to the plugins the API touches,
and with our own plugin added so the console command is registered exactly as
it would be through the entry point.

It also fences the library off from the developer's own one — see
`_library_of_its_own`, which is autouse and therefore the one place that has to be
right.
"""

import pytest
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


@pytest.fixture
def kernel():
    k = _bootstrap()
    try:
        yield k
    finally:
        k()
