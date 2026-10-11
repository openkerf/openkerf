"""
The RD bytes of each realtime verb, built by the engine's own `RDJob` encoders.

Every function here returns the packets one console command made the engine's
`RuidaDriver` write, in order, one `bytes` per `controller.write` call — and the engine
sends each of those as a datagram of its own. Nothing here touches a socket: the bytes
are collected with `output=list.append`, never with a session's `write`, because
`RDJob.__call__` swallows a `ConnectionError` from `output` (`ruida/rdjob.py:576-581`)
and a refused stop would then look sent.

Where each one comes from (engine `ruida/driver.py`, `ruida/controller.py`,
`ruida/device.py`, `core/spoolers.py`), and `test_ruida_link_motion.py` runs those very
functions on a stand-in controller whose `write` collects, for the same inputs:

| console command                | engine path                                   | packets          |
|--------------------------------|-----------------------------------------------|------------------|
| `move_absolute X Y`, `home`    | `RuidaDriver.move_abs` (`home` is `(0, 0)`)   | `C9 02` + a move |
| `move_relative DX DY`          | `RuidaDriver.move_rel`, `confined=True`       | `C9 02` + a move |
| `physical_home`                | `RuidaDriver.physical_home` → `home_xy`       | `D8 2A`          |
| `focusz <anything>`            | `RuidaDriver.focusz` → `focus_z`              | `D8 2E`          |
| `pause`                        | `RuidaController.pause` → `pause_process`     | `D8 02`          |
| `resume`                       | `RuidaController.resume` → `restore_process`  | `D8 03`          |
| `estop` / `abort`              | `RuidaDriver.reset` → `controller.abort` →    | `D8 01`          |
|                                | `stop_process`                                |                  |
| `lock` / `unlock`              | the spooler asks the driver for `lock_rail` / | none             |
|                                | `unlock_rail`; `RuidaDriver` has neither      |                  |

`C9 02` is `speed_laser_1(_jog_speed)` with `_jog_speed = 600.0` (`driver.py:54`).

The move after it depends on where the driver *thinks* the head is (`native_x`,
`native_y`, the raw values of the last `MEM_CURRENT_X`/`Y` reads, `controller.py:258-276`):
an X-only change goes out as `D9 00 02 <dx>` and a Y-only one as `D9 01 02 <dy>` —
relative distances, which is how the engine's emulator reads them too
(`emulator.py:589-605`) — and anything else as the absolute `D9 10 00 <x> <y>`. So the
caller has to pass that position in; the bytes cannot be had without it.

Measured, and kept on purpose because it is what the engine sent:

- `focusz 5.0000mm` and plain `focusz` both wrote exactly `D8 2E`: the distance
  never reached the controller.
- `move_relative` without `-f` runs the driver's `confined` clamp (`kernel.root` has
  no `confined`, so `getattr(..., True)`). At native (0, 0) on the default bed a
  `+10 mm` X jog and a `-5 mm` Y jog each came out as `C9 02 …` alone, no move, and
  `-10 mm, -5 mm` as an X-only `-10 mm` (`D9 00 02 7f 7f 7f 31 70`), the Y clamped
  away. Note the sign: X is clamped as if `+dx` moved towards 0. `confine` copies it.
- `unlock` and `lock` wrote 0 bytes; the spooler thread raised `AttributeError:
  'RuidaDriver' object has no attribute 'unlock_rail'`.
"""

from __future__ import annotations

from meerk40t.core.units import Length
from meerk40t.ruida.rdjob import RDJob

#: `RuidaDriver._jog_speed` (`ruida/driver.py:54`), in mm/s as `speed_laser_1` takes it.
JOG_SPEED = 600.0


def _collect(build) -> list[bytes]:
    packets: list[bytes] = []
    build(RDJob(), packets.append)
    return [bytes(p) for p in packets]


def millimetres(value: float) -> Length:
    """
    A coordinate as the console handed it to the driver.

    `machine.py` wrote `f"{value:.4f}mm"` into the command line and the console made a
    `Length` of it (`core/spoolers.py:230-232`); the same rounding to 0.1 µm here, so
    the same float arrives in `View.position`.
    """
    return Length(f"{float(value):.4f}mm")


def to_native(view, x, y, *, vector: bool = False) -> tuple[float, float]:
    """
    Design coordinates to the controller's micrometres through the device's `view`,
    exactly as `RuidaDriver.move_abs` (point) and `move_rel` (vector) call it.

    `view` is the engine device's `View`, kept up to date by `RuidaDevice.realize`
    from the bed size, scale, margins, flips, `swap_xy` and `home_corner`. Unrounded:
    the encoders truncate with `int()`, as they do for the engine.
    """
    result = view.position(x, y, vector=vector)
    return float(result[0]), float(result[1])


def jog_speed(speed: float = JOG_SPEED) -> bytes:
    """`C9 02 <speed>`: the speed every engine jog and move is sent with first."""
    return _collect(lambda job, out: job.speed_laser_1(speed, output=out))[0]


def rapid_to(x: float, y: float, native_x: float, native_y: float) -> list[bytes]:
    """
    The move half of `RuidaDriver.move_abs` (`driver.py:318-329`), for a target already
    in controller units; `[]` when the head is already there.
    """
    dx = x - native_x
    dy = y - native_y

    def build(job, out):
        if dx == 0:
            if dy != 0:
                job.rapid_move_y(dy, output=out)
        elif dy == 0:
            job.rapid_move_x(dx, output=out)
        else:
            job.rapid_move_xy(x, y, origin=True, output=out)

    return _collect(build)


def rapid_by(dx: float, dy: float, native_x: float, native_y: float) -> list[bytes]:
    """The move half of `RuidaDriver.move_rel` (`driver.py:361-373`), in controller units."""

    def build(job, out):
        if dx == 0:
            if dy != 0:
                job.rapid_move_y(dy, output=out)
        elif dy == 0:
            job.rapid_move_x(dx, output=out)
        else:
            job.rapid_move_xy(native_x + dx, native_y + dy, origin=True, output=out)

    return _collect(build)


def move_to(view, x, y, native_x: float, native_y: float,
            speed: float = JOG_SPEED) -> tuple[list[bytes], tuple[float, float]]:
    """
    `move_absolute x y` (and `home`, which is `move_abs(0, 0)`): the packets and the
    target in controller units, which the engine's `wait_for_move` then waits for.
    """
    tx, ty = to_native(view, x, y)
    return [jog_speed(speed)] + rapid_to(tx, ty, native_x, native_y), (tx, ty)


def confine(view, dx, dy, native_x: float, native_y: float):
    """
    The `confined` clamp of `RuidaDriver.move_rel` (`driver.py:339-355`), in scene units,
    on the scene-unit `dx`/`dy` before they become a vector — with one sign repaired.

    The engine computes the new X as `x - dx`. Measured on the KH-5030 (RDC6442S): a jog
    of +10 mm in X took the panel from 49.9 to 59.9, so +dx is +X; and at (0, 0) the
    engine's clamp turned that same +10 mm jog into nothing — `C9 02` and no move on the
    line, the head standing still. With `x + dx` the jog goes, and a jog off the bed is
    still cut at its edge. Y was right (`y + dy`) and is unchanged: −5 mm at 0 stays put.
    """
    new_x = native_x * view.native_scale_x + dx
    new_y = native_y * view.native_scale_y + dy
    if new_x < 0:
        dx = -native_x * view.native_scale_x
    elif new_x > view.width:
        dx = view.width - native_x * view.native_scale_x
    if new_y < 0:
        dy = -native_y * view.native_scale_y
    elif new_y > view.height:
        dy = view.height - native_y * view.native_scale_y
    return dx, dy


def move_by(view, dx, dy, native_x: float, native_y: float, *, confined: bool = True,
            speed: float = JOG_SPEED) -> tuple[list[bytes], tuple[float, float]]:
    """
    `move_relative dx dy`: the packets and the target in controller units.

    `confined=True` is what `machine.py`'s jog got (no `-f`); `False` is `-f`.
    """
    if confined:
        dx, dy = confine(view, dx, dy, native_x, native_y)
    ndx, ndy = to_native(view, dx, dy, vector=True)
    packets = [jog_speed(speed)] + rapid_by(ndx, ndy, native_x, native_y)
    return packets, (native_x + ndx, native_y + ndy)


def home_xy() -> list[bytes]:
    """`physical_home`: `D8 2A`."""
    return _collect(lambda job, out: job.home_xy(output=out))


def focus_z() -> list[bytes]:
    """`focusz`: `D8 2E`, whatever distance was asked."""
    return _collect(lambda job, out: job.focus_z(output=out))


def pause() -> list[bytes]:
    """`pause`: `D8 02`."""
    return _collect(lambda job, out: job.pause_process(output=out))


def resume() -> list[bytes]:
    """`resume`: `D8 03`."""
    return _collect(lambda job, out: job.restore_process(output=out))


def stop() -> list[bytes]:
    """`estop` / `abort`: `D8 01`."""
    return _collect(lambda job, out: job.stop_process(output=out))
