"""
De machine bewegen: homen, jogpen, ontgrendelen.

These commands set the head in motion. Unlike pausing and stopping they are not
device-specific: `core/spoolers.py` registers them on the kernel, so they always exist and
go through the active device's spooler. We report the availability anyway, so that the UI
does not have to assume it stays that way.
"""

import json

from .commands import CommandRunner
from .edits import DesignError, _finite

MOVES = ("home", "physical_home", "unlock", "lock")

# Where saved positions live (gap J6).
#
# On the device service, not in our library: a position is a property of *this* machine
# with *this* jig on it, and a service's settings are made for exactly that — they move
# along when the machine changes profile, and they survive a restart without us having to
# migrate a table. The library belongs to somebody else and is about material.
POSITIONS_KEY = "openkerf_positions"
MAX_POSITIES = 12
MAX_NAAM = 40

# The user origin (gap J12).
#
# Beside the saved positions and for the same reason: a zero point belongs to *this*
# machine with *this* offcut on it, not to the browser you happen to be sitting at. One per
# machine — two zero points at once is no longer a zero point.
ORIGIN_KEY = "openkerf_origin"

# Focusing sits on the Ruida (`focusz`), not on every device. The same approach as with
# pausing and stopping: ask what this device knows, do not assume.
FOCUS = "focusz"

# Verbinden en verbreken.
#
# Every driver family calls it something different and marks it `hidden=True`: Ruida has
# `ruida_connect` (`ruida/device.py:448`), lihuiyu, moshi, newly and balor have
# `usb_connect`. Grbl registers none — it opens its connection itself as soon as data has to
# go there. So we ask the active device what it knows, in the same order, and a machine that
# does not know it gets no button either.
CONNECTS = ("ruida_connect", "usb_connect")
DISCONNECTS = ("ruida_disconnect", "usb_disconnect")


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def _zonder_echo(output, command: str) -> str:
    """
    What the engine had to report, without the echo of the command itself.

    The console channel echoes every line that goes into it, with a timestamp. Measured on
    the real machine with an address where nothing is: the UDP session reports nothing at
    all, so the only thing left was "[11:51:29] ruida_connect". Serving that up as a reason
    is worse than saying there is no reason.
    """
    lines = [
        line
        for line in output
        if line.strip() and not line.strip().endswith(command)
    ]
    return " ".join(lines).strip()


class MachineControl:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    def capabilities(self) -> dict:
        caps = {name: self.runner.supports(name) for name in MOVES}
        caps["move"] = self.runner.supports("move_absolute")
        caps["jog"] = self.runner.supports("move_relative")
        caps["focus"] = self.runner.supports(FOCUS)
        return caps

    def connection_capabilities(self) -> dict:
        """A block of its own, not under `motion`: connecting does not move the head."""
        return {
            "connect": self._link_command(CONNECTS) is not None,
            "disconnect": self._link_command(DISCONNECTS) is not None,
        }

    # ------------------------------------------------------------- connection

    def _link_command(self, names) -> str | None:
        for name in names:
            if self.runner.supports(name):
                return name
        return None

    def _connection(self) -> dict:
        """
        Is a machine on the line? The same source as the status bar.

        `StatusReader.connection` knows per family where it is and says "unknown" where
        nothing reports it — and that last one is here the difference between "could not
        check" and "is open".
        """
        from .status import StatusReader

        return StatusReader(self.kernel).connection(getattr(self.kernel, "device", None))

    def connect(self) -> dict:
        return self._link(CONNECTS, "connect", "connected")

    def disconnect(self) -> dict:
        return self._link(DISCONNECTS, "disconnect", "disconnected")

    def _link(self, names, verb: str, wanted: str) -> dict:
        command = self._link_command(names)
        if command is None:
            raise DesignError(
                f"This device has no command to {verb}. Grbl, for instance, "
                "opens its connection itself as soon as work goes to it."
            )
        output = self.runner.run(command)
        state = self._connection()

        # The engine reports a failed connection only on the channel and then
        # returns quietly (`ruida/device.py:452`). The state afterwards is therefore
        # the only honest answer; when that cannot be read, the output is all we have
        # and we do not commit ourselves.
        if state.get("state") not in (wanted, "unknown"):
            klacht = _zonder_echo(output, command)
            raise DesignError(
                f"{verb.capitalize()}ing did not work. The engine reports: {klacht}"
                if klacht
                else f"{verb.capitalize()}ing did not work, and the engine does not say why. "
                "Is the machine on, and is the address in the machine settings right? "
                "Also possible: something was disconnected or switched in this session "
                "— the Ruida session does not always survive that, and then only "
                "a restart of the server helps."
            )
        return {"connection": state, "output": output}

    def _idle(self) -> None:
        """
        No moving while something is burning.

        The UI disables the buttons, but the UI is advice: a second tab, a phone or a curl
        command can go straight through it. Moving the head during a job ruins it at best.
        """
        device = getattr(self.kernel, "device", None)
        spooler = getattr(device, "spooler", None)
        if spooler is None:
            return
        try:
            # Look at a *running* job, not at the queue: our own home and jog also go
            # through the spooler, and they would then block each other.
            running = any(job.is_running() for job in list(spooler.queue))
        except Exception:  # pragma: no cover - the spooler must not break us
            return
        if running:
            raise DesignError(
                "A job is running. Stop it first; moving while burning "
                "ruins the job."
            )

    def _require(self, command: str):
        if not self.runner.supports(command):
            raise DesignError(
                f"This device does not know '{command}'; movement is handled by the "
                "device service itself."
            )

    def home(self, physical: bool = False, force: bool = False) -> dict:
        """
        To the zero point. The head really moves — and with a rotary fitted it moves
        into it.

        A chuck rotary stands in the bed where the gantry wants to go, so homing Y drives
        the head against it. The engine's own guard for that lives in the rotary service
        that never attaches to a Ruida (see rotary.py), so it is ours, and it is a refusal
        and not a greyed-out button: the interface is advice and a second tab takes no
        notice of it. `force` is the way through for whoever has taken the rotary out —
        the interface asks first and passes it on.
        """
        command = "physical_home" if physical else "home"
        self._require(command)
        self._idle()
        if not force:
            reason = self._rotary().homing_refusal()
            if reason is not None:
                raise DesignError(reason, code="rotary.homeWhileActive")
        return {"output": self.runner.run(command), "forced": bool(force)}

    def _rotary(self):
        from .rotary import RotaryControl

        return RotaryControl(self.kernel)

    def move_to(self, x_mm, y_mm) -> dict:
        """Absolute position. The head moves; this is not a drawing command."""
        self._require("move_absolute")
        self._idle()
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        return {"output": self.runner.run(f"move_absolute {_mm(x)} {_mm(y)}")}

    def frame(self, x_mm, y_mm, width_mm, height_mm) -> dict:
        """
        Sending the head around the four corners of the work.

        This is the last check before you burn: does it fit on the material, is it straight,
        is the clamp in the way. The laser stays off — there is only movement, with the same
        guard as on a jog.
        """
        self._require("move_absolute")
        self._idle()
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        width = _finite(width_mm, "width_mm")
        height = _finite(height_mm, "height_mm")
        if width <= 0 or height <= 0:
            raise DesignError("There is nothing to draw a frame around.")

        bed = self._bed_mm()
        if bed and (x < 0 or y < 0 or x + width > bed[0] or y + height > bed[1]):
            raise DesignError(
                f"The frame ({width:.0f}x{height:.0f} mm from {x:.0f},{y:.0f}) "
                f"falls outside the bed of {bed[0]:.0f}x{bed[1]:.0f} mm."
            )

        # Back to the first corner, so that you really see the round close.
        corners = [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
            (x, y),
        ]
        # `-f` (force) is the whole repair here. Without that flag `move_absolute` refuses
        # as soon as the spooler is not idle (`core/spoolers.py:243`), and after the first
        # corner the head is of course on its way: measured on a real machine the head went
        # to the top left and the next four corners came back as "Busy Error". With the flag
        # they go into the queue and follow each other neatly. Nothing can jump the queue:
        # that no job is running has already been checked above.
        output = []
        for hx, hy in corners:
            resultaat = self.runner.run(f"move_absolute -f {_mm(hx)} {_mm(hy)}")
            output.extend(resultaat if isinstance(resultaat, list) else [resultaat])

        # The message stays as a safety net, but should no longer go off: since the corners
        # go into the queue with `-f`, nothing refuses any more.
        busy = [r for r in output if "busy" in str(r).lower() or "error" in str(r).lower()]
        return {
            "output": output,
            "corners": len(corners),
            "notice": (
                "The machine reported it was busy; the frame may not have run "
                "all the way. Try again when the head is standing still."
                if busy
                else None
            ),
        }

    def _bed_mm(self):
        """The work area in millimetres, or None when the device does not say."""
        device = getattr(self.kernel, "device", None)
        try:
            from meerk40t.core.units import Length

            return (Length(device.bedwidth).mm, Length(device.bedheight).mm)
        except Exception:
            return None

    def jog(self, dx_mm, dy_mm) -> dict:
        self._require("move_relative")
        self._idle()
        dx = _finite(dx_mm, "dx_mm")
        dy = _finite(dy_mm, "dy_mm")
        if dx == 0 and dy == 0:
            raise DesignError("A jog of zero does nothing.")
        return {"output": self.runner.run(f"move_relative {_mm(dx)} {_mm(dy)}")}

    def focus(self, distance_mm) -> dict:
        """
        Moving the head up or down. Focusing is daily work: a new material
        thickness, a new height.
        """
        self._require(FOCUS)
        self._idle()
        distance = _finite(distance_mm, "distance_mm")
        if distance == 0:
            raise DesignError("A movement of zero does nothing.")
        if abs(distance) > 100:
            raise DesignError("More than 100 mm at once is not focusing.")
        return {"output": self.runner.run(f"{FOCUS} {_mm(distance)}")}

    # ------------------------------------------------- bewaarde positions (J6)

    def _device(self):
        device = getattr(self.kernel, "device", None)
        if device is None:
            raise DesignError("There is no active machine.")
        return device

    def positions(self) -> list[dict]:
        """
        The positions this machine remembers.

        LightBurn's Move window has them and we did not: anybody with a jig on the bed wants
        to record "top-left corner of the jig" once instead of jogging it together again
        every session.
        """
        device = self._device()
        try:
            device.setting(str, POSITIONS_KEY, "[]")
            raw = json.loads(getattr(device, POSITIONS_KEY, "[]") or "[]")
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        clean = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            x, y = item.get("x_mm"), item.get("y_mm")
            if not name or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            clean.append({"name": name, "x_mm": float(x), "y_mm": float(y)})
        return clean

    def _write_positions(self, positions: list[dict]) -> list[dict]:
        device = self._device()
        device.setting(str, POSITIONS_KEY, "[]")
        setattr(device, POSITIONS_KEY, json.dumps(positions))
        # Otherwise it is only there until the next restart, and then it is not a memory
        # but a joke.
        try:
            self.kernel.write_configuration()
        except Exception:  # pragma: no cover - the engine must not break us
            pass
        return positions

    def save_position(self, name, x_mm=None, y_mm=None) -> dict:
        """
        Save a position. Without coordinates: where the head is now.

        That last one is the normal way — you jog to the corner of your jig and record it
        there; typing numbers is possible too, but then you knew them already.
        """
        name = str(name or "").strip()[:MAX_NAAM]
        if not name:
            raise DesignError("A saved position needs a name.")

        if x_mm is None or y_mm is None:
            current = self._current_mm()
            if current is None:
                raise DesignError(
                    "This machine reports no position, so there is nothing to "
                    "keep. Fill in the coordinates by hand."
                )
            x_mm, y_mm = current
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")

        positions = [p for p in self.positions() if p["name"].lower() != name.lower()]
        positions.append({"name": name, "x_mm": round(x, 2), "y_mm": round(y, 2)})
        if len(positions) > MAX_POSITIES:
            raise DesignError(
                f"More than {MAX_POSITIES} saved positions becomes a list you have "
                "to search through. Throw one away first."
            )
        self._write_positions(positions)
        return {"name": name, "x_mm": round(x, 2), "y_mm": round(y, 2)}

    def delete_position(self, name) -> dict:
        name = str(name or "").strip()
        positions = [p for p in self.positions() if p["name"].lower() != name.lower()]
        self._write_positions(positions)
        return {"deleted": name}

    def _current_mm(self):
        """Where the head is now, in millimetres — or None when it does not say."""
        from .status import StatusReader

        positie = StatusReader(self.kernel).position(self._device())
        mm = positie.get("mm")
        if not mm or len(mm) < 2:
            return None
        return (float(mm[0]), float(mm[1]))

    # ----------------------------------------------- user origin (J12)
    #
    # LightBurn has Set Origin / Clear Origin / Go to Origin: you put a zero point on your
    # workpiece and the work burns from there. That is the operation when aligning on an
    # offcut — the board lies askew in the bed, and you do not want to drag your whole
    # drawing to get it onto it.
    #
    # The engine does not know it (a grep over `core` and `ruida` for `user_origin` and
    # `set_origin`: no hits), so this is our layer. Deliberately no change to the device's
    # `View`: that also carries homing and the canvas size, and a zero point that silently
    # moves the bed is a trap. It is a shift applied once, at the moment the work goes into
    # the machine — see `Drawing.shifted`.

    def origin(self) -> dict | None:
        """The zero point of this machine, or None when none is set."""
        try:
            device = self._device()
        except DesignError:
            return None
        try:
            device.setting(str, ORIGIN_KEY, "")
            raw = getattr(device, ORIGIN_KEY, "") or ""
            if not raw:
                return None
            value = json.loads(raw)
        except Exception:
            return None
        if not isinstance(value, dict):
            return None
        x, y = value.get("x_mm"), value.get("y_mm")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return {"x_mm": float(x), "y_mm": float(y)}

    def set_origin(self, x_mm=None, y_mm=None) -> dict:
        """
        Record the zero point. Without coordinates: where the head is now.

        That last one is the normal way — you jog to the corner of your board and press the
        button. Typing numbers is possible, but then you knew them already.
        """
        if x_mm is None or y_mm is None:
            current = self._current_mm()
            if current is None:
                raise DesignError(
                    "This machine reports no position, so no zero point can be "
                    "set. Fill in the coordinates by hand."
                )
            x_mm, y_mm = current
        x = round(_finite(x_mm, "x_mm"), 2)
        y = round(_finite(y_mm, "y_mm"), 2)

        bed = self._bed_mm()
        if bed and not (0 <= x <= bed[0] and 0 <= y <= bed[1]):
            raise DesignError(
                f"That point ({x:.0f},{y:.0f} mm) lies outside the bed of "
                f"{bed[0]:.0f}x{bed[1]:.0f} mm. The head does not go there."
            )

        device = self._device()
        device.setting(str, ORIGIN_KEY, "")
        setattr(device, ORIGIN_KEY, json.dumps({"x_mm": x, "y_mm": y}))
        self._store()
        return {"x_mm": x, "y_mm": y}

    def clear_origin(self) -> dict:
        """Back to the machine's own zero point."""
        device = self._device()
        device.setting(str, ORIGIN_KEY, "")
        setattr(device, ORIGIN_KEY, "")
        self._store()
        return {"cleared": True}

    def _store(self) -> None:
        # Otherwise it is there until the next restart, and then it is not a zero point but
        # a joke.
        try:
            self.kernel.write_configuration()
        except Exception:  # pragma: no cover - the engine must not break us
            pass

    # ---------------------------------------------- adjusting during a job (J11)
    #
    # In its Move window LightBurn has two columns "Adjust Speed" and "Adjust Power" with
    # which you rescue a running job instead of doing it again. The engine can do this, but
    # not everywhere: only the grbl driver has `set_power_scale`/`set_speed_scale` (realtime
    # overrides 0x90/0x99), and it is also the only one that sets
    # `has_adjustable_power`/`has_adjustable_speed` to True. The Ruida driver sets speed and
    # power per cut segment from the settings and has no realtime channel for it.
    #
    # So: the same rule as with air assist and the Z axis — what the machine *can* do decides
    # what you see. On a Ruida these buttons do not exist.

    ADJUST_MIN = 0.1
    ADJUST_MAX = 2.0

    def _driver(self):
        return getattr(getattr(self.kernel, "device", None), "driver", None)

    def _can(self, wat: str) -> bool:
        driver = self._driver()
        question = getattr(driver, f"has_adjustable_{wat}", None)
        if question is None:
            return False
        try:
            return bool(question())
        except Exception:  # pragma: no cover - a driver that does not co-operate
            return False

    def adjust_capabilities(self) -> dict:
        return {"power": self._can("power"), "speed": self._can("speed")}

    def adjustment(self) -> dict:
        """What is adjusted right now, as a factor (1.0 = as designed)."""
        driver = self._driver()
        caps = self.adjust_capabilities()
        return {
            "power": float(getattr(driver, "power_scale", 1.0) or 1.0)
            if caps["power"]
            else None,
            "speed": float(getattr(driver, "speed_scale", 1.0) or 1.0)
            if caps["speed"]
            else None,
            "supported": caps,
        }

    def adjust(self, power=None, speed=None) -> dict:
        """
        Adjusting speed and power, while the job is running as well.

        The factor is a multiplication on what the layer says, not a new value: the layer
        keeps its setting, because that is evidence (it may come from a preset). This is a
        correction to one burn session.
        """
        driver = self._driver()
        if driver is None:
            raise DesignError("There is no active machine.")
        applied = {}
        for name, value in (("power", power), ("speed", speed)):
            if value is None:
                continue
            if not self._can(name):
                raise DesignError(
                    "This machine cannot adjust speed and power during a job. "
                    "The driver has no realtime channel for it; "
                    "stop the job, change the layer and start again."
                )
            factor = _finite(value, name)
            if not self.ADJUST_MIN <= factor <= self.ADJUST_MAX:
                raise DesignError(
                    f"A factor of {factor:.2f} falls outside what the machine "
                    f"accepts ({self.ADJUST_MIN:g}–{self.ADJUST_MAX:g})."
                )
            getattr(driver, f"set_{name}_scale")(factor)
            applied[name] = factor
        if not applied:
            raise DesignError("Give a factor for speed or power.")
        return {**self.adjustment(), "applied": applied}

    def unlock(self) -> dict:
        """Release the motors, so the head can be moved by hand."""
        self._require("unlock")
        return {"output": self.runner.run("unlock")}

    def lock(self) -> dict:
        self._require("lock")
        return {"output": self.runner.run("lock")}
