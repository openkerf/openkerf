"""
The first layer of a Ruida job at its own speed, not at the driver's default.

`RuidaDriver._move` writes a speed only when `speed_dirty` is set
(`ruida/driver.py:557`). It is set once, when the driver is made, so the job's very first
move — a jump to the first shape — writes the driver's default speed, 10 mm/s. Then the
driver sees that the layer wants another speed and calls `self.set("speed", ...)`
(`driver.py:212`), and `set` is a docstring and nothing else (`driver.py:116`). The new
speed lands in `self.settings` a line later, but nothing marks it dirty again, so it is
never written. Measured on a filled 10×5 mm rectangle in a 150 mm/s raster layer: the
layer block says `Speed Laser 1 150.0mm/s` and then, right before the first move, the cut
stream says `Speed Laser 1 10.0mm/s`, and nothing after it: all 465 cut commands at 10.
Every later layer starts with its own block, so it is the first layer of a job that is
hit, whatever its speed, unless that speed happens to be 10. Measured with a 25 mm/s cut
layer before a 300 mm/s engrave layer: the cut layer's 4 cuts at 10, the engrave layer's
4 at 300.

Whether a controller burns those cuts at 10 mm/s has not been measured on a machine. If it
does, a 300 mm/s engraving gets thirty times the energy per millimetre it was set up for.

The repair is the one line `set` is missing: a new speed is a dirty speed, so the next
move writes it. Same file, same order of commands, one `Speed Laser 1` more, in the right
place. Installed from our plugin, like the rasteriser, and only while `set` is still
empty: an engine that fixes it itself keeps its own.
"""

from __future__ import annotations


def _empty(self, key, value):
    """Stand-in with the same body as the engine's `set`: a docstring."""


def install() -> bool:
    """Repair `RuidaDriver.set`; hands back whether anything was changed."""
    try:
        from meerk40t.ruida.driver import RuidaDriver
    except ImportError:
        return False
    current = RuidaDriver.set
    if getattr(current, "openkerf_speed_repair", False):
        return False
    if current.__code__.co_code != _empty.__code__.co_code:
        return False

    def set(self, key, value):
        if key == "speed":
            self.speed_dirty = True

    set.__doc__ = current.__doc__
    set.openkerf_speed_repair = True
    RuidaDriver.set = set
    return True
