"""
The cut path before burning: what the machine does, in what order, and when.

The engine can already answer this — the cut plan *is* the answer — but only as
live objects inside the kernel, and only after a build that is the most expensive
thing this API does. So this module does three things and nothing else: it decides
whether a build is worth it, it builds one at a time in the background while the
rest of the app stays usable, and it turns the result into plain data before
anything else can touch the plan.

Three facts shape every decision here, all of them measured.

1. **The plan is not free.** On this Mac, with squares of 6x6 mm on a 9 mm pitch:
   100 shapes build in 0.05 s, 400 in 0.50 s, 960 in 2.54 s, and 400 shapes over
   eight passes in 2.71 s. Almost all of it is one phase — `optimize` — which is
   0.02 s at 100 shapes and 2.26 s at 960. The growth is quadratic in the number
   of cut objects, exactly as CLAUDE.md records for the estimate.
2. **The plan is kernel-global.** `/api/job/start` begins with `plan clear`, so a
   preview build and a starting job cannot share it. Whoever is burning wins:
   `CommandRunner.preview_plan` gives way *between* phases (see there). It cannot give
   way inside one, and `optimize` is a single console call, so a start that arrives
   during it waits for it. Measured on 990 squares (3,960 planned segments, a 3.2 s
   build): a start fired 0, 200 and 600 ms after the build began answered 200 after
   3.23, 3.05 and 2.50 s, and in all three the preview still finished `ready` rather
   than giving way. So the honest number is **two to three and a half seconds at the
   ceiling**, and giving way is the uncommon outcome. What the yielding does buy is
   that no start waits for a whole build *and* an optimize, and that the window
   recovers by itself when it does lose the plan.
3. **The answer is big.** Serialised, a step costs about 130 bytes: 80 steps is
   9.7 KiB, 800 is 100 KiB, 7,680 is 1.0 MB. Turning the plan into data is free
   (0.01 s for 7,680 steps); shipping it is not.

Hence the two ceilings. The first is checked *before* building, from the geometry:
segments x passes, which is what the plan will roughly hold. The second is checked
after, on the real step count.
"""

import hashlib
import threading
import time

from .commands import PlanYielded

#: What we allow ourselves to plan, in segments x passes counted on the design.
#:
#: 8,000 lets through the two heaviest designs we measured that still answer in
#: about two and a half seconds: 960 squares on one pass (3,840 segments, 2.54 s,
#: 7,680 steps, 1.0 MB) and 200 squares over eight passes (6,400, 0.72 s, 7,200
#: steps, 1.0 MB). It refuses 400 squares over eight passes (12,800 segments,
#: 2.71 s but 14,400 steps and 2.0 MB) — that is where the answer, not the build,
#: becomes the problem.
#:
#: What the refusal says is measured on the smallest design that trips it: 2,025 squares
#: of 4x3 mm, 8,100 segments, one pass. The plan builds in 6.61 s and the answer is
#: 1,058,900 bytes over 8,100 steps (131 bytes a step). So the sentence promises "seconds
#: to a minute of work, megabytes of answer" — it used to say minutes and tens of
#: megabytes, which overstated both by about an order of magnitude at the boundary.
PLANNED_SEGMENT_LIMIT = 8000

#: What we allow ourselves to send. At ~130 bytes a step this is about 2.6 MB, and
#: it is the backstop for a design whose segment count lies about its plan (a
#: hatch effect multiplies inside the plan, not in the tree).
STEP_LIMIT = 20000

#: How long a "the machine took the plan" verdict stands before a poll tries
#: again. Long enough that a start is not raced, short enough that the window
#: recovers by itself.
BLOCKED_SECONDS = 5.0

#: Settings on the root that change the plan without changing the design. Read out
#: of `core/cutplan.py` and `core/planner.py`; without them the cached answer would
#: survive somebody switching "cut inner shapes first" off.
OPT_SETTINGS = (
    "opt_closed_distance",
    "opt_complete_subpaths",
    "opt_effect_combine",
    "opt_effect_optimize",
    "opt_inner_first",
    "opt_inner_tolerance",
    "opt_inners_grouped",
    "opt_jog_minimum",
    "opt_merge_ops",
    "opt_merge_passes",
    "opt_nearest_neighbor",
    "opt_rapid_between",
    "opt_raster_opt_margin",
    "opt_raster_optimisation",
    "opt_reduce_details",
    "opt_reduce_tolerance",
    "opt_reduce_travel",
    "opt_start_from_position",
    "opt_stitch_tolerance",
    "opt_stitching",
)

#: What a layer carries that reaches the plan. Anything not in here cannot change
#: the path, so a cached answer stays valid across it.
OP_FIELDS = (
    "type",
    "output",
    "speed",
    "power",
    "passes",
    "implicit_passes",
    "passes_custom",
    "dpi",
    "z_step_mm",
    "overscan",
    "raster_direction",
    "raster_preference_left",
    "raster_preference_top",
    "bidirectional",
    "kerf",
    "dot_length",
    "dwell_time",
    "frequency",
    "acceleration",
    "rapid_speed",
    "hatch_distance",
    "hatch_angle",
    "stopop",
    "coolant",
)

#: The classes the plan can hold, and what each one *is* to somebody watching.
#: Everything not named here is drawn as a straight burn from start to end and
#: says so (`approx`), because guessing at a shape we do not know is worse than
#: admitting the line is a chord.
KINDS = {
    "LineCut": "cut",
    "CubicCut": "cut",
    "QuadCut": "cut",
    "RasterCut": "raster",
    "PlotCut": "cut",
    "DwellCut": "dot",
    "GotoCut": "move",
    "HomeCut": "move",
    "WaitCut": "wait",
    "InputCut": "wait",
    "OutputCut": "wait",
}


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class CutPath:
    """
    The ordered path of the current design, cached against the design itself.

    One build at a time, in a thread of its own, because a build takes seconds and
    an HTTP request that takes seconds is a request the browser gives up on.
    """

    def __init__(self, kernel, runner, drawing):
        self.kernel = kernel
        self.runner = runner
        self.drawing = drawing
        self._lock = threading.Lock()
        self._ready: dict | None = None
        self._building: str | None = None
        self._started = 0.0
        self._failed: tuple[str, str] | None = None
        self._blocked: tuple[str, float] | None = None

    # ------------------------------------------------------------------ state

    def state(self, origin=None) -> dict:
        """
        The path, or an honest word about why it is not there yet.

        Never blocks: everything that costs time happens in the build thread. The
        caller polls, exactly as the pre-flight polls its estimate.
        """
        key, planned = self.signature(origin)
        with self._lock:
            if self._ready is not None and self._ready.get("fingerprint") == key:
                return self._ready
            if self._failed is not None and self._failed[0] == key:
                return {"state": "failed", "fingerprint": key, "message": self._failed[1]}
            if self._blocked is not None:
                blocked_key, since = self._blocked
                if blocked_key == key and time.monotonic() - since < BLOCKED_SECONDS:
                    return {"state": "busy", "fingerprint": key}
                self._blocked = None
            if self._building is not None:
                # Somebody's build is running. If it is not ours, the next poll
                # starts ours — two builds cannot share one kernel-global plan.
                return {
                    "state": "building",
                    "fingerprint": key,
                    "for_this_design": self._building == key,
                    "elapsed_s": round(time.monotonic() - self._started, 1),
                }
            if not planned:
                return {"state": "empty", "fingerprint": key}
            if planned > PLANNED_SEGMENT_LIMIT:
                return {
                    "state": "too_big",
                    "fingerprint": key,
                    "planned_segments": planned,
                    "limit": PLANNED_SEGMENT_LIMIT,
                }
            self._building = key
            self._started = time.monotonic()
        thread = threading.Thread(
            target=self._build, args=(key, origin), name="openkerf-cutpath", daemon=True
        )
        thread.start()
        return {
            "state": "building",
            "fingerprint": key,
            "for_this_design": True,
            "elapsed_s": 0.0,
        }

    def forget(self) -> None:
        """Throw the cached answer away — for a test, and for shutting down."""
        with self._lock:
            self._ready = None
            self._failed = None
            self._blocked = None

    # ------------------------------------------------------------ fingerprint

    def signature(self, origin=None) -> tuple[str, int]:
        """
        What this design would plan, as a key and as a weight.

        The key has to change on everything that moves a line and on nothing else,
        so it is taken from the geometry itself and not from a change counter: undo,
        a reload and an import that puts a shape back where it was must all land on
        the same answer. The weight is the segment count times the passes — the
        cheapest honest guess at how big the plan becomes, and the only thing we
        have *before* paying for it.

        Measured on 960 squares: 0.017 s for both together, against 2.54 s for the
        plan. That ratio is the whole reason this exists.
        """
        digest = hashlib.blake2b(digest_size=16)
        planned = 0
        elements = self.kernel.elements
        # Without this every shape that came in from an SVG carries an empty id, and
        # then the path cannot say which layer a step belongs to.
        elements.validate_ids()
        device = getattr(self.kernel, "device", None)
        digest.update(str(getattr(device, "path", "")).encode())
        digest.update(repr(self.drawing.bed_mm()).encode())
        digest.update(
            repr(
                (
                    round(_number((origin or {}).get("x_mm")), 4),
                    round(_number((origin or {}).get("y_mm")), 4),
                )
            ).encode()
        )
        # The rotary scales Y while the plan is built (rotary.py), so switching it on or
        # off moves every line in this window without touching a single shape. Measured
        # before this was in the key: with a factor of 1.036269 the path of a rectangle at
        # y 10..30 mm came out at 10.36..31.09 mm, and it *stayed* there after the rotary
        # was switched off — the preview then showed a job the machine no longer burns.
        # And on the scale that is really *installed*, not the one that is stored. On a
        # lihuiyu (which brings MeerK40t's own rotary, so ours installs nothing) switching
        # ours on changed the key while not one coordinate moved — y stayed 10.01..30 over
        # four states. On a Ruida, off/on/off gave three different keys instead of two,
        # because the stored factor (1.036269) travelled in the key of the "off" state as
        # well. At the ceiling that is a 2.25 s rebuild for a byte-identical answer.
        rotary = getattr(self.runner, "rotary", None)
        if rotary is not None:
            digest.update(f"rotary={self._rotary_scale(rotary)}".encode())

        root = self.kernel.root
        for name in OPT_SETTINGS:
            digest.update(f"{name}={getattr(root, name, None)}".encode())

        for operation in elements.ops():
            kind = str(getattr(operation, "type", ""))
            if not kind.startswith("op "):
                continue
            digest.update(b"|op|")
            digest.update(str(getattr(operation, "id", None)).encode())
            for field in OP_FIELDS:
                digest.update(f"{field}={getattr(operation, field, None)}".encode())
            if not getattr(operation, "output", True):
                continue
            passes = max(1, int(_number(getattr(operation, "implicit_passes", 1), 1) or 1))
            for node in self.drawing._burnable(operation):
                digest.update(b"|el|")
                digest.update(str(getattr(node, "id", None)).encode())
                planned += passes * self._sign_element(digest, node)
        return digest.hexdigest(), planned

    def _rotary_scale(self, rotary) -> float:
        """
        The Y scale the plan will actually be built with.

        1.0 whenever nothing of ours is installed — the rotary switched off, or a device
        that owns its own rotary (grbl and family; `RotaryControl.applied` steps aside for
        it). Exactly the same three questions `applied` asks, so the key cannot say a
        state is different when the plan comes out the same.
        """
        try:
            stored = rotary.settings()
            if not stored.get("active"):
                return 1.0
            if rotary.engine_rotary():
                return 1.0
            return round(rotary.scale_y(stored), 6)
        except Exception:
            # A rotary layer that cannot answer is a rotary that does not scale; the plan
            # then comes out unscaled too.
            return 1.0

    def _sign_element(self, digest, node) -> int:
        """Sign one shape into the digest; returns how many segments it holds."""
        if str(getattr(node, "type", "")) == "elem image":
            # An image is one raster cut however many pixels it has. Its matrix and
            # its adjustments are what move it; hashing the pixels of a 24 MP photo
            # on every poll is not worth the one bit it adds.
            digest.update(str(getattr(node, "matrix", "")).encode())
            digest.update(repr(getattr(node, "bounds", None)).encode())
            digest.update(f"dpi={getattr(node, 'dpi', None)}".encode())
            image = getattr(node, "active_image", None) or getattr(node, "image", None)
            digest.update(repr(getattr(image, "size", None)).encode())
            digest.update(f"altered={getattr(node, 'altered', None)}".encode())
            return 1
        try:
            geometry = node.as_geometry()
            count = int(geometry.index)
            digest.update(geometry.segments[:count].tobytes())
            return max(1, count)
        except Exception:
            # A node without geometry still has to be in the key: its matrix moves
            # whatever the engine does make of it.
            digest.update(str(getattr(node, "matrix", "")).encode())
            digest.update(repr(getattr(node, "bounds", None)).encode())
            return 1

    # ---------------------------------------------------------------- building

    def _build(self, key: str, origin) -> None:
        started = time.monotonic()
        try:
            # The zero point moves the work into the machine (gap J12), so the
            # preview has to see it too — otherwise it draws a path beside the one
            # the machine walks. Exactly what `/api/job/start` does.
            with self.drawing.shifted(origin):
                payload = self.runner.preview_plan(self.harvest)
            payload["state"] = "ready"
            payload["fingerprint"] = key
            # The whole build, not only the harvesting: what the window reports is
            # what the reader waited for. The harvest on its own is 0.003 s and
            # reporting that read as "took 0 seconds" after a wait of a second.
            payload["built_in_s"] = round(time.monotonic() - started, 2)
            with self._lock:
                self._ready = payload
                self._failed = None
                self._blocked = None
        except PlanYielded:
            with self._lock:
                self._blocked = (key, time.monotonic())
        except Exception as error:  # pragma: no cover - the engine must not hang us
            with self._lock:
                self._failed = (key, f"{type(error).__name__}: {error}")
        finally:
            with self._lock:
                self._building = None

    # --------------------------------------------------------------- harvest

    def harvest(self, plan) -> dict:
        """
        The built plan as plain data, while the lock is still held.

        Everything here is a copy: nothing that leaves this method points into the
        plan, because `plan clear` follows immediately and the next job wipes it
        anyway.

        The clock is the engine's own arithmetic (`CutCode.provide_statistics`),
        not a second model of ours. It costs 0.007 s for 7,680 items — a free ride
        on top of the build, and the only way for the preview to agree with the
        estimate beside it.
        """
        from meerk40t.core.cutcode.cutcode import CutCode
        from meerk40t.core.units import UNITS_PER_MM

        started = time.monotonic()
        names = self._layer_names()
        steps: list[dict] = []
        used: dict[str, dict] = {}
        clock = 0.0
        cut_units = 0.0
        travel_units = 0.0
        a, b, c, d, e, f = self._back_to_scene()
        per_mm = float(UNITS_PER_MM)
        # A length has no offset, so it does not go through the same sum as a point:
        # it scales by the square root of the determinant. On a lihuiyu that is the
        # difference between 46 mm and 3,013 mm of cutting — measured, and 46 mm was
        # the kind of wrong number nobody questions.
        length_mm = (abs(a * d - b * c) ** 0.5) / per_mm

        def mm(x, y) -> tuple[float, float]:
            """One point from the machine's own coordinates to millimetres on the bed."""
            return (
                round((a * x + c * y + e) / per_mm, 2),
                round((b * x + d * y + f) / per_mm, 2),
            )

        for chunk in getattr(plan, "plan", []) or []:
            if not isinstance(chunk, CutCode):
                # A console step between the passes — that is where our Z drop
                # lives (`CommandRunner._with_passes`). It burns nothing and takes
                # no time we can know, but leaving it out would show a path the
                # machine does not walk.
                command = getattr(chunk, "command", None)
                if command:
                    steps.append({"k": "console", "cmd": str(command), "t0": round(clock, 2),
                                  "t1": round(clock, 2), "t2": round(clock, 2)})
                continue
            flat = CutCode(chunk.flat())
            items = list(flat.flat())
            if not items:
                continue
            stats = flat.provide_statistics(include_start=False)
            for index, item in enumerate(items):
                line = stats[index] if index < len(stats) else stats[-1]
                step = self._step(item, line, clock, mm, names, used)
                if step is not None:
                    steps.append(step)
            last = stats[-1]
            cut_units += _number(last.get("total_distance_cut"))
            travel_units += _number(last.get("total_distance_travel"))
            clock += _number(last.get("time_at_end_of_burn"))

        limited = len(steps) > STEP_LIMIT
        payload = {
            # Overwritten in `_build` with the whole build; this is the harvest alone,
            # and it is here so a caller of `harvest` on its own still gets a number.
            "built_in_s": round(time.monotonic() - started, 3),
            "seconds": round(clock, 2),
            "cut_mm": round(cut_units * length_mm, 1),
            "travel_mm": round(travel_units * length_mm, 1),
            "steps_total": len(steps),
            "steps": [] if limited else steps,
            "limited": limited,
            "step_limit": STEP_LIMIT,
            "layers": list(used.values()),
        }
        return payload

    def _back_to_scene(self):
        """
        The device matrix, inverted: native units back to scene units.

        This is not a detail — it is the difference between a picture of your work
        and a picture 65 times too small. `plan preprocess` converts the scene into
        **device** coordinates, so what comes out of the plan is in the machine's
        own units, with the machine's own flip and margin in it. On the dummy device
        that happens to be a no-op, which is exactly why it has to be measured on a
        real one: on the lihuiyu (1,000 steps to the inch) a rectangle at 15 mm came
        out of the plan at 0.23, and it looked like a plausible small drawing.

        Same route the engine's own simulation window takes
        (`gui/simulation.py:2328`: `~scene.context.device.view.matrix`). The six
        coefficients are pulled out once instead of transforming point by point:
        that is two multiplications per point instead of a Python matrix call, and
        at the ceiling there are 30,000 points.
        """
        try:
            matrix = ~self.kernel.device.view.matrix
            return (
                float(matrix.a),
                float(matrix.b),
                float(matrix.c),
                float(matrix.d),
                float(matrix.e),
                float(matrix.f),
            )
        except Exception:
            # No device, or a device without a view: then the plan is already in
            # scene units and there is nothing to undo.
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def _step(self, item, line, clock: float, mm, names, used) -> dict | None:
        kind = KINDS.get(type(item).__name__)
        settings = getattr(item, "settings", None)
        settings = settings if isinstance(settings, dict) else {}
        layer = settings.get("id")
        if layer is not None:
            layer = str(layer)
            if layer not in used:
                known = names.get(layer, {})
                used[layer] = {
                    "id": layer,
                    "label": known.get("label") or layer,
                    "color": known.get("color"),
                    "type": known.get("type"),
                    "speed_mm_s": _number(settings.get("speed"), 0.0) or None,
                    # Power runs 0-1000 in the engine; a laser operator reads percent.
                    "power_percent": round(_number(settings.get("power")) / 10, 1) or None,
                }
        step: dict = {
            "k": kind or "cut",
            "op": layer,
            "t0": round(clock + _number(line.get("time_at_start")), 2),
            "t1": round(clock + _number(line.get("time_at_end_of_travel")), 2),
            "t2": round(clock + _number(line.get("time_at_end_of_burn")), 2),
        }
        if kind == "raster":
            # `RasterCut.left()/upper()` are device units but `right()/lower()` add
            # *pixels* to them (rastercut.py:102-112). Measured on a filled 40x30 mm
            # rectangle at x=100 mm: right() says 100.11 mm where the image ends at
            # 140.24 mm. So the box is computed from the step size, which is the
            # number the plotter itself walks on.
            plot = getattr(item, "plot", None)
            left = _number(getattr(plot, "offset_x", getattr(item, "offset_x", 0)))
            upper = _number(getattr(plot, "offset_y", getattr(item, "offset_y", 0)))
            right = left + _number(getattr(item, "width")) * _number(getattr(item, "step_x"))
            lower = upper + _number(getattr(item, "height")) * _number(getattr(item, "step_y"))
            # Both corners through the matrix and then sorted: the device flip can
            # turn "upper left" into "lower right", and a rectangle with a negative
            # width draws nothing at all.
            ax, ay = mm(left, upper)
            bx, by = mm(right, lower)
            step.update({
                "x0": min(ax, bx),
                "y0": min(ay, by),
                "w": round(abs(bx - ax), 2),
                "h": round(abs(by - ay), 2),
            })
            start, end = getattr(item, "start", None), getattr(item, "end", None)
            if start is not None and end is not None:
                sx, sy = mm(start[0], start[1])
                ex, ey = mm(end[0], end[1])
                step.update({"sx": sx, "sy": sy, "ex": ex, "ey": ey})
            return step
        start, end = getattr(item, "start", None), getattr(item, "end", None)
        if start is None or end is None:
            return None
        step["x0"], step["y0"] = mm(start[0], start[1])
        step["x1"], step["y1"] = mm(end[0], end[1])
        name = type(item).__name__
        if name == "CubicCut":
            c1, c2 = item.c1(), item.c2()
            step["c"] = [*mm(c1[0], c1[1]), *mm(c2[0], c2[1])]
        elif name == "QuadCut":
            control = item.c()
            step["c"] = list(mm(control[0], control[1]))
        elif kind is None:
            # Drawn as a chord, and it says so, so nobody reads a straight line as
            # a promise.
            step["approx"] = True
        if getattr(item, "first", False):
            # The start of a subpath: this is where the order becomes visible. The
            # window numbers these, and that is the answer to "does it cut inside
            # before outside".
            step["f"] = True
        return step

    def _layer_names(self) -> dict:
        """
        Layer id to the name and colour the rest of the app uses.

        Taken from the *design* tree and not from the plan: the plan's copies carry
        a label template ("Cut ({percent}, {speed}mm/s)") and no user name at all.
        The id is the same on both sides, so the window can put the same word beside
        a step that the layer list puts on its row.
        """
        from .design import operation_label

        found = {}
        try:
            operations = list(self.kernel.elements.ops())
        except Exception:  # pragma: no cover - a tree without an ops branch
            return found
        for operation in operations:
            identifier = getattr(operation, "id", None)
            if identifier is None:
                continue
            colour = getattr(operation, "color", None)
            found[str(identifier)] = {
                "label": operation_label(operation),
                "color": str(colour) if colour is not None else None,
                "type": str(getattr(operation, "type", "")),
            }
        return found
