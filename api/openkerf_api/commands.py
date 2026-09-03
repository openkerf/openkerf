"""
Serialised console execution and device capability detection.

Every write action goes through here. Console commands mutate shared kernel
state, so they are executed one at a time under a lock — HTTP requests arrive
on uvicorn worker threads and must not interleave mid-pipeline.
"""

import re
import threading
from contextlib import contextmanager

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# The console reports failures as plain text on the channel rather than raising,
# so these are the markers that tell us a command did not take effect.
ERROR_MARKERS = (
    "is not a registered command",
    "Syntax Error",
    "Bad provider",
    "did not exist",
    # The engine reports an unreadable file only on the console channel and then returns
    # neatly. Without this marker HTTP 200 {"ok":true} came out of a file that was never
    # read — the user sees an empty bed and no reason at all why.
    "File is Malformed",
)

# The full job pipeline in one line: console commands chain through their
# input/output types only within a single line (verified against the engine).
#
# `clear` is not there for decoration. `plan copy` *adds* to the plan that is already there
# (planner.py:593, `data.append`), and the plan is kernel-global and stays after spooling.
# So without clear the second start carried the same work twice, the third three times, and
# the time estimate grew by a factor per press of the button — measured: 1701 s, 3364 s,
# 5027 s for the same design. That is the source of "150:40:23 for the same work" from gap
# B1: not one wrong formula but eleven copies of the same job in one plan. Worse than the
# number is what would have been burned: the machine cuts over every shape just as often.
PLAN_AND_SPOOL = "plan clear copy preprocess validate blob preopt optimize spool"

# The same pipeline, but cut in two so that something can be put in the plan between
# `copy` and the rest. Only used when a layer carries a Z step; without that the line above
# stays literally what it was.
PLAN_COPY = "plan clear copy"
PLAN_REST = "plan preprocess validate blob preopt optimize spool"
# The same route in two pieces, for mutators that need the cutcode.
PLAN_BLOB = "plan preprocess validate blob preopt optimize"
PLAN_SPOOL = "plan spool"


#: The plan pipeline in phases, for a build that has to be interruptible.
#:
#: Cut into pieces on purpose: each line starts with `plan`, which fetches the
#: kernel-global plan again, so the phases chain through it and not through the
#: console's input/output types. Measured identical to the one-liner (same cut
#: object count on 10, 100, 200, 400 and 960 shapes). What the pieces buy is the
#: gap between them: a job that wants the plan gets it there instead of after the
#: whole build. Measured per phase at 960 squares: copy 0.006 s, preprocess
#: 0.008 s, validate 0.000 s, blob 0.260 s, preopt 0.000 s, optimize 2.261 s.
PREVIEW_PHASES = ("plan preprocess", "plan validate", "plan blob")


class PlanYielded(RuntimeError):
    """A preview build gave the plan up because a job claimed it."""


class CommandError(RuntimeError):
    def __init__(self, command, output):
        super().__init__(f"Command failed: {command}")
        self.command = command
        self.output = output


class CommandRunner:
    def __init__(self, kernel, document=None):
        self.kernel = kernel
        self._lock = threading.Lock()
        # The cut plan is kernel-global: `plan copy` adds to whatever is there and
        # `plan clear` throws away whatever somebody else was reading. So a whole
        # pipeline needs a lock of its own, above the per-line one — otherwise two
        # pipelines interleave and both get half a plan.
        self._plan_lock = threading.RLock()
        # How often a real job has claimed the plan. A preview build watches this
        # number and gives way when it moves; it does not need to know who moved it.
        self._plan_claims = 0
        # Set by the server; every write command makes the design dirty.
        self.document = document
        # Set by the server as well: the rotary, which scales Y while the plan is being
        # built (see rotary.py). None means "no rotary layer at all", which is what a test
        # or a script that builds a runner of its own gets.
        self.rotary = None

    def run(self, command: str) -> list[str]:
        """Execute one console line and return its output. Raises CommandError."""
        captured: list[str] = []
        channel = self.kernel.channel("console")

        with self._lock:
            channel.watch(captured.append)
            try:
                self.kernel.console(command + "\n")
            finally:
                channel.unwatch(captured.append)

        if self.document is not None:
            self.document.touch(command)
        output = [ANSI.sub("", str(line)).strip() for line in captured]
        output = [line for line in output if line]
        for line in output:
            if any(marker in line for marker in ERROR_MARKERS):
                raise CommandError(command, output)
        return output

    def supports(self, name: str, input_type: str = "None") -> bool:
        """
        Whether the active device provides this console command.

        `find` searches the active services first and then the kernel — exactly
        what the console parser does — so this reflects the device that is
        actually selected. pause/resume/estop are registered by device services
        (Ruida and Lihuiyu both do), not by the kernel, so availability changes
        when the user switches device; the dummy device has none of them.
        """
        return any(True for _ in self.kernel.find("command", input_type, f"{name}$"))

    def capabilities(self) -> dict:
        return {
            "start": self.supports("plan") and self.supports("spool"),
            "pause": self.supports("pause"),
            "resume": self.supports("resume"),
            "stop": self.supports("estop") or self.supports("abort"),
            "clear_queue": self.supports("spool"),
            "load": self.supports("load"),
        }

    # --------------------------------------------------------------- actions

    def load_file(self, path: str) -> list[str]:
        """
        Reading a file in, and being honest when that does not work.

        The console reports a failure as text on the channel and then simply returns, so
        without this check "succeeded" came out of a file that was never read. Two things can
        go wrong: the file is unreadable (the engine shouts "File is Malformed"), or it is
        readable but empty — an SVG without shapes loads without complaint and produces an
        empty bed. Both get their own sentence here, in the language of somebody who wanted to
        open a drawing.
        """
        name = path.rsplit("/", 1)[-1]
        voor = self._element_count()
        try:
            output = self.run(f'load "{path}"')
        except CommandError as e:
            raise CommandError(
                "load",
                [
                    f"“{name}” cannot be read. The file is damaged or it is not a "
                    "drawing — check that you have the right export (SVG, DXF, PNG "
                    "or an RD file).",
                ],
            ) from e
        if self._element_count() <= voor:
            raise CommandError(
                "load",
                [
                    f"There is no drawing in “{name}”. The file was read but holds "
                    "no shapes — with an SVG from a drawing program that is usually "
                    "because everything is on a hidden layer.",
                ],
            )
        return output

    def _element_count(self) -> int:
        """How many shapes are in the tree; 0 when the engine does not co-operate."""
        try:
            return sum(1 for _ in self.kernel.elements.elems())
        except Exception:
            return 0

    def start_job(self, name: str | None = None, mutators=()) -> list[str]:
        """
        Building the plan and sending it to the spooler.

        First look at *whether* there is anything to burn. An empty design ran cheerfully
        through here and reported "succeeded": the user presses start, the app says yes, and
        nothing happens at the machine. That is the most annoying kind of mistake — you go and
        state beside it waiting.

        `mutators` are operations on the copied plan (tiles, Z steps). See `_plan_and_spool`.
        """
        burnable = self._require_something_to_burn()
        output = self._plan_and_spool(mutators)
        self._name_job(name, burnable)
        return output

    def _require_something_to_burn(self) -> int:
        """De telling die `start_job` ook doet, apart zodat beide hem lezen."""
        from .edits import DesignError

        burnable = 0
        for operation in self.kernel.elements.ops():
            if not str(operation.type).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            burnable += sum(1 for child in operation.children)
        if not burnable:
            raise DesignError(
                "There is nothing ready to burn. Draw or load something, and put it "
                "in a layer that burns — a layer with 'burn along' off is skipped.",
                code="job.nothingToBurn",
            )
        return burnable

    def build_job_bytes(self, mutators=()) -> bytes:
        """
        De job als bestand, zonder hem te spoolen.

        Dezelfde pijplijn als `start_job` tot en met `optimize`, en dan niet `spool`
        maar de RuidaDriver zelf: die schrijft zijn opdrachten in `controller.job`, een
        `RDJob`, en `get_contents()` is precies de inhoud van een `.rd`-bestand —
        inclusief de staart met SET_FILE_SUM en END_OF_FILE uit `write_tail`.

        Waarom niet `save_job` uit de engine: die zet `controller.write` op `f.write` en
        voert de RDJob daarna uit, terwijl de bytes juist in de buffer belanden.
        Gemeten (CLAUDE.md): 4 bytes in het bestand, 623 in de buffer.

        De mutators zijn dezelfde als bij een gewone job — tegels, Z-stappen,
        series — inclusief `_share_pass_settings` erna. Zonder die laatste krijgt elke
        pass zijn eigen RD-laag en zegt de controller "file invalid".
        """
        from meerk40t.core.laserjob import LaserJob

        device = getattr(self.kernel, "device", None)
        driver = getattr(device, "driver", None)
        controller = getattr(driver, "controller", None)
        if controller is None or not hasattr(controller, "job"):
            raise DesignError(
                "This machine does not keep files in memory; that is a Ruida thing.",
                code="upload.notRuida",
            )

        self._require_something_to_burn()
        with self.claim_plan():
            with self.rotary_applied():
                self._plan_without_spooling(mutators)
                plan = self.kernel.planner.get_or_make_plan("0")
                steps = [step for step in plan.plan if hasattr(step, "__iter__")]
                job = LaserJob("upload", list(steps), driver=driver)
                # De buffer leegmaken vóór de job: wat er nog in staat is van een
                # eerdere job en zou er zo tussen komen te staan.
                controller.job.buffer.clear()
                driver.job_start(job)
                while not job.execute():
                    pass
                driver.job_finish(job)
                return controller.job.get_contents()

    def _plan_without_spooling(self, mutators=()) -> list[str]:
        """
        `_plan_and_spool_locked`, maar zonder de laatste stap.

        Zelfde `opt_merge_ops`/`opt_merge_passes`-behandeling als `_plan_with_mutators`,
        en om dezelfde reden: met die vlaggen aan lijmt de optimalisatie de stukken aan
        elkaar en schuift consolestappen naar achteren, zodat een Z pas zakt nadat er al
        gebrand is. Voor een bestand in het geheugen van de machine is dat net zo'n fout
        als bij een gewone job — het risico staat op het werkstuk en op de lens.
        """
        all_mutators = list(mutators)
        after = []
        if self._focus_layers():
            from meerk40t.core.node.util_console import ConsoleOperation

            all_mutators.append(lambda steps: self._with_focus_moves(steps, ConsoleOperation))
        if self._multi_pass_layers():
            from meerk40t.core.node.util_console import ConsoleOperation

            all_mutators.append(lambda steps: self._with_passes(steps, ConsoleOperation))
            after.append(self._share_pass_settings)
        root = self.kernel.root
        root.setting(bool, "opt_merge_ops", True)
        root.setting(bool, "opt_merge_passes", True)
        eerder = (root.opt_merge_ops, root.opt_merge_passes)
        root.opt_merge_ops = False
        root.opt_merge_passes = False
        try:
            output = self.run(PLAN_COPY)
            self._apply_mutators(all_mutators)
            output += self.run(PLAN_BLOB)
            self._apply_mutators(after)
            return output
        finally:
            root.opt_merge_ops, root.opt_merge_passes = eerder

    # ------------------------------------------------------ zakken per pass

    @contextmanager
    def claim_plan(self):
        """
        Take the plan for real work, and say so first.

        The counter goes up *before* the lock is asked for, so a preview build that
        is halfway through sees the claim at its next phase boundary and gives up
        instead of finishing a plan that is about to be thrown away.

        A phase boundary is as fine as this gets: `plan optimize` is one console call
        and cannot be interrupted from outside, and at the preview ceiling it is the
        2.26 s of a 3.2 s build. Measured on 990 squares, a start fired 0, 200 and
        600 ms after a build began answered 200 after 3.23, 3.05 and 2.50 s. So this
        is not "at most one phase" — it is two to three and a half seconds in the
        heaviest case the preview admits, and all three of those starts succeeded.
        """
        with self._lock:
            self._plan_claims += 1
        with self._plan_lock:
            yield

    @property
    def plan_claims(self) -> int:
        return self._plan_claims

    def preview_plan(self, harvest, mutators=()):
        """
        Build the plan for looking at, and hand it to `harvest` before letting go.

        Same route as a real job — the pass unfolding and the shared settings dict
        included, because a preview that skips our own workarounds shows something
        the machine will not do — with `spool` left off and the lock released
        between the phases.

        `mutators` is what the burn would add and this must add too. It exists for the
        series: on the last plate the places the list has no names left for hold the
        literal `{name#+2}`, and a cut-path window that drew those nine characters — and
        a jig frame on every plate after the first — would be answering "what does the
        machine do, when" about a job nobody is going to run.

        `harvest` runs while the lock is still held: after this method there is no
        plan any more (`plan clear` in the `finally`), and a caller holding a
        reference into it would be reading the next job's work.

        Raises `PlanYielded` when a job claimed the plan meanwhile. That is not an
        error but the answer: whoever is burning wins.
        """
        with self.rotary_applied():
            return self._preview_plan_locked(harvest, mutators)

    def _preview_plan_locked(self, harvest, mutators=()):
        # Split off only so that the rotary wraps the whole build; `preprocess` is the
        # phase that reads `device.rotary`, and it is one of the phases below.
        multi = self._multi_pass_layers()
        root = self.kernel.root
        root.setting(bool, "opt_merge_ops", True)
        root.setting(bool, "opt_merge_passes", True)
        earlier = (root.opt_merge_ops, root.opt_merge_passes)
        if multi:
            # Same reason as in `_plan_with_mutators`: with merging on, the
            # optimisation glues the passes into one piece and pushes the console
            # steps to the back, so the preview would draw a Z drop that happens
            # after the burning instead of between the passes.
            root.opt_merge_ops = False
            root.opt_merge_passes = False
        claims = self._plan_claims
        try:
            with self._plan_lock:
                self._give_way(claims)
                self.run(PLAN_COPY)
                # In the burn's own order: what a plate leaves out first, and only then
                # the passes of what is left. The other way round the passes of a place
                # that is not burned at all would be unfolded and then removed.
                if mutators:
                    self._apply_mutators(list(mutators))
                if multi:
                    from meerk40t.core.node.util_console import ConsoleOperation

                    self._apply_mutators(
                        [lambda steps: self._with_passes(steps, ConsoleOperation)]
                    )
            for phase in PREVIEW_PHASES:
                with self._plan_lock:
                    self._give_way(claims)
                    self.run(phase)
            with self._plan_lock:
                self._give_way(claims)
                if multi:
                    self._apply_mutators([self._share_pass_settings])
                self.run("plan preopt")
                self.run("plan optimize")
                return harvest(self.kernel.planner.default_plan)
        finally:
            root.opt_merge_ops, root.opt_merge_passes = earlier
            with self._plan_lock:
                self.run("plan clear")

    @contextmanager
    def rotary_applied(self):
        """
        The rotary's Y scale, for as long as the plan is being built.

        Sits here and not at the routes because every plan goes through this class: a job,
        a tile run, the cut-path preview and the exact estimate. A scale that reached only
        one of them would show a preview of a job that burns differently.
        """
        if self.rotary is None:
            yield None
            return
        with self.rotary.applied() as scale:
            yield scale

    def _give_way(self, claims: int) -> None:
        if self._plan_claims != claims:
            raise PlanYielded()

    def _plan_and_spool(self, mutators=()) -> list[str]:
        """
        Building the plan. With mutators in two steps, otherwise in one.

        A mutator is a callable that gets the plan steps and hands them back. The order
        counts: tiles first (clipping and moving), Z steps afterwards (unfolding the passes) —
        the other way round you clip the same work six times.

        The ordinary route stays literally one line: that path is walked on every job and
        deserves no extra bends.
        """
        with self.claim_plan():
            # The rotary scales Y on its way to the machine (rotary.py), in the same place
            # and for the same reason as the zero point: the design on screen is untouched.
            with self.rotary_applied():
                return self._plan_and_spool_locked(mutators)

    def _plan_and_spool_locked(self, mutators=()) -> list[str]:
        """The same, with the plan already claimed. See `claim_plan`."""
        all_mutators = list(mutators)
        after = []
        if self._focus_layers():
            from meerk40t.core.node.util_console import ConsoleOperation

            # Before the passes: the height belongs to the layer, and unfolding the passes
            # only repeats the layer. The other way round the repeats would each get their
            # own move of zero.
            all_mutators.append(lambda steps: self._with_focus_moves(steps, ConsoleOperation))
        if self._multi_pass_layers():
            from meerk40t.core.node.util_console import ConsoleOperation

            all_mutators.append(lambda steps: self._with_passes(steps, ConsoleOperation))
            # After the blobbing: one layer's passes belong in one RD layer.
            after.append(self._share_pass_settings)
        if not all_mutators and not after:
            return self.run(PLAN_AND_SPOOL)
        return self._plan_with_mutators(all_mutators, after)

    def _plan_with_mutators(self, mutators, post=()) -> list[str]:
        """
        Build the plan, work on it, and only then finish it.

        `opt_merge_ops`/`opt_merge_passes` go off while we are working on the plan. With
        those flags on, the optimisation glues pieces into one cutcode and pushes console
        steps to the back — then a Z only drops once burning has already happened, and you
        notice that on the workpiece instead of on the screen. They are the user's settings,
        so they go back in a `finally`.

        The plan is a copy of the tree: `plan copy` calls `copy_children_as_real`, which
        dereferences the ReferenceNodes and copies the shapes themselves. So what is mutated
        here does not touch the user's design.
        """
        root = self.kernel.root
        root.setting(bool, "opt_merge_ops", True)
        root.setting(bool, "opt_merge_passes", True)
        eerder = (root.opt_merge_ops, root.opt_merge_passes)
        root.opt_merge_ops = False
        root.opt_merge_passes = False
        try:
            output = self.run(PLAN_COPY)
            self._apply_mutators(mutators)
            if not post:
                output += self.run(PLAN_REST)
                return output
            # In two bites, because a mutator that touches the cutcode can only see
            # anything *after* `blob`. `spool` stays the last step.
            output += self.run(PLAN_BLOB)
            self._apply_mutators(post)
            output += self.run(PLAN_SPOOL)
            return output
        finally:
            root.opt_merge_ops, root.opt_merge_passes = eerder

    def _apply_mutators(self, mutators) -> list:
        """The processors over the copied plan. Returns the new steps."""
        plan = self.kernel.planner.get_or_make_plan("0")
        steps = list(plan.plan)
        for mutator in mutators:
            steps = list(mutator(steps))
        plan.plan[:] = steps
        return steps

    def build_plan(self, mutators=()) -> list:
        """
        The copied and mutated plan, without finishing it.

        Exists because you cannot look at it otherwise: `blob` replaces the operations with
        one `CutCode`, so after a full `plan` line there is no layer with children left to
        establish anything about. What the mutators do is exactly what should be tested here,
        and this is the only place where that is still visible.

        Deliberately does not run the spooler: this is the hook for tests, not a second way
        to start a job.
        """
        self.run(PLAN_COPY)
        return self._apply_mutators(mutators)

    def _z_stepped_layers(self) -> list:
        """
        Layers that burn, do more than one pass *and* carry a Z step.

        The machine is asked first whether it has a Z axis. That is not doubling up on the
        refusal when setting it: a layer keeps its step when you switch to another machine,
        and without this question a design made on a diode laser would send a `z_move` on the
        Ruida that does not exist there — in the middle of the job, with the head on the work.
        """
        found = []
        device = getattr(self.kernel, "device", None)
        if device is None or not getattr(device, "supports_z_axis", False):
            return found
        if not self.kernel.find("command", "None", "z_move$"):
            return found
        try:
            operations = list(self.kernel.elements.ops())
        except Exception:  # pragma: no cover - a tree without an ops branch
            return found
        for operation in operations:
            if not str(getattr(operation, "type", "")).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            if not getattr(operation, "z_step_mm", None):
                continue
            if int(getattr(operation, "passes", 1) or 1) < 2:
                continue
            found.append(operation)
        return found

    @staticmethod
    def _share_pass_settings(steps) -> list:
        """
        Keeping the passes of one layer inside one RD layer.

        Runs *after* `blob`, because before then the copies do not exist. `blob` gives every
        pass its own settings dict (`core/cutplan.py` `_blob_convert` copies the dict as soon
        as `passes` and `implicit_passes` differ) and the Ruida driver groups its layers on
        the identity of that dict (`ruida/rdjob.py:1434`). So every pass became an extra layer
        in the file. Measured on the real RD stream of a board with four squares: 4 layers at
        one pass, **8** at two, and 4 again as soon as the copies share their dict. A board of
        sixteen squares comes to 33 layers at two passes, and then the controller says "file
        invalid" and the laser stands still.

        The key is the `id` from the settings dict: copies of the same operation carry the
        same one. Layers with a Z step are deliberately left out: there a `z_move` belongs
        between the passes, and that sequence was measured with a layer of its own per pass.
        """
        first: dict = {}
        for step in steps:
            if not hasattr(step, "__iter__"):
                continue
            for item in step:
                settings = getattr(item, "settings", None)
                if not isinstance(settings, dict):
                    continue
                if settings.get("z_step_mm"):
                    continue
                key = settings.get("id")
                if key is None:
                    continue
                shared = first.setdefault(key, settings)
                if shared is not settings:
                    item.settings = shared
        return list(steps)

    def _multi_pass_layers(self) -> list:
        """
        Layers that burn and do more than one pass.

        Why this deserves a route of its own through the plan: `blob` makes every pass a
        piece of cutcode of its own **with a settings dict of its own**
        (`core/cutplan.py:_blob_convert` copies the dict as soon as `passes` and
        `implicit_passes` differ). The Ruida driver groups its RD layers on the identity of
        that dict (`ruida/rdjob.py:1434`), so every pass became an *extra* layer in the file.
        Measured on a test board of four squares: 4 RD layers at one pass, 8 at two. A board
        of sixteen squares then goes above what the controller accepts, and it says nothing
        better than "file invalid" — with a laser standing still.

        What *does* work is putting the same node in the plan list several times: `blob`
        makes fresh cutcode per place and the settings dict stays one object, so the number of
        layers stays equal to the number of operations. That is exactly what the Z step
        already did; this is that route for *every* layer with more than one pass.

        Aside: `opt_merge_passes` would solve the same thing by making one copy with
        `passes=N`, but the Ruida driver does not look at that number (not a single reference
        to `passes` in `ruida/driver.py`) — then the layer would silently burn once.
        """
        found = []
        try:
            operations = list(self.kernel.elements.ops())
        except Exception:  # pragma: no cover - a tree without an ops branch
            return found
        for operation in operations:
            if not str(getattr(operation, "type", "")).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            if int(getattr(operation, "implicit_passes", 1) or 1) < 2:
                continue
            found.append(operation)
        return found

    @staticmethod
    def _with_passes(steps, console_operation) -> list:
        """
        Unfolding the passes: every layer appears in the plan as often as it burns.

        With a Z step a `z_move` comes between the passes and one back at the end; without a Z
        step it is only the repeating. Pure arithmetic on the step list, so testable without a
        machine.
        """
        uitgebreid = []
        for step in steps:
            z_step = getattr(step, "z_step_mm", None)
            passes = int(getattr(step, "implicit_passes", 0) or getattr(step, "passes", 1) or 1)
            if passes < 2:
                uitgebreid.append(step)
                continue
            # The counter on the operation goes to one: we do the repeating now.
            step.passes = 1
            step.passes_custom = True
            for index in range(passes):
                uitgebreid.append(step)
                if z_step and index < passes - 1:
                    uitgebreid.append(
                        console_operation(command=f"z_move {z_step:.3f}mm")
                    )
            if z_step:
                uitgebreid.append(
                    console_operation(command=f"z_move {-z_step * (passes - 1):.3f}mm")
                )
        return uitgebreid

    def _focus_layers(self) -> list:
        """
        Layers of a focus board: they carry a Z offset of their own.

        Same first question as the Z step per pass, and for the same reason: a board drawn
        on a machine with a Z axis keeps its offsets when you switch to a machine without
        one, and there a `z_move` does not exist. Then the board burns every mark at the
        same height — which looks like an answer and is not — but at least the job does not
        die on an unknown command with the head on the work.
        """
        found = []
        device = getattr(self.kernel, "device", None)
        if device is None or not getattr(device, "supports_z_axis", False):
            return found
        if not self.kernel.find("command", "None", "z_move$"):
            return found
        try:
            operations = list(self.kernel.elements.ops())
        except Exception:  # pragma: no cover - a tree without an ops branch
            return found
        for operation in operations:
            if not str(getattr(operation, "type", "")).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            if getattr(operation, "focus_z_mm", None) is None:
                continue
            if not list(getattr(operation, "children", []) or []):
                # An empty layer burns nothing, so its height means nothing. This is not
                # hypothetical: the engine restores the previous session's layer list from
                # `operations.cfg` (see CLAUDE.md), so an empty focus layer from yesterday
                # would put `z_move` steps in today's unrelated job.
                continue
            found.append(operation)
        return found

    @staticmethod
    def _with_focus_moves(steps, console_operation) -> list:
        """
        The plan steps with the focus board's height changes in them.

        Every layer that carries `focus_z_mm` gets a `z_move` in front of it — of the
        *difference* with the height the head is already at, not of the offset itself,
        because `z_move` is a relative move. At the end one move back to where the head
        started, so the next job on the same sheet is not burned at the last mark's height.

        Only when the height actually changes: a layer unfolded into several passes appears
        several times in the list, and a `z_move 0` between the copies would be a command
        for nothing. Pure arithmetic on the step list, so testable without a machine.
        """
        out = []
        current = 0.0
        for step in steps:
            offset = getattr(step, "focus_z_mm", None)
            if offset is None or not list(getattr(step, "children", []) or []):
                # Same reason as in `_focus_layers`: a layer with nothing in it does not
                # get a height change of its own.
                out.append(step)
                continue
            wanted = float(offset)
            if abs(wanted - current) > 1e-6:
                out.append(console_operation(command=f"z_move {wanted - current:.3f}mm"))
                current = wanted
            out.append(step)
        if abs(current) > 1e-6:
            out.append(console_operation(command=f"z_move {-current:.3f}mm"))
        return out

    @staticmethod
    def _with_z_moves(steps, console_operation) -> list:
        """The plan steps with the Z movements in them. Pure arithmetic, so testable."""
        uitgebreid = []
        for step in steps:
            z_step = getattr(step, "z_step_mm", None)
            passes = int(getattr(step, "passes", 1) or 1)
            if not z_step or passes < 2:
                uitgebreid.append(step)
                continue
            # The counter on the operation goes to one: we do the repeating now.
            step.passes = 1
            step.passes_custom = True
            for index in range(passes):
                uitgebreid.append(step)
                if index < passes - 1:
                    uitgebreid.append(
                        console_operation(command=f"z_move {z_step:.3f}mm")
                    )
            uitgebreid.append(
                console_operation(command=f"z_move {-z_step * (passes - 1):.3f}mm")
            )
        return uitgebreid

    def _name_job(self, name, burnable: int) -> None:
        """
        Giving the fresh job a name a human recognises (gap P4).

        The engine calls it `Spooler:3 items` as soon as there is no file name: the class name
        plus the length of the command list (spoolers.py:612). The `spool` command takes its
        label from `elements.basename` and knows no option to put something else in it, so we
        rename the job after it is in the queue. Only when the engine knew nothing itself: if
        you have loaded a file, that name is better than ours.
        """
        title = (name or "").strip()
        if not title:
            title = f"{burnable} operation" + ("" if burnable == 1 else "en")
        try:
            queue = list(self.kernel.device.spooler.queue)
        except Exception:
            return
        if not queue:
            return
        job = queue[-1]
        current = str(getattr(job, "label", "") or "")
        if current and not re.fullmatch(r"\w+:\d+ items?", current):
            return
        try:
            job.label = title
        except Exception:  # pragma: no cover - the engine must not break us
            pass

    def _driver_paused(self):
        """`driver.paused` of the active device, or None when nobody says."""
        try:
            flag = self.kernel.device.driver.paused
        except Exception:
            return None
        return flag if isinstance(flag, bool) else None

    def pause(self) -> list[str]:
        """
        Pausing, and nothing else.

        On lihuiyu, ruida *and* grbl `pause` is a *toggle*: if the driver is already paused,
        the same command resumes (lihuiyu/device.py:844,
        ruida/device.py:425, grbl/device.py:982). So pressing Pause twice sets the machine
        burning again, and that is exactly the opposite of what is on the button.
        """
        if self._driver_paused() is True:
            return ["already paused"]
        return self.run("pause")

    def resume(self) -> list[str]:
        """
        Resuming, and checking that it has actually happened.

        Measured on a lihuiyu device: `resume` reports "Lihuiyu Channel Resumed." and the
        machine stays put. The cause is in the engine — the device registers `resume` twice,
        first as a realtime resume (device.py:855) and later again as "Resume Controller"
        (device.py:1045). The second wins, and that starts the controller instead of the
        driver: `driver.paused` stays True and `hold_work()` holds the work back. On a K40 a
        paused job therefore never got going again — the resume button did nothing, every
        time.

        We cannot fix that in `meerk40t/`, so we check the result: if the driver is still
        paused afterwards, we take it off with the toggle. For ruida and grbl nothing changes;
        there the flag is already gone after the first attempt.
        """
        if self._driver_paused() is False:
            return ["not paused"]
        output = self.run("resume")
        if self._driver_paused() is True:
            output = output + self.run("pause")
        return output

    def stop(self) -> list[str]:
        """Abort the running job. estop is realtime; abort is the fallback."""
        if self.supports("estop"):
            return self.run("estop")
        return self.run("abort")

    def clear_queue(self) -> list[str]:
        return self.run("spool clear")
