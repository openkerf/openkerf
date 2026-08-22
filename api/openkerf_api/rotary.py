"""
Burning on a cylinder: the rotary.

A chuck or roller rotary turns the workpiece under the head. Y stops being a distance
across the bed and becomes an angle around the object — but the *number* you draw stays a
millimetre on the surface of that object, and that is the whole convention of this module.

## Why the engine does not do this for us

MeerK40t has a rotary service (`meerk40t/rotary/`), and it never loads on the machine this
project is built for. `rotary/rotary.py:145-152` returns exactly five provider paths from
its `"service"` lifecycle — lhystudios, grbl, balor, newly and moshi — and the Ruida
registers itself as `provider/device/ruida` (`ruida/plugin.py:20`). The kernel files a
service plugin under the paths it returns (`kernel/kernel.py:386-396`), so on a Ruida the
delegate, its sixteen settings and its console commands are structurally unreachable.
Measured headless with both devices in one kernel: on the Ruida `hasattr(device, "rotary")`
is False and `lookup("choices/rotary")` is None; on the grbl both are there. `grep -rniE
rotar meerk40t/ruida/` gives zero hits, so the driver has no hook of its own either.

## The one piece that is not driver-specific

`core/cutplan.py:157-159`, inside `CutPlan.preprocess`:

    rotary = getattr(device, "rotary", None)
    if rotary is not None and rotary.active:
        scene_to_device_matrix.post_scale(rotary.scale_x, rotary.scale_y)

That is in core and duck-typed on three attribute names. So we hang an object with
`.active`, `.scale_x` and `.scale_y` on the active device while the plan is being built —
exactly where `Drawing.shifted` puts the zero point — and the engine does the rest. Nothing
changes in `meerk40t/`. Measured on a Ruida with a 30x20 mm rectangle at 10,10 and factor
1.036269: cutcode Y went from 10000..30000 to 10363..31088 native units (height ratio
1.036250, the remainder is integer rounding at 2580.118 units/mm) and X stayed 10000..40000.

## Millimetres on the surface, not an unrolled bed

`rotary_cam.py` also offers `wrap_scale_y(diameter, bed_height)`, which maps the whole bed
height onto one circumference. We deliberately do not use it as the coordinate system. On
this Ruida (bed 609.6 x 406.4 mm) a chuck of 80 mm gives wrap = 251.3274 / 406.4 =
0.618424: a 30 mm logo would come off the cup at 18.55 mm while the canvas, the ruler and
the context panel all keep saying 30 mm. Flipping one checkbox in machine settings would
silently rescale every Y in every job by a third. Worse, its denominator is the *bed
height* — a property of the machine that has nothing to do with the workpiece.

So Y millimetres stay surface millimetres and the scale is a *calibration*: 1.0 when the
Ruida's own rotary page already converts Y to rotation (and then anything else would be
double compensation), and a small correction when it does not. The circumference is kept as
a *check* — "does my design go round without overlapping itself" — and as a verb ("Fit to
circumference"), which sets a real height in real millimetres and leaves the canvas telling
the truth.

## What the scale does *not* reach

The fast time estimate (`Drawing._geometry_estimate`, the one the pre-flight shows) measures
the geometry in the tree, and the tree is never scaled. So with a rotary on, the clock is
off by the part of the path that runs along Y: for a factor of 1.036 that is at most 3.6% of
the burn time, and less in practice because X contributes nothing. The exact route
(`?exact=1`) does see it, because it measures the built plan — measured on a 30x20 mm
rectangle at factor 1.036269: 15.0 s with the rotary off and 14.7 s with it on,
deterministic over three runs each. That difference is the engine's own travel accounting,
not ours; what it proves is that the estimate is built on the scaled plan.

## Where the settings live

On the device service, under one JSON key, like the zero point and the saved positions
(`machine.py`). A rotary belongs to *this* machine — it is a thing bolted into that bed —
not to the browser you happen to be sitting at, and a service's settings survive a restart
without a migration of ours.
"""

import json
import threading
from contextlib import contextmanager

from meerk40t.rotary.rotary_cam import (
    calibrate_rotary_steps,
    circumference_mm,
    y_steps_factor,
)

from .edits import DesignError, _finite

# One key, one JSON blob. A rotary is one thing with one state; spreading it over eight
# device settings would let half of it save and the other half not.
ROTARY_KEY = "openkerf_rotary"

#: A chuck holds the object between centres and you know its diameter; a roller drives it
#: from below and what you can measure is the circumference (the rollers slip, so the
#: diameter does not predict it). Two words, because the number you have is different.
KINDS = ("chuck", "roller")

#: Where the Y factor comes from. `none` is 1.0 and is the right answer whenever the Ruida
#: controller already does the conversion itself.
SCALE_SOURCES = ("none", "manual", "steps")

# What we accept as a Y factor. A rotary calibration is a correction, not a resize: 0.5 is
# already a job that comes out half as tall, and anything beyond this range is a typo
# (a comma for a dot, steps/mm swapped) rather than a machine. Refusing it here costs one
# message; not refusing it costs a workpiece.
SCALE_MIN = 0.5
SCALE_MAX = 2.0

DEFAULTS = {
    "active": False,
    "kind": "chuck",
    "diameter_mm": 0.0,
    "circumference_mm": 0.0,
    "scale_source": "none",
    "manual_scale_y": 1.0,
    "flat_steps_per_mm": 0.0,
    "rotary_steps_per_mm": 0.0,
    "last_calibration": None,
}


class _Duck:
    """
    What `CutPlan.preprocess` reads. Three attributes, nothing else.

    Deliberately not the engine's `Rotary` class: that one is a service delegate with
    sixteen settings and console commands, and it cannot be constructed for a device its
    plugin never attached to.
    """

    __slots__ = ("active", "scale_x", "scale_y")

    def __init__(self, scale_y: float):
        self.active = True
        # X is untouched. Along the axis of the cylinder a millimetre is still a
        # millimetre; `length_scale_x` maps the bed width onto the object's length, which
        # is the unrolled-bed idea again and would shrink every job in the other direction
        # too.
        self.scale_x = 1.0
        self.scale_y = scale_y


class RotaryControl:
    def __init__(self, kernel):
        self.kernel = kernel
        # How many plans are being built with this scale right now, over all threads.
        # The cut-path preview builds in a thread of its own while a job can claim the
        # plan (commands.py), so two callers can be inside `applied` at once. Measured
        # before this counter, with the rotary on: a preview that started while a job
        # held the plan lock lost the duck the moment the job's `finally` removed it,
        # built its remaining phases unscaled, and cached that as the ready answer for a
        # rotary-on design — a picture of a job the machine does not burn. So the last
        # one out takes it away, not the first.
        self._depth = 0
        self._depth_lock = threading.Lock()

    # ------------------------------------------------------------------ state

    def _device(self):
        device = getattr(self.kernel, "device", None)
        if device is None:
            raise DesignError(
                "There is no machine selected, so there is no rotary to set up.",
                code="rotary.noMachine",
            )
        return device

    def settings(self) -> dict:
        """What is stored, filled out with the defaults. Never raises."""
        stored = dict(DEFAULTS)
        try:
            device = self._device()
        except DesignError:
            return stored
        try:
            device.setting(str, ROTARY_KEY, "")
            raw = getattr(device, ROTARY_KEY, "") or ""
            if raw:
                value = json.loads(raw)
                if isinstance(value, dict):
                    for key in DEFAULTS:
                        if key in value:
                            stored[key] = value[key]
        except Exception:
            # A half-written or hand-edited key is not a reason to make the whole machine
            # unusable; the rotary is then simply off, which is the safe state.
            return dict(DEFAULTS)
        stored["active"] = bool(stored["active"])
        if stored["kind"] not in KINDS:
            stored["kind"] = "chuck"
        if stored["scale_source"] not in SCALE_SOURCES:
            stored["scale_source"] = "none"
        return stored

    def scale_y(self, stored: dict | None = None) -> float:
        """
        The factor that goes into the plan.

        `steps` uses the engine's own `y_steps_factor`: flat steps/mm over rotary
        steps/mm, for a rotary whose motor is not the gantry's.
        """
        stored = stored if stored is not None else self.settings()
        source = stored["scale_source"]
        if source == "manual":
            return float(stored["manual_scale_y"] or 1.0)
        if source == "steps":
            return y_steps_factor(
                float(stored["flat_steps_per_mm"] or 0.0),
                float(stored["rotary_steps_per_mm"] or 0.0),
            )
        return 1.0

    def circumference(self, stored: dict | None = None) -> float:
        """
        How far it is once round, in millimetres.

        A chuck computes it from the diameter (the engine's `circumference_mm`); a roller
        carries the measured number itself.
        """
        stored = stored if stored is not None else self.settings()
        if stored["kind"] == "chuck":
            return circumference_mm(float(stored["diameter_mm"] or 0.0))
        return float(stored["circumference_mm"] or 0.0)

    def engine_rotary(self) -> bool:
        """
        Whether this device brings the engine's *own* rotary along (grbl, lhystudios, …).

        Then that one wins and we install nothing — the same rule as the rasteriser: what
        is already there is not overwritten. On a Ruida this is False, and that is exactly
        why this module exists.
        """
        try:
            device = self._device()
        except DesignError:
            return False
        existing = getattr(device, "rotary", None)
        return existing is not None and not isinstance(existing, _Duck)

    def state(self, work_height_mm: float | None = None) -> dict:
        """
        Everything a screen needs, in one answer.

        `work_height_mm` is the height of what is on the bed. Given, the answer says
        whether that goes round the object once without running into itself — the one
        question the circumference does answer.
        """
        stored = self.settings()
        scale = self.scale_y(stored)
        circumference = self.circumference(stored)
        state = {
            **stored,
            "circumference_mm": round(circumference, 4) if circumference else 0.0,
            "scale_y": round(scale, 6),
            # Reported so nobody has to infer it from the absence of a field: along the
            # axis nothing is scaled.
            "scale_x": 1.0,
            "engine_rotary": self.engine_rotary(),
        }
        if work_height_mm and stored["active"] and circumference > 0:
            burned = float(work_height_mm) * scale
            if burned > circumference:
                state["overlap"] = {
                    "work_mm": round(float(work_height_mm), 2),
                    "burns_mm": round(burned, 2),
                    "circumference_mm": round(circumference, 2),
                }
        return state

    # ----------------------------------------------------------------- writing

    def update(self, fields: dict) -> dict:
        """
        Change what was given and leave the rest. Refuses a state that cannot burn.

        Validation happens against the *merged* settings, not against the request: turning
        the rotary on without touching the diameter has to be refused just as hard as
        sending both in one call with the diameter empty.
        """
        stored = self.settings()
        merged = dict(stored)
        for key in DEFAULTS:
            if key in fields and key != "last_calibration":
                merged[key] = fields[key]

        if merged["kind"] not in KINDS:
            raise DesignError(
                "A rotary is either a chuck or a roller.", code="rotary.unknownKind"
            )
        if merged["scale_source"] not in SCALE_SOURCES:
            raise DesignError(
                "The Y scale comes from the two motors, from a number you fill in, "
                "or nowhere at all.",
                code="rotary.unknownScaleSource",
            )

        merged["active"] = bool(merged["active"])
        for key in (
            "diameter_mm",
            "circumference_mm",
            "flat_steps_per_mm",
            "rotary_steps_per_mm",
        ):
            merged[key] = round(_finite(merged[key] or 0.0, key), 4)
        # Six decimals, the same as a calibration writes. At four, pressing Save after
        # calibrating quietly turned 1.036269 into 1.0363 — measured on screen. Harmless
        # on one cup (0.008 mm over 250 mm), but a value that changes because you saved
        # the page you were looking at is a value you stop trusting.
        merged["manual_scale_y"] = round(_finite(merged["manual_scale_y"] or 1.0, "manual_scale_y"), 6)

        if merged["active"]:
            self._check_ready(merged)

        self._save(merged)
        return self.state()

    def _check_ready(self, merged: dict) -> None:
        """What has to be filled in before a rotary may be switched on."""
        if merged["kind"] == "chuck" and merged["diameter_mm"] <= 0:
            raise DesignError(
                "A chuck rotary needs the diameter of the object, measured with "
                "calipers.",
                code="rotary.needsDiameter",
            )
        if merged["kind"] == "roller" and merged["circumference_mm"] <= 0:
            raise DesignError(
                "A roller rotary needs the circumference of the object: mark a line, "
                "roll it round once, and measure.",
                code="rotary.needsCircumference",
            )
        if merged["scale_source"] == "steps" and (
            merged["flat_steps_per_mm"] <= 0 or merged["rotary_steps_per_mm"] <= 0
        ):
            raise DesignError(
                "Computing the Y scale from the motors needs both numbers: the steps per "
                "millimetre of the flat bed and of the rotary.",
                code="rotary.needsSteps",
            )
        scale = self.scale_y(merged)
        if not (SCALE_MIN <= scale <= SCALE_MAX):
            # Numbers measured per call keep their English sentence: a code alone cannot
            # carry them, and a translated sentence without them says less.
            raise DesignError(
                f"A Y scale of {scale:.4f} is not a calibration but a resize; "
                f"between {SCALE_MIN} and {SCALE_MAX} is what a rotary needs."
            )

    def calibrate(self, commanded_mm, measured_mm) -> dict:
        """
        "I burned a line meant to be 100 mm and I measured 96.5."

        The engine's own `calibrate_rotary_steps` turns that into the factor, starting from
        the factor that is set now — so calibrating twice keeps converging instead of
        starting over. 100 commanded and 96.5 measured from 1.0 gives 1.036269.

        The result is stored as the manual factor, because that is what it is: a number
        that came off a workpiece and not out of a motor's data sheet.
        """
        commanded = _finite(commanded_mm, "commanded_mm")
        measured = _finite(measured_mm, "measured_mm")
        if commanded <= 0 or measured <= 0:
            raise DesignError(
                "Calibrating needs both lengths: what you asked the machine for and what "
                "you measured on the object.",
                code="rotary.needsMeasurement",
            )
        stored = self.settings()
        factor = calibrate_rotary_steps(self.scale_y(stored), commanded, measured)
        if not (SCALE_MIN <= factor <= SCALE_MAX):
            raise DesignError(
                f"{commanded:g} mm commanded and {measured:g} mm measured gives a factor "
                f"of {factor:.4f}. That is not a calibration — check whether you measured "
                f"the right line, and whether the rotary is set up in the controller "
                f"as well."
            )
        merged = dict(stored)
        merged["scale_source"] = "manual"
        merged["manual_scale_y"] = round(factor, 6)
        merged["last_calibration"] = {
            "commanded_mm": round(commanded, 3),
            "measured_mm": round(measured, 3),
            "factor": round(factor, 6),
        }
        self._save(merged)
        return self.state()

    def _save(self, merged: dict) -> None:
        """
        On the device, and straight into its persistent settings.

        Deliberately not only the attribute: the engine writes a service's attributes to
        the config file at *shutdown*, and a headless server that is killed never gets
        there. Measured in a test kernel: after setting the attribute alone,
        `read_persistent(str, device.path, ROTARY_KEY)` was still empty. So the value is
        written explicitly and the file flushed — a rotary you have to set up again after
        every restart is one you will forget to set up once, and then a flat job goes onto
        a cup.
        """
        device = self._device()
        raw = json.dumps(merged)
        device.setting(str, ROTARY_KEY, "")
        setattr(device, ROTARY_KEY, raw)
        try:
            device.write_persistent(ROTARY_KEY, raw)
            self.kernel.write_configuration()
        except Exception:  # pragma: no cover - the engine must not break us
            pass

    # ------------------------------------------------------- into the plan

    @contextmanager
    def applied(self):
        """
        The scale, for as long as the plan is being built.

        Yields the factor that was installed, or None when nothing was installed. Removed
        in a `finally`, like `Drawing.shifted`: a device that keeps a rotary attribute
        after a failed plan would scale the next job as well, and nothing on screen would
        say so.
        """
        stored = self.settings()
        if not stored["active"]:
            # Off means off, and that has to hold even while somebody else is mid-build.
            # The preview builds in a thread of its own; switch the rotary off during that
            # build and its duck is still hanging on the device when a job starts, reads
            # "off", installs nothing — and gets scaled anyway by the duck that is still
            # there. That costs a workpiece, in the direction nobody checks. So a caller
            # that reads "off" takes any duck away rather than stepping around it; the
            # preview in flight then finishes unscaled, and its answer is thrown away by
            # the fingerprint, which counts the rotary scale (cutpath.py).
            try:
                device = self._device()
            except DesignError:
                yield None
                return
            with self._depth_lock:
                if isinstance(getattr(device, "rotary", None), _Duck):
                    del device.rotary
                    self._depth = 0
            yield None
            return
        try:
            device = self._device()
        except DesignError:
            yield None
            return
        existing = getattr(device, "rotary", None)
        if existing is not None and not isinstance(existing, _Duck):
            # The device brings its own rotary (grbl and family). That one has the user's
            # settings from the engine's own panel; ours would fight it. Same rule as the
            # rasteriser: what is there wins.
            yield None
            return
        scale = self.scale_y(stored)
        with self._depth_lock:
            if self._depth <= 0 or not isinstance(getattr(device, "rotary", None), _Duck):
                device.rotary = _Duck(scale)
                self._depth = 1
            else:
                self._depth += 1
        try:
            yield scale
        finally:
            with self._depth_lock:
                self._depth -= 1
                if self._depth <= 0:
                    self._depth = 0
                    try:
                        if isinstance(getattr(device, "rotary", None), _Duck):
                            del device.rotary
                    except AttributeError:  # pragma: no cover - nothing to clean up
                        pass

    # ---------------------------------------------------------------- safety

    def homing_refusal(self) -> str | None:
        """
        Why homing is dangerous right now, or None.

        With a chuck bolted in, homing Y drives the head into it — the rotary stands where
        the gantry wants to go. The engine has no guard for it on a Ruida (the one it does
        have, `rotary.py`'s homing hook, is in the service that never attaches), so this is
        ours, and it sits in the API and not only in the interface: a second tab, a phone
        or a curl command comes straight past a greyed-out button.
        """
        if not self.settings()["active"]:
            return None
        return (
            "The rotary is switched on. Homing drives the head over the bed and into "
            "the rotary. Take the rotary out first, or confirm that it is clear."
        )
