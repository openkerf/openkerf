"""
A minimal MeerK40t kernel for tests.

Mirrors upstream `test/bootstrap.py`, trimmed to the plugins the API touches,
and with our own plugin added so the console command is registered exactly as
it would be through the entry point.
"""

import pytest
from meerk40t.kernel import Kernel

from openkerf_api.plugin import plugin as openkerf_plugin


def _bootstrap(profile="OpenKerf_TEST"):
    kernel = Kernel("MeerK40t", "0.0.0-testing", profile, ansi=False, ignore_settings=True)

    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import cag, coolant, hershey
    from meerk40t.fill import fills
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
        potrace,
        fills,
        cag,  # union/difference/intersection/xor
        coolant,
        hershey,  # levert `linetext`: vector-tekst voor de rasterlabels
        svg_io,
        ruidadevice,
    ):
        kernel.add_plugin(mod.plugin)
    kernel.add_plugin(openkerf_plugin)

    kernel(partial=True)
    kernel.console("service device start dummy 0\n")
    return kernel


@pytest.fixture
def kernel():
    k = _bootstrap()
    try:
        yield k
    finally:
        k()
