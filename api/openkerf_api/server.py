"""
The OpenKerf read-only API server.

A FastAPI app running on uvicorn in its own thread, next to (never inside) the
MeerK40t kernel. It exposes REST snapshots and a WebSocket that pushes live
status, and it bridges kernel signals — which are dispatched on the kernel
thread at ~20 Hz — onto the server's asyncio loop.

Reading is open. Writing — loading a file, spooling a job, pause/resume/stop —
sits behind a token as soon as the API is bound beyond loopback, and every
write runs through the serialised CommandRunner.
"""

import asyncio
import inspect
import json
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .auth import extract_token, generate_token, is_loopback, token_matches
from . import boardcode
from .commands import CommandError, CommandRunner
from .design import DesignReader
from .document import Document
from .duplicates import Duplicates
from .focus import FocusBoard
from .plating import Plating
from .printcut import PrintCut
from .drawing import Drawing
from .edits import DesignEditor, DesignError
from .images import Images
from .library import BUNDLE_SUFFIX, Library, LibraryError, default_path
from .autosave import Autosave
from .camera import Camera
from .clipart import Clipart
from .cutpath import CutPath
from .fonts import Fonts
from .generators import Generators
from .nesting import Nesting
from .nodes import Nodes
from .palette import Palette, machine_key
from .presetariat import Presetariat
from .provenance import Provenance
from .rotary import RotaryControl
from .series import (
    OverrunMutator,
    Series,
    burn_rows,
    read_rows,
    rows_from_numbers,
    rows_in,
)
from .sheets import Sheets
from .starter import Starter
from .tilerun import TileRun
from .testgrid import (
    LABEL_LAYERS,
    TestGridGenerator,
    cutout_setting,
    is_cel_element,
    is_cel_operatie,
    is_raster_group,
    markeer_foto,
    plan_grid,
    raster_supported,
)
from .machine import MachineControl
from .machines import MachineError, MachineManager
from .status import StatusReader

# Kernel signals worth forwarding to connected clients. Every one of these is
# emitted by the engine itself; we only listen.
CAMERA_HINT = (
    "A camera image needs OpenCV. Install it beside the engine with "
    "'pip install opencv-python-headless'."
)

SIGNALS = (
    "pipe;usb_status",
    "pipe;running",
    "driver;position",
    "spooler;queue",
    "spooler;completed",
    "warn_state_update",
    # Design changes, so the canvas knows when to refetch.
    "tree_changed",
    "rebuild_tree",
    "element_property_update",
)

HEARTBEAT_SECONDS = 2.0

#: The largest list we will take in. A list of names is a few kilobytes, so anything
#: past this is a spreadsheet with the photographs still in it or simply the wrong file
#: — and streaming it into a temp directory before saying so costs the disk and buys
#: nothing. Counted while reading, so the refusal comes before the whole body is on
#: disk.
SERIES_UPLOAD_LIMIT = 5 * 1024 * 1024

#: How many rows a preview shows. Enough to recognise your own file by, few enough that
#: the answer stays small; the row count beside it says how many there really are.
SERIES_PREVIEW_ROWS = 10

# Who this server is, in this process (gap E2). New at every start; the client compares it
# on reconnecting and so knows whether it is talking to the same engine as before the
# silence.
INSTANCE_ID = uuid.uuid4().hex


#: Everything this layer raises when it refuses what somebody asked for, as opposed to
#: the engine failing under it (that is `CommandError`). One tuple, because both route
#: helpers below have to catch the same set: the day a module grows a fourth error of
#: its own, adding it here is the whole change instead of a 500 out of whichever helper
#: was forgotten.
OUR_REFUSALS = (MachineError, DesignError, LibraryError)


def refuse(e):
    """
    Our own refusal, as the 409 a client can act on. Returns the exception to raise.

    Returning rather than raising keeps `raise refuse(e) from e` at the call site, so a
    reader of a route helper sees the control flow and the traceback keeps the refusal
    that caused it.

    Our own refusals carry an optional code, and it travels in a header rather than in
    the body: `detail` is a string everywhere in this API and every client reads it that
    way. A header adds the machine-readable half without breaking the human-readable
    one, so the web app can say the refusal in the reader's language while curl still
    shows a sentence.

    A refusal may also carry the numbers its sentence needs, and those go in a second
    header as JSON. That is for the number that is a constant of ours — "at most 200
    bridges" — which a code alone cannot carry, so the translated sentence used to be
    impossible and the panel showed English.

    One function and not a branch in each helper, because `manage()` had this from
    the start while `act()` caught `CommandError` only — so a refusal of ours raised
    inside `/api/job/start` (`act(run)`, below) came out of FastAPI as a 500 with no
    sentence and no code, on the one button every client presses to burn.
    """
    # fastapi lives inside `build_app` in this module and this helper keeps to that, so
    # importing the module still does not pull the web framework in.
    from fastapi import HTTPException

    code = getattr(e, "code", None)
    headers = {"X-OpenKerf-Error": code} if code else None
    values = getattr(e, "values", None)
    if headers and values:
        headers["X-OpenKerf-Error-Values"] = json.dumps(values)
    return HTTPException(status_code=409, detail=str(e), headers=headers)


class EventBridge:
    """
    Fan-out of kernel signals to WebSocket clients.

    Kernel signals arrive on the kernel thread; WebSocket sends must happen on
    the server's asyncio loop. Everything crosses that boundary through
    `loop.call_soon_threadsafe`.
    """

    def __init__(self):
        self._loop = None
        self._clients = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop):
        self._loop = loop

    def add_client(self, websocket):
        with self._lock:
            self._clients.add(websocket)

    def remove_client(self, websocket):
        with self._lock:
            self._clients.discard(websocket)

    @property
    def client_count(self):
        with self._lock:
            return len(self._clients)

    def publish_threadsafe(self, event: dict):
        """Called from the kernel thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.broadcast(event))
            )
        except RuntimeError:
            # Loop shut down between the check and the call.
            pass

    async def broadcast(self, event: dict):
        payload = json.dumps(event, default=str)
        with self._lock:
            clients = list(self._clients)
        for websocket in clients:
            try:
                await websocket.send_text(payload)
            except Exception:
                self.remove_client(websocket)


def _spa_files(directory: str):
    """
    Static files with a single-page-app fallback.

    The frontend is client-routed: /setup exists only in the browser, so an
    unknown path has to return index.html instead of a 404. Real missing
    assets (a stale .js hash) still need to 404, or the browser would try to
    execute HTML as JavaScript.

    An unknown `/api` path does **not** fall under this. It used to, with two misleading
    consequences: a GET got the HTML page back (where the frontend expected JSON) and a
    POST got "405 Method Not Allowed", because the fallback only knows GET. So anybody
    running an older server beside a newer frontend saw an incomprehensible error message
    instead of "I do not know that route".
    """
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            if path.startswith("api/") or path == "api":
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": (
                            f"Unknown API route '/{path}'. Is the server perhaps "
                            "running older code than the frontend? Restart it "
                            "if so."
                        )
                    },
                )
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as e:
                if e.status_code != 404 or "." in Path(path).name:
                    raise
                return await super().get_response("index.html", scope)

    return SPAStaticFiles(directory=directory, html=True)


class ApiServer:
    """Owns the uvicorn thread, the signal subscriptions and the event bridge."""

    def __init__(
        self,
        kernel,
        port=8080,
        bind="127.0.0.1",
        frontend=None,
        token=None,
        library_path=None,
    ):
        self.kernel = kernel
        self.port = port
        self.bind = bind
        self.frontend = Path(frontend).expanduser() if frontend else None
        self.reader = StatusReader(kernel)
        self.document = Document()
        self.commands = CommandRunner(kernel, self.document)
        self.machines = MachineManager(kernel, self.commands)
        self.library = Library(library_path or default_path(kernel))
        self.presetariat = Presetariat(
            self.library,
            Path(self.library.path).with_name("presetariat-cache.json"),
            # Beside the library like the sheets and the palette, and for the same
            # reason: it is about this installation and not about this project. Not
            # *inside* the library, because a library is a file you hand to a colleague
            # and who you are is not part of it. No `was`: this file never had a Dutch
            # name.
            handle_path=self._beside("openkerf-contributor.json"),
        )
        # The offer a machine with no settings gets, and the staging that answers it. It
        # holds no state of its own: the coverage is six counts over the library and the
        # staged bundle is a file in the upload directory.
        self.starter = Starter(self.library, self.presetariat)
        self.editor = DesignEditor(kernel, self.commands)
        self.drawing = Drawing(kernel, self.commands)
        self.motion = MachineControl(kernel, self.commands)
        # The rotary. Machine-wide, stored on the device service, and applied while the
        # plan is being built — so the runner needs to know about it, not the routes: a
        # job, a tile run, the preview and the exact estimate all go through there.
        self.rotary = RotaryControl(kernel)
        self.commands.rotary = self.rotary
        # The cut path for looking at, cached against the design itself. Built in a
        # thread of its own: a build takes seconds on a heavy design and a request
        # that takes seconds is a request the browser gives up on.
        self.cutpath = CutPath(kernel, self.commands, self.drawing)
        self.images = Images(kernel, self.commands)
        self.nodes = Nodes(kernel, self.commands)
        self.sheets = Sheets(
            kernel,
            self.drawing,
            self.document,
            self._beside("openkerf-sheets", "openkerf-vellen"),
        )
        self.tiles = TileRun(
            kernel,
            self.drawing,
            self.sheets,
            self.commands,
            self._beside("openkerf-tiles.json", "openkerf-tegelreeks.json"),
        )
        # One design, burned once per row of a list. It needs the runner to spool a
        # burn, the sheets to record which sheet a run belongs to, and the tile run
        # because that is the other thing in this app that decides what the next burn
        # is — the two refuse each other. No `was`: this file never had a Dutch name.
        self.series = Series(
            kernel,
            self._beside("openkerf-series.json"),
            runner=self.commands,
            tiles=self.tiles,
            sheets=self.sheets,
        )
        # Bound on the drawing rather than passed to it, because the drawing is built
        # first: the series spools through the command runner it already owns. Two things
        # need it there — the refusal when a text asks for a column the list has not got,
        # which has to be said at the text field and not at the machine, and the list
        # riding along in a project bundle. Same idiom as `self.commands.rotary` above.
        self.drawing.series = self.series
        # And the cut-path window, for the same reason in a different room: it draws what
        # the machine does and in what order, so it has to leave out what the next plate
        # leaves out. One sum (`Series.burn_mutators`) is read by the burn, the pre-flight
        # and this window.
        self.cutpath.series = self.series
        # Where a layer's settings come from. Beside the library, because it is about
        # presets; not *in* it, because it is about this project.
        self.provenance = Provenance(
            self._beside("openkerf-provenance.json", "openkerf-herkomst.json")
        )
        # What every palette colour last did on this machine (decision B2). Beside the
        # provenance and emphatically not in it: this is habit, not evidence — see the head
        # of palette.py.
        self.palette = Palette(
            self._beside("openkerf-palette.json", "openkerf-palet.json")
        )
        # `series` for the Repeat tab's "each copy takes the next name": the
        # generator needs to know whether a list is attached and how many rows it
        # has, and one answer to that in the app is one answer.
        self.generators = Generators(
            kernel, self.commands, self.drawing, self.sheets, self.series
        )
        self.nesting = Nesting(kernel, self.editor)
        # Filling a plate with one piece per row of the list. It borrows the repeat from
        # `generators` rather than copying its own way: one way of copying, and one way
        # of giving a copy the next name.
        self.plating = Plating(
            kernel, self.drawing, self.sheets, self.generators, self.series, self.editor
        )
        self.duplicates = Duplicates(kernel, self.drawing)
        self.focus = FocusBoard(kernel, self.drawing)
        self.printcut = PrintCut(kernel, self.drawing, self.motion)
        self.fonts = Fonts(kernel)
        self.camera = Camera(kernel, self.commands)
        self.clipart = Clipart(kernel, self.drawing)
        self.autosave = Autosave(
            kernel,
            self.drawing,
            self.document,
            Path(self.library.path).with_name("openkerf-herstel.svg"),
        )
        self.design = DesignReader(
            kernel,
            keep_operations=self.drawing.user_operations,
            grid_operations=lambda: self.library.grid_operations(),
        )
        self.drawing.grid_operations = lambda: self.library.grid_operations()
        # Decision B2: a layer that comes into being while drawing starts at what that
        # colour did on this machine before.
        self.drawing.color_memory = lambda colour: self.palette.recall(
            self._palette_machine()[0], colour
        )
        # Gap J12: the zero point lives on the machine (machine.py) and decides where the
        # work lands. One source, two readers — the pre-flight and the spooling.
        self.drawing.origin = self.motion.origin
        self.grids = TestGridGenerator(kernel)
        self.bridge = EventBridge()
        self.channel = kernel.channel("openkerf-api")

        # Loopback means "this computer only", so a token would be friction
        # without added safety. Anything wider and writes must be authenticated.
        self.local_only = is_loopback(bind)
        self.token = token or generate_token()
        self._upload_dir = None

        self._server = None
        self._thread = None
        self._listeners = []

    # ------------------------------------------------------------------ app

    def _active_profile(self):
        """
        The library profile of the machine the engine is using now.

        The engine knows devices, the library knows profiles; this is the knot between
        them. No active device means no profile — then we show everything.

        Only for a machine somebody has set up. MeerK40t starts with an lhystudios device so
        that the kernel always has something to talk to; nobody chose that. This function is
        called on six read routes and creates what is not there, so without this hurdle
        opening the library on a fresh installation immediately produces a profile with that
        device's internal name — and that way names end up in the list of machines the user
        never had.
        """
        device = getattr(self.kernel, "device", None)
        path = getattr(device, "path", None) if device is not None else None
        if not path:
            return None
        try:
            if not self.machines._configured(device):
                return None
        except Exception:
            return None
        try:
            return self.library.profile_for_device(
                str(path),
                str(getattr(device, "label", "") or path),
                machine_uid=self.machines.machine_uid(device),
            )
        except Exception:
            return None

    def _live_device_paths(self) -> set[str]:
        """
        The slots that a machine somebody set up is sitting in right now.

        Only configured machines, exactly as the profile list counts them: MeerK40t always
        keeps an lhystudios stand-in alive so the kernel has something to talk to, and
        counting that as "a machine that exists" would let it block a merge between two
        profiles of the user's own laser.
        """
        return {
            device.path
            for device in self.kernel.services("device")
            if self.machines._configured(device)
        }

    def _palette_machine(self):
        """
        Which machine the palette memory falls under, and what it is called.

        Speed and power are machine properties: 12 mm/s at 80 watts is a different cut
        from at 40. A memory that mixes those up is worse than no memory, so it hangs off
        the machine or off nothing.
        """
        profile = self._active_profile()
        name = None
        if profile:
            name = profile.get("name") or profile.get("device_path")
        return machine_key(profile), name

    def _remember_layer(self, operation_id: str) -> None:
        """
        Record what this layer's colour does now.

        Called *after* a successful change, because a refused attempt is not a habit. If
        this fails, at worst there is no memory — it must never strand the change itself.
        """
        try:
            operation = self.drawing._operation(operation_id)
            color = self.drawing._usable_color(operation)
            if color is None:
                return
            power = getattr(operation, "power", None)
            key, name = self._palette_machine()
            self.palette.remember(
                key,
                color,
                speed=getattr(operation, "speed", None),
                power_percent=None if power is None else float(power) / 10,
                kind=str(getattr(operation, "type", "") or ""),
                machine_name=name,
            )
        except Exception:
            return

    def _rotary_state(self, sheet=None):
        """
        The rotary, with the height of what is on the bed measured against it.

        That measurement is what turns the circumference from a number into an answer:
        300 mm of work on a cup of 251.3 mm burns over itself. Reading the bounds must
        never be the reason a pre-flight fails, hence the fallback.
        """
        height = None
        try:
            report = self.drawing.bounds_report(sheet)
            height = (report.get("work") or {}).get("height_mm")
        except Exception:  # pragma: no cover - the engine must not break the pre-flight
            height = None
        return self.rotary.state(height)

    def _active_sheet(self):
        """
        The sheet being worked on now, with the name of its material.

        The sheet keeps only an id — the library knows what it is called, and without that
        name the pre-flight cannot say what you are burning *into*.
        """
        try:
            sheet = self.sheets.active()
        except Exception:
            return None
        if sheet is None:
            return None
        name = None
        if sheet.get("material_id") is not None:
            try:
                name = next(
                    (
                        m["name"]
                        for m in self.library.materials()
                        if m["id"] == sheet["material_id"]
                    ),
                    None,
                )
            except Exception:
                name = None
        return {**sheet, "material_name": name}

    def _tiling_state(self):
        """
        The state of the tile series, or nothing.

        In the status payload and not in a route of its own: top bar, canvas and phone view
        have to see the same state, and three separate requests let them drift apart.
        """
        try:
            return self.tiles.state()
        except Exception:  # pragma: no cover - status mag nooit omvallen
            return None

    def _series_state(self):
        """
        The series, or nothing — and the bed put right on the way past.

        Beside the tile run and for the same reason: top bar, canvas, context panel and
        phone view all read the live socket, and four separate requests for one fact
        drift apart. `Series.state()` also re-primes the engine when something has moved
        the row behind our back, which is why it is called even on the way to answering
        `None`.

        Nothing attached means nothing to say. The rows themselves never ride here —
        `GET /api/series` is where a thousand of them belong, not every heartbeat.
        """
        try:
            state = self.series.state()
        except Exception:  # pragma: no cover - status must never fall over
            return None
        return state if state.get("attached") else None

    def _series_burn(self) -> tuple:
        """
        The burn the pre-flight is about: what it leaves out, and how many are still due.

        The pre-flight has to describe the button that is going to burn. While a series
        runs, that button is `POST /api/series/burn`, and it hands the plan an
        `OverrunMutator` (`series.py`): out come the places the list has no rows left
        for, and out comes a `mkonce` jig frame on every plate after the first. Without
        that same mutator the estimate is a number for a job nobody is going to run.
        Measured on the design of `api/tests/test_series_estimate.py` — three places on
        the sheet, five names, the pointer on the last sheetful, one frame marked burn
        once — the real cut plan held **409 cut objects and 37.3 s** as this route used
        to build it, against **172 objects and 9.8 s** as the burn builds it: 26 of those
        37 seconds were the frame (15.0 s) and the literal `{name#+2}` (11.3 s), neither
        of which the machine was going to touch. The interface multiplies that by the
        plates still to come, so a near-fourfold error over one plate was about to become
        a near-fourfold error over an afternoon.

        With no run going there is deliberately no mutator: the button that burns is
        then the plain one, and `/api/job/start` composes only the print-and-cut pose —
        so a plain Burn on the last sheetful really does engrave the nine characters
        `{name#+2}`, and really does cut the jig again. Whether *that* should be refused
        or mutated is a question about the burn and not about the clock, and it is not
        this route's to answer by understating the work the button will do. An estimate
        that leaves out what the machine is going to do is the same bug pointing the
        other way.

        `Series.state()` is asked rather than `Series.check()`, and not only for `run`:
        it re-primes the bed if anything has moved the row behind our back, so what is
        measured below is the row that is about to burn and not the one before it.

        The second half of the answer is how many burns are still due, and it is here
        rather than in the interface for the reason the plan gives in one line: a job of
        fifty burns must never show the time of one. Leaving the multiplication to the
        frontend means two places counting plates — this one, and whatever the panel
        derives from `burns` and `current_burn` — and the moment they disagree the
        number on the screen is nobody's. So the count comes off the same partition the
        run verbs act on: the burns whose rows are not all in `done`, which is exactly
        how many times the operator still has to press Burn (`Series.advance` walks that
        same set). Not `burns - current_burn + 1`: after a redo of row 12 in a list
        burned to row 18 that says three plates where one is left.

        The partition itself is `burn_rows` — the very function `Series._burns` calls —
        fed only from fields `Series.state()` publishes, so there is one rule about how
        rows fall into burns and this reads it rather than restating it.

        Returns `(mutator or None, burns_left)`.
        """
        try:
            state = self.series.state()
        except Exception:  # pragma: no cover - a pre-flight has to answer with something
            # The refusals belong to the burn (`Series.vet`), not to the clock. An
            # estimate that raises leaves the operator with no number at all, which is
            # worse than the number they had before this method existed.
            return None, 1
        run = state.get("run")
        if not state.get("attached"):
            return None, 1
        if not run:
            # No run going, but a list attached: the button above this number is the
            # plain one, and it composes the same sum through `Series.plain_mutators()`.
            # One burn left, because pressing Burn once is all that is due.
            return (self.series.burn_mutators() or [None])[0], 1
        burns = burn_rows(
            self.series.rows(),
            state["used_columns"],
            state["step"],
            state["skip_blank"],
        )
        done = rows_in(run.get("done"))
        left = sum(1 for group in burns if not set(group) <= done)
        # Through `Series.burn_mutators()`, which is the same sum the burn itself, the
        # plain Burn button and the cut-path window read. Its `first` is "the first plate
        # of *this run*", not burn number one of the list: somebody who starts at row 12
        # puts the jig on the bed at that moment.
        return (self.series.burn_mutators() or [None])[0], left

    @contextmanager
    def _as_it_burns(self, mutator):
        """
        The design as the next burn will see it, for as long as it takes to measure it.

        Both estimate routes read the drawing itself — the geometry route walks the
        element tree (`Drawing._geometry_estimate`), the exact one builds the real cut
        plan — and neither has a seam a plan mutator can be handed to. What both *do*
        honour is `hidden`, and honour it identically to a shape not being there at all:
        every operation skips a hidden child on its way to cutcode
        (`core/node/op_cut.py:458`, `op_engrave.py:411`, `op_dots.py:313`, and
        `op_raster.py:492` where the bitmap is made),
        and `Drawing._burnable` skips it for the geometry sum. So this hides exactly what
        the mutator would remove and lets both routes answer about one design.

        That it really is the same answer and not merely a similar one was measured on
        the design in `api/tests/test_series_estimate.py`: the cut plan built with the
        mutator held 172 cut objects and 9.8 s, and the plan built with those same shapes
        hidden instead held **172 cut objects and 9.8 s** — equal to the digit, against
        409 objects and 37.3 s for the design as it stands.
        `test_the_estimate_and_the_burn_agree_to_the_second` keeps it that way.

        Two things this deliberately does not do. It does not touch a shape the user has
        hidden themselves — that shape is not burned either way, and switching it back on
        afterwards would be this route changing their drawing. And it restores in a
        `finally`, because a request that fell over halfway would otherwise leave two
        shapes hidden on somebody's canvas and in the next thing that saves.

        The window is as short as the measurement: 1.2 ms for the geometry route on the
        design above. During it a `GET /api/design` would report those shapes as hidden,
        which is why nothing here signals the canvas — with `exact=1`, which builds the
        whole plan and is for calibration rather than for the UI, that window is minutes.
        """
        if mutator is None:
            yield
            return
        hidden = []
        for node in self.kernel.elements.elems():
            if getattr(node, "hidden", False):
                continue
            # The mutator's own name, on purpose. Whether this burn leaves a shape out is
            # one decision; a second reading of it in the pre-flight is precisely the
            # drift this route was guilty of.
            if mutator._leave_out(node):
                node.hidden = True
                hidden.append(node)
        try:
            yield
        finally:
            for node in hidden:
                node.hidden = False

    def _status_payload(self) -> dict:
        """
        One snapshot, the same everywhere.

        `reader.snapshot()` alone was the kernel and the device status; the tile run was
        missing on the WebSocket (`/api/ws`, which the running app uses) while
        `/api/status` already sent it along. Top bar, canvas and phone view all three
        read the live socket, so without these fields here a running series never
        arrived there — exactly what `_tiling_state`'s docstring promised to prevent.
        """
        payload = self.reader.snapshot()
        payload["tiling"] = self._tiling_state()
        payload["series"] = self._series_state()
        return payload

    def build_app(self):
        from contextlib import asynccontextmanager, contextmanager

        from fastapi import (
            Depends,
            FastAPI,
            HTTPException,
            Request,
            UploadFile,
            WebSocket,
            WebSocketDisconnect,
        )
        from fastapi.responses import HTMLResponse

        def require_write(request: Request):
            if self.local_only:
                return
            if not token_matches(extract_token(request.headers), self.token):
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "Write actions need a token when the API is not bound to "
                        "localhost. Send it as 'Authorization: Bearer <token>'."
                    ),
                )

        write = [Depends(require_write)]

        def act(action, *args):
            """
            Run a write action and turn failure into a 409.

            Engine-side failure keeps its own shape: `detail` is then the command and
            its output, because that is what a developer needs to see. A refusal of
            ours goes through `refuse()` with its code in the header, the same as in
            `manage()`: a route being wrapped in `act()` says the action is a
            command, not that our layer never says no before sending it.
            """
            try:
                return {"ok": True, "output": action(*args)}
            except OUR_REFUSALS as e:
                raise refuse(e) from e
            except CommandError as e:
                raise HTTPException(
                    status_code=409,
                    detail={"command": e.command, "output": e.output},
                ) from e

        def manage(action, *args, **kwargs):
            """
            Same for machine management, where failures are our own.

            The difference from `act()` is the answer on success: this one hands back
            what the action returned, because these routes are asked for state — where
            the head is, what the library holds — and not for whether a command ran.
            The refusal half is `refuse()`, shared with `act()`.
            """
            try:
                return action(*args, **kwargs)
            except OUR_REFUSALS as e:
                raise refuse(e) from e
            except CommandError as e:
                raise HTTPException(
                    status_code=409, detail={"command": e.command, "output": e.output}
                ) from e

        @contextmanager
        def spooling():
            """
            What every burn of ours passes through on its way to the spooler.

            Gap J12: when a zero point is set, the work goes into the machine from
            there. The shift lives only while the plan is being built; after that the
            drawing is back where it was.

            Print and cut goes on top of that as a mutator, and only when the sheet was
            actually aligned — otherwise this is the same single line it always was.
            With an alignment the zero point stays out of it: the pose is measured on
            the material and says where the work goes, which is the same job the zero
            point does by hand. Doing both would shift twice, and you would only see
            that on the workpiece.

            Shared by the ordinary Burn button and a series burn, because a series adds
            no placement of its own — it changes what a text says. Two copies of this
            would be two chances to leave one of the two out, and both of them are
            mistakes you can only see on material.
            """
            pose = self.printcut.mutators()
            origin = None if pose else self.motion.origin()
            with self.drawing.shifted(origin):
                yield pose

        @asynccontextmanager
        async def lifespan(app):
            self.bridge.bind_loop(asyncio.get_running_loop())
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                yield
            finally:
                heartbeat.cancel()

        app = FastAPI(
            title="OpenKerf API",
            version="0.1.0",
            description="Read-only status API on top of the MeerK40t engine.",
            lifespan=lifespan,
        )

        @app.get("/api/health")
        def health():
            return {"ok": True, "clients": self.bridge.client_count}

        @app.get("/api/status")
        def status():
            return self._status_payload()

        @app.get("/api/devices")
        def devices():
            return self.reader.snapshot()["devices"]

        @app.get("/api/design")
        def design():
            """Element outlines and the operations that claim them."""
            snapshot = self.design.snapshot()
            # So that the frontend knows whether opening would throw work away.
            snapshot["dirty"] = self.document.dirty
            return snapshot

        @app.get("/api/capabilities")
        def capabilities():
            """
            Which control actions the *active* device supports. pause/resume/
            estop are registered by the Ruida service, not by the kernel, so
            this changes when the user switches device.
            """
            return {
                "actions": self.commands.capabilities(),
                "motion": self.motion.capabilities(),
                # Gap J11: adjusting during a running job is only possible when the driver
                # has a realtime channel. On a Ruida this is false, and then there should be
                # no button.
                "adjust": self.motion.adjust_capabilities(),
                # Connecting and disconnecting. Every driver family calls it something
                # different and grbl does not know it; what is false here should not be a
                # button.
                "connection": self.motion.connection_capabilities(),
                "auth_required": not self.local_only,
            }

        # ---------------------------------------------------------- write API

        @app.post("/api/job/load", dependencies=write)
        async def load_job(file: UploadFile):
            """
            Upload a drawing and add it to the sheet.

            Importing *adds*. The engine loads a file on top of what is already there
            and that is what a laser cutter wants: a sheet is a plate, and a plate
            holds more than one part. Emptying it first belongs to opening a project,
            which says so.

            So the shapes that came in are reported by id. Whoever imports wants to
            put the new work somewhere, and without those ids the interface cannot
            select it — you would be hunting for what just arrived among what was
            already there.
            """
            target = self._upload_path(file.filename or "upload.svg")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            before = self.design.element_ids()
            result = act(self.commands.load_file, str(target))
            added = [id_ for id_ in self.design.element_ids() if id_ not in before]
            # An empty bed plus a file *is* that file; anything else is a mixture that
            # exists nowhere on disk, so it counts as unsaved work. Marking it clean
            # there would tell the recovery file there is nothing to keep.
            if before:
                self.document.touch()
            else:
                self.document.clean()
            return {**result, "added": added, "count": len(added)}

        @app.post("/api/job/start", dependencies=write)
        def start_job():
            """Plan the current operations and hand the job to the spooler."""
            # The sheet's name as the job name (gap P4): that is what goes into the
            # machine, and it is the only word the user chose themselves. Without this a
            # nameless job is called "Spooler:3 items".
            sheet = self._active_sheet() or {}

            def run():
                # The same gate a series burn passes, and first of all: with a series
                # going this button burns one plate and counts nothing, and it also
                # refuses a text that asks the list for a column it has not got — which
                # today burns a plate with a frame and no name and says nothing at all.
                self.series.vet_plain_job()
                with spooling() as pose:
                    # A list attached without a run going is still a list: the places
                    # this row has no names for read the literal `{name#+2}`, and the
                    # engine engraves those nine characters (`core/wordlist.py:597`
                    # only substitutes when there is a value). So the plain button gets
                    # the same mutator the series burn gets, and the pre-flight can go
                    # on describing the button it is above — measured on one plate of
                    # the last sheetful: 409 cut objects without it, 172 with.
                    #
                    # `first=True` here on purpose: with no run there is no earlier
                    # plate, so a jig marked "burn only once" belongs to this one.
                    mutators = list(pose) + self.series.plain_mutators()
                    return self.commands.start_job(sheet.get("name"), mutators=mutators)

            return act(run)

        @app.get("/api/printcut")
        def printcut_state():
            """Where the sheet lies, as far as we have been told (gap H2)."""
            return self.printcut.state()

        @app.post("/api/printcut/marks", dependencies=write)
        def printcut_marks(body: dict):
            """The two shapes in the drawing that are on the material as well."""
            return manage(self.printcut.set_marks, body.get("ids") or [])

        @app.post("/api/printcut/measure", dependencies=write)
        def printcut_measure(body: dict):
            """
            Where the head is standing now: over mark 1 or mark 2.

            A write route, and not because it changes the drawing — it does not. It reads
            the machine and it decides where a job will burn, and that is the side of the
            line the gate is drawn on.
            """
            return manage(
                self.printcut.measure,
                int(body.get("index", 0)),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.post("/api/printcut/clear", dependencies=write)
        def printcut_clear():
            """Forget the alignment. The next job burns where it was drawn again."""
            return manage(self.printcut.clear)

        @app.post("/api/job/pause", dependencies=write)
        def pause_job():
            return act(self.commands.pause)

        @app.post("/api/job/resume", dependencies=write)
        def resume_job():
            return act(self.commands.resume)

        @app.post("/api/job/stop", dependencies=write)
        def stop_job():
            """Realtime abort. Must stay reachable in one call, always."""
            return act(self.commands.stop)

        @app.post("/api/spooler/clear", dependencies=write)
        def clear_queue():
            return act(self.commands.clear_queue)

        # ------------------------------------------------ tekenen en layers

        @app.post("/api/design/elements", dependencies=write, status_code=201)
        def create_element(body: dict):
            """Draw a shape or a line of text on the bed."""
            kind = body.get("type")
            return manage(lambda: self.drawing.create(kind, **body))

        @app.post("/api/design/clear", dependencies=write)
        def clear_design():
            """Empty the design — what opening does before it reads a file."""
            def run():
                # The same gate as opening a project, and for the same reason: a run
                # counts plates made from *this* drawing, and emptying the bed leaves that
                # count about nothing. Asked before one shape is touched.
                self.series.vet_new_design()
                # Before `clean()`, because that erases the very answer: if this design was
                # already safely on disk, there is nothing left to recover after the
                # clearing and the recovery dialog need not bring it up next time.
                self.autosave.forget_if_saved()
                self.kernel.elements.clear_all()
                self.drawing.user_operations.clear()
                self.document.clean()
                return {"cleared": True}

            return manage(run)

        @app.post("/api/project/new", dependencies=write)
        def new_project():
            """
            Starting over: an empty design, one empty sheet.

            Saving and opening already existed, starting over did not — the only way to
            make a new project was to remove everything by hand, and anybody who forgets
            that burns yesterday's remnants along.

            The library stays. Materials, presets and machine profiles are what you know
            about your laser; they belong not to *this* project but to this workshop. A
            project file does carry them along, because there they go to somebody else.
            """

            def run():
                # See `/api/design/clear`: a running series may not have its drawing
                # replaced, and the refusal comes before anything is emptied.
                self.series.vet_new_design()
                # Before `clean()`: that erases the answer to whether there is anything
                # left to recover. See `/api/design/clear`.
                self.autosave.forget_if_saved()
                self.kernel.elements.clear_all()
                self.drawing.user_operations.clear()
                self.sheets.reset()
                self.provenance.clear()
                self.document.clean()
                return {"new": True, **self.sheets.state()}

            return manage(run)

        @app.get("/api/project/export.openkerf")
        def export_project(filename: str = "project.openkerf"):
            """The design plus its library context in one file."""
            from fastapi.responses import FileResponse

            path = manage(
                self.drawing.export_project, self.library, filename, self.sheets
            )
            self.document.clean()
            return FileResponse(
                path, media_type="application/zip", filename=path.name
            )

        @app.post("/api/project/open", dependencies=write)
        async def open_project(file: UploadFile):
            target = self._upload_path(file.filename or "project.openkerf")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            result = manage(
                self.drawing.import_project, str(target), self.library, self.sheets
            )
            self.document.clean()
            return result

        @app.get("/api/design/elements/{element_id}/image.png")
        def element_image(element_id: str):
            """The pixels of an image, so the canvas can show it."""
            from fastapi.responses import Response

            return Response(
                content=manage(self.images.render_png, element_id),
                media_type="image/png",
            )

        @app.get("/api/design/elements/{element_id}/image")
        def image_adjustments(element_id: str):
            """Which adjustments are on and with what values."""
            return manage(self.images.adjustments, element_id)

        @app.post("/api/design/elements/{element_id}/image", dependencies=write)
        def adjust_image(element_id: str, body: dict):
            if body.get("dpi") is not None:
                return manage(self.images.set_dpi, element_id, body["dpi"])
            if body.get("clear"):
                return manage(self.images.clear_adjustments, element_id)
            return manage(
                self.images.set_adjustment,
                element_id,
                body.get("adjustment"),
                body.get("enabled"),
                body.get("values"),
            )

        @app.get("/api/design/elements/{element_id}/nodes")
        def element_nodes(element_id: str):
            """The nodes of a shape, so they can be dragged separately."""
            return manage(self.nodes.points, element_id)

        @app.patch("/api/design/elements/{element_id}/nodes", dependencies=write)
        def move_element_node(element_id: str, body: dict):
            return manage(
                self.nodes.move_point,
                element_id,
                body.get("index"),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.post("/api/design/elements/{element_id}/nodes", dependencies=write)
        def add_element_node(element_id: str, body: dict):
            """
            A node on a segment: either a place on the bed (a double-click) or a segment
            and a parameter (the menu, which means "the middle of this piece").
            """
            return manage(
                self.nodes.insert_point,
                element_id,
                body.get("segment_index"),
                body.get("t"),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.delete("/api/design/elements/{element_id}/nodes/{index}", dependencies=write)
        def remove_element_node(element_id: str, index: int):
            return manage(self.nodes.remove_point, element_id, index)

        # A kind and a handle sit on a *segment*, not on a node: a curve lives between two
        # points, and addressing it by one of them would leave the question which of the two
        # segments meeting there was meant.
        @app.patch(
            "/api/design/elements/{element_id}/segments/{index}/kind", dependencies=write
        )
        def set_segment_kind(element_id: str, index: int, body: dict):
            return manage(self.nodes.set_kind, element_id, index, body.get("kind"))

        @app.patch(
            "/api/design/elements/{element_id}/segments/{index}/control",
            dependencies=write,
        )
        def move_segment_control(element_id: str, index: int, body: dict):
            return manage(
                self.nodes.move_control,
                element_id,
                index,
                body.get("which"),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.delete("/api/design/elements/{element_id}/crop", dependencies=write)
        def uncrop_image(element_id: str):
            """Undo the crop; the original was never thrown away."""
            return manage(
                self.images.set_adjustment, element_id, "crop", False, None
            )

        @app.post("/api/design/elements/{element_id}/crop", dependencies=write)
        def crop_image(element_id: str, body: dict):
            return manage(
                self.images.crop,
                element_id,
                body.get("x_mm"),
                body.get("y_mm"),
                body.get("width_mm"),
                body.get("height_mm"),
            )

        @app.post("/api/design/elements/{element_id}/vectorise", dependencies=write)
        def vectorise_image(element_id: str, body: dict | None = None):
            method = (body or {}).get("method") or "vectrace"
            return manage(self.images.vectorise, element_id, method)

        @app.get("/api/design/vectorisers")
        def list_vectorisers():
            """Which tracers are loaded — potrace may be missing."""
            return {"methods": self.images.vectorisers()}

        @app.get("/api/design/fonts")
        def list_fonts(refresh: bool = False):
            """
            The typefaces the engine can use.

            The engine keeps that list in a cache file, so a freshly installed typeface only
            appears after `refresh=true`.
            """
            if refresh:
                manage(self.fonts.refresh)
            return manage(self.drawing.fonts)

        @app.get("/api/design/fonts/file")
        def font_file(name: str):
            """
            The typeface file itself, so that the picker can show every name in its own
            typeface — choosing by sight instead of by name.
            """
            from fastapi.responses import FileResponse

            path = manage(self.fonts.preview_file, name)
            return FileResponse(
                path,
                media_type="font/ttf",
                headers={"Cache-Control": "max-age=86400"},
            )

        @app.get("/api/design/fonts/importable")
        def importable_fonts():
            """Fonts on this system the engine does not read, but we do."""
            return manage(self.fonts.importable)

        @app.post("/api/design/fonts/import", dependencies=write, status_code=201)
        def import_font(body: dict):
            return manage(self.fonts.import_font, body.get("file"))

        @app.get("/api/job/layers")
        def job_layers():
            """
            What gets burned and where those settings came from — without the clock.

            Deliberately a route of its own beside `/api/job/estimate`: that builds the
            whole cut plan for the time estimate, and on a heavy design that takes minutes
            (gap J1). A warning that a layer carries a setting for a *different* material
            must not have to queue behind it — that is precisely what you have to know
            before starting. Nothing is planned here: this reads the element tree, the
            library and the provenance.

            For that same reason `bounds` and `engine` ride along here: that a shape falls
            off the bed or that this engine does not burn rasters is not a clock fact but a
            blockage. If it were only in `/api/job/estimate`, "falls outside the bed" would
            only appear once the time estimate was back.
            """
            sheet = self._active_sheet()
            return manage(
                lambda: {
                    "sheet": sheet,
                    "layers": self.drawing.job_layers(
                        self.library, self.provenance, sheet
                    ),
                    "bounds": self.drawing.bounds_report(sheet),
                    "engine": self.drawing.engine_report(),
                    # The pre-flight has to say, before you press start, that the rotary
                    # is on and by how much Y is scaled. A job that silently comes out
                    # stretched costs a workpiece, and there is only one of those.
                    "rotary": self._rotary_state(sheet),
                    # The series, for the same reason as `bounds` and `engine`: that a
                    # text asks the list for a column it has not got is a blockage and
                    # not a clock fact, so it must not have to queue behind the clock.
                    # The clock's own half of a series — the time of this plate and how
                    # many plates are left — rides on `/api/job/estimate` instead, where
                    # the seconds are, and this route says nothing about it: two places
                    # answering "how many burns still to go" is how the panel comes to
                    # show a number that is nobody's. `check()` never raises.
                    "series": self.series.check(),
                }
            )

        @app.get("/api/job/estimate")
        def estimate_job(exact: bool = False):
            """
            What the machine is going to do, before starting: time, parts *and* per layer
            the settings with their provenance.

            `exact=1` computes along the full cut plan, as this route always used to. On a
            heavy design that costs minutes and is only meant for calibrating the fast
            estimate against.

            With a series running, the answer is about the plate now on the bed and about
            nothing else: measured through `_as_it_burns`, so the places the list has no
            rows left for and a jig frame already cut are out of the sum instead of in it
            — see `_series_burn` for the numbers and for why the plain Burn button gets
            no such treatment.

            `burns_left` and `seconds_total` are the whole answer to "how long is this
            afternoon". `seconds_total` is `seconds` — the rounded one, so that a client
            showing both cannot show two numbers that do not multiply — times the burns
            still due. It is this plate's time and not the afternoon's exactly, and it
            cannot be: the names differ in length (measured, one tag per plate over
            Anna/Bram/Cees/Daan/Eva: 4.9, 5.5, 5.2, 5.4 and 3.9 s — 41 % between the
            shortest and the longest), the last sheetful is short and the first plate
            carries the jig. Measuring every plate for real would mean re-rendering the
            list row by row on a GET, which moves the bed the operator is looking at.
            What this number can be trusted about is the thing it exists for — that a
            list of fifty never shows the time of one.

            Without a series `burns_left` is 1 and `seconds_total` equals `seconds`, so
            the pre-flight has one field to draw and no branch of its own.
            """
            mutator, burns_left = self._series_burn()

            def measure():
                with self._as_it_burns(mutator):
                    answer = self.drawing.estimate(
                        self.library,
                        self.provenance,
                        self._active_sheet(),
                        exact=exact,
                    )
                return {
                    **answer,
                    "burns_left": burns_left,
                    "seconds_total": round(answer["seconds"] * burns_left, 1),
                }

            return manage(measure)

        @app.get("/api/job/path")
        def job_path():
            """
            The ordered path of the current design: what the machine does, when.

            Answers at once, always. Building the plan is the most expensive thing
            this API does (measured: 2.5 s on 960 squares, and quadratic above
            that), so the build runs in a thread and this route says which of five
            things is true: `ready` with the path, `building` with how long it has
            been at it, `empty`, `too_big` with the numbers, `busy` because a job
            claimed the plan, or `failed`. The client polls; nothing here waits.

            The answer is cached against a fingerprint of the design, so a poll on
            an untouched drawing costs the fingerprint and nothing else (measured:
            0.017 s on 960 shapes against 2.5 s for the plan).
            """
            return manage(lambda: self.cutpath.state(self.motion.origin()))

        @app.get("/api/design/export.svg")
        def export_design(filename: str = "ontwerp.svg"):
            """Download the design as SVG — otherwise the work is fleeting."""
            from fastapi.responses import FileResponse

            path = manage(self.drawing.export_svg, filename)
            self.document.clean()
            return FileResponse(
                path, media_type="image/svg+xml", filename=path.name
            )

        @app.patch("/api/design/elements/{element_id}/line", dependencies=write)
        def update_line(element_id: str, body: dict):
            """Move one end; a line is two points, not a box."""
            return manage(lambda: self.drawing.update_line(element_id, **body))

        @app.get("/api/design/duplicates")
        def count_duplicates(ids: str | None = None):
            """
            How many shapes lie on top of each other, without touching anything.

            Looking first, because removing them changes nothing you can see: the
            drawing looks the same and only the count says what happened. So the
            interface asks with the number in the question.
            """
            picked = [i for i in (ids or "").split(",") if i]
            return manage(lambda: self.duplicates.find(picked or None))

        @app.post("/api/design/duplicates/remove", dependencies=write)
        def remove_duplicates(body: dict):
            return manage(lambda: self.duplicates.remove(body.get("ids")))

        @app.post("/api/design/lock", dependencies=write)
        def lock_elements(body: dict):
            """
            Lock or unlock the selection: protected from moving, sizing and deleting.

            One route for both directions, with the wanted state in the body, because
            a selection can hold a mix of the two and "make these locked" is the
            operation a user means — not "toggle each of them", which on a mixed
            selection leaves you with the other half of the mess.
            """
            return manage(
                lambda: self.drawing.set_locked(body.get("ids"), body.get("locked", True))
            )

        @app.post("/api/design/bridges", dependencies=write)
        def set_bridges(body: dict):
            """
            Bridges (tabs) in a cut line, on the whole selection at once.

            A collection route and not a route per element, because a bridge is something
            you put on every part you are about to cut loose: the answer says how many
            shapes got them and how many were skipped for their type.
            """
            return manage(
                lambda: self.drawing.set_bridges(
                    body.get("ids"),
                    count=body.get("count"),
                    length_mm=body.get("length_mm"),
                    positions_percent=body.get("positions_percent"),
                )
            )

        # A POST and not a DELETE: the ids are in the body, and this API sends a body only
        # on POST and PATCH — `element delete` does it the same way.
        @app.post("/api/design/bridges/clear", dependencies=write)
        def clear_bridges(body: dict):
            return manage(self.drawing.clear_bridges, body.get("ids"))

        @app.post("/api/design/offset", dependencies=write)
        def offset_elements(body: dict):
            return manage(self.drawing.offset, body.get("ids"), body.get("distance_mm"))

        @app.post("/api/design/corners", dependencies=write)
        def corner_elements(body: dict):
            """
            Hoeken afronden of afschuinen.

            Rounding a rectangle stays a rectangle (the engine draws that with `rx`/`ry`);
            everything else becomes a path, and that is one-way.
            """
            return manage(
                self.drawing.corners,
                body.get("ids"),
                body.get("style") or "round",
                body.get("size_mm"),
            )

        @app.post("/api/design/simplify", dependencies=write)
        def simplify_elements(body: dict):
            return manage(self.drawing.simplify, body.get("ids"))

        @app.post("/api/design/effect", dependencies=write)
        def add_effect(body: dict):
            return manage(self.drawing.add_effect, body.get("ids"), body.get("effect"))

        @app.post("/api/design/mirror", dependencies=write)
        def mirror_elements(body: dict):
            return manage(self.drawing.mirror, body.get("ids"), body.get("axis"))

        @app.post("/api/design/boolean", dependencies=write)
        def boolean_elements(body: dict):
            """Unite, subtract, intersect or exclude."""
            return manage(self.drawing.boolean, body.get("ids"), body.get("operation"))

        @app.post("/api/design/align", dependencies=write)
        def align_elements(body: dict):
            return manage(self.drawing.align, body.get("ids"), body.get("mode"))

        @app.post("/api/design/group", dependencies=write)
        def group_elements(body: dict):
            return manage(self.drawing.group, body.get("ids"))

        @app.post("/api/design/ungroup", dependencies=write)
        def ungroup_elements(body: dict):
            return manage(self.drawing.ungroup, body.get("ids"))

        # ------------------------------------------------------- beweging

        @app.post("/api/machine/home", dependencies=write)
        def machine_home(body: dict | None = None):
            """
            To the zero point. The head really moves.

            Refused while the rotary is on: homing Y runs the head into a fitted chuck.
            `force` is the way through for whoever has taken it out — see rotary.py.
            """
            fields = body or {}
            return manage(
                self.motion.home,
                bool(fields.get("physical")),
                bool(fields.get("force")),
            )

        # -- the rotary (machine-wide) — see rotary.py ----------------------
        @app.get("/api/machine/rotary")
        def machine_rotary():
            """
            How this machine's rotary is set up, and what it does to a job.

            `work_height_mm` is optional and answers the one question the circumference
            answers: does this design go round the object once without overlapping itself.
            """
            return manage(lambda: self._rotary_state(self._active_sheet()))

        @app.post("/api/machine/rotary", dependencies=write)
        def set_machine_rotary(body: dict | None = None):
            """Change what was given; the rest stays. Refuses a rotary that cannot burn."""
            return manage(self.rotary.update, body or {})

        @app.post("/api/machine/rotary/calibrate", dependencies=write)
        def calibrate_machine_rotary(body: dict):
            """"Meant 100 mm, measured 96.5" -> the new Y factor."""
            return manage(
                self.rotary.calibrate, body.get("commanded_mm"), body.get("measured_mm")
            )

        # -- end of the rotary block ----------------------------------------

        @app.post("/api/machine/move", dependencies=write)
        def machine_move(body: dict):
            return manage(self.motion.move_to, body.get("x_mm"), body.get("y_mm"))

        @app.post("/api/machine/jog", dependencies=write)
        def machine_jog(body: dict):
            return manage(self.motion.jog, body.get("dx_mm"), body.get("dy_mm"))

        # -- saved positions (gap J6) — a block of its own, see machine.py ---
        @app.get("/api/machine/positions")
        def machine_positions():
            """Positions this machine remembers: a jig, the zero of a fixture."""
            return manage(lambda: {"positions": self.motion.positions()})

        @app.post("/api/machine/positions", dependencies=write, status_code=201)
        def save_machine_position(body: dict):
            """Without x/y: where the head is now."""
            return manage(
                self.motion.save_position,
                body.get("name"),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.delete("/api/machine/positions", dependencies=write)
        def delete_machine_position(name: str):
            return manage(self.motion.delete_position, name)

        # -- end of the positions block --------------------------------------

        # -- user origin (gap J12) — see machine.py -------------------------
        @app.get("/api/machine/origin")
        def machine_origin():
            """The zero point of this machine, or null when none is set."""
            return manage(lambda: {"origin": self.motion.origin()})

        @app.post("/api/machine/origin", dependencies=write)
        def set_machine_origin(body: dict | None = None):
            """Without x/y: where the head is now."""
            fields = body or {}
            return manage(
                self.motion.set_origin, fields.get("x_mm"), fields.get("y_mm")
            )

        @app.delete("/api/machine/origin", dependencies=write)
        def clear_machine_origin():
            return manage(self.motion.clear_origin)

        # -- adjusting during a running job (gap J11) -----------------------
        @app.get("/api/job/adjust")
        def job_adjustment():
            """What is adjusted right now, and whether this machine can do it at all."""
            return manage(self.motion.adjustment)

        @app.post("/api/job/adjust", dependencies=write)
        def adjust_job(body: dict):
            """Scale speed and/or power, even in the middle of a job."""
            return manage(self.motion.adjust, body.get("power"), body.get("speed"))

        @app.post("/api/machine/focus", dependencies=write)
        def focus_machine(body: dict):
            """Focusing: the head higher or lower. Only when the device knows it."""
            return manage(self.motion.focus, body.get("distance_mm"))

        @app.post("/api/machine/frame", dependencies=write)
        def frame_design(body: dict | None = None):
            """
            Sending the head around the outline of the work, without burning.

            Without measures in the request it takes the bounding rectangle of what is on
            the bed now — that is what you want to check.
            """
            def run():
                fields = body or {}
                if fields.get("width_mm"):
                    return self.motion.frame(
                        fields.get("x_mm"), fields.get("y_mm"),
                        fields.get("width_mm"), fields.get("height_mm"),
                    )
                doos = self.design.bounds_mm()
                if doos is None:
                    raise DesignError("There is nothing on the bed to frame.")
                # Gap J12: framing has to show where it will *really* lie. A frame on the
                # drawing coordinates while the zero point puts the work 100 mm aside is
                # precisely the check you thought you had made.
                origin = self.motion.origin() or {}
                x, y, width, height = doos
                return self.motion.frame(
                    x + float(origin.get("x_mm") or 0.0),
                    y + float(origin.get("y_mm") or 0.0),
                    width,
                    height,
                )

            return manage(run)

        @app.post("/api/machine/connect", dependencies=write)
        def connect_machine():
            """
            Opening the connection.

            Moves nothing. The engine reports a failed attempt only on the console channel
            and then returns neatly, so we look at the state afterwards and pass the message
            on — otherwise this is a button that silently does nothing.
            """
            return manage(self.motion.connect)

        @app.post("/api/machine/disconnect", dependencies=write)
        def disconnect_machine():
            return manage(self.motion.disconnect)

        @app.post("/api/machine/unlock", dependencies=write)
        def machine_unlock():
            return manage(self.motion.unlock)

        @app.post("/api/machine/lock", dependencies=write)
        def machine_lock():
            return manage(self.motion.lock)

        @app.patch("/api/design/elements/{element_id}/text", dependencies=write)
        def update_text(element_id: str, body: dict):
            """Update existing text instead of throwing it away and placing it again."""
            return manage(lambda: self.drawing.update_text(element_id, **body))

        @app.post("/api/design/elements/{element_id}/once", dependencies=write)
        def element_once(element_id: str, body: dict | None = None):
            """
            Burn this shape only once in a series, or on every plate again.

            One shape per call, because that is what the menu row acts on: the flag is
            about a jig frame or a set of pockets, not about a selection of fifty. Absent
            `once` means switching it on — the row that turns it off says so and sends
            false.
            """
            want = True if body is None else bool(body.get("once", True))
            return manage(lambda: self.drawing.once([element_id], want))

        @app.post("/api/design/elements/delete", dependencies=write)
        def delete_elements(body: dict):
            return manage(self.drawing.delete, body.get("ids"))

        @app.post("/api/design/elements/duplicate", dependencies=write)
        def duplicate_elements(body: dict):
            return manage(self.drawing.duplicate, body.get("ids"))

        @app.get("/api/design/clipboard")
        def clipboard_state():
            """What is on the clipboard — the menu has to know whether pasting is possible."""
            return manage(self.drawing.clipboard_state)

        @app.post("/api/design/clipboard/copy", dependencies=write)
        def clipboard_copy(body: dict):
            return manage(self.drawing.clipboard_copy, body.get("ids"))

        @app.post("/api/design/clipboard/cut", dependencies=write)
        def clipboard_cut(body: dict):
            return manage(self.drawing.clipboard_cut, body.get("ids"))

        @app.post("/api/design/clipboard/paste", dependencies=write)
        def clipboard_paste(body: dict):
            return manage(
                self.drawing.clipboard_paste, body.get("x_mm"), body.get("y_mm")
            )

        @app.post("/api/design/operations", dependencies=write, status_code=201)
        def create_operation(body: dict):
            return manage(
                self.drawing.create_operation,
                body.get("type"),
                body.get("label"),
                body.get("speed"),
                body.get("power_percent"),
            )

        @app.patch("/api/design/operations/{operation_id}", dependencies=write)
        def update_operation(operation_id: str, body: dict):
            def run():
                result = self.drawing.update_operation(operation_id, **body)
                # Decision B2: the colour remembers what you last did with it.
                self._remember_layer(operation_id)
                return result

            return manage(run)

        # ------------------------------------------------------- palet (B2)

        @app.get("/api/design/palette")
        def design_palette():
            """
            The colour strip under the canvas: ten colours with their memory.

            Only the memory comes from here. *Which* layer has which colour is already in
            `/api/design` — sending that twice is two truths that can drift apart.
            """
            key, name = self._palette_machine()
            remembered = self.palette.all(key)
            return {
                "machine": {"key": key, "name": name},
                "default_color": self.drawing.default_color(),
                "colors": [
                    {"color": colour.lower(), "memory": remembered.get(colour.lower())}
                    for colour in self.drawing.PALETTE
                ],
            }

        @app.post("/api/design/palette", dependencies=write)
        def use_palette_color(body: dict):
            """
            One click on a palette swatch.

            With a selection: it moves to the layer of that colour, which is created if
            need be on what that colour did before. Without a selection: the colour for new
            work. That distinction comes from LightBurn and is the reason assigning is one
            action there and was three with us.
            """
            colour = body.get("color")
            ids = body.get("ids") or []
            key, _naam = self._palette_machine()

            def run():
                memory = self.palette.recall(key, colour)
                if ids:
                    result = self.drawing.paint(ids, colour, memory)
                    self._remember_layer(result["operation_id"])
                    return result
                return {**self.drawing.set_default_color(colour), "operation_id": None}

            return manage(run)

        @app.get("/api/design/capabilities")
        def design_capabilities():
            """
            What a layer can do on *this* machine (decision B11).

            Air assist is a switch in the row, but only when the driver knows a command for
            it — the same rule as with the Z axis. What the machine cannot do does not belong
            on the screen as a button.
            """
            return {
                "air_assist": self.drawing.air_assist_supported(),
                "z_step": self.drawing.z_step_supported(),
            }

        @app.post("/api/design/operations/sort", dependencies=write)
        def sort_operations():
            """Engrave before cut, in one action (gap L2)."""
            return manage(self.drawing.sort_operations)

        @app.post("/api/design/operations/{operation_id}/move", dependencies=write)
        def move_operation(operation_id: str, body: dict):
            """
            Moving a layer in the burn order.

            `direction` is one step (the buttons), `index` is a destination (dragging, gap
            L1).
            """
            return manage(
                lambda: self.drawing.move_operation(
                    operation_id, body.get("direction"), body.get("index")
                )
            )

        @app.post("/api/design/operations/{operation_id}/type", dependencies=write)
        def retype_operation(operation_id: str, body: dict):
            """
            Turning a cut layer into an engrave layer, with the shapes in it (gap L3).

            A route of its own and not a PATCH: the layer is replaced and gets a new id.
            Doing that silently under a PATCH would mean the caller afterwards refers to a
            layer that no longer exists.
            """
            return manage(
                lambda: self.drawing.change_operation_type(
                    operation_id, body.get("type")
                )
            )

        # Before the route with `{operation_id}`: otherwise that one catches this path.
        @app.delete("/api/design/operations", dependencies=write)
        def delete_all_operations():
            """Every ordinary layer gone; the shapes stay."""
            return manage(self.drawing.delete_all_operations)

        @app.delete("/api/design/operations/{operation_id}", dependencies=write)
        def delete_operation(operation_id: str):
            return manage(self.drawing.delete_operation, operation_id)

        # ------------------------------------------------------- design edits

        @app.post("/api/design/move", dependencies=write)
        def move_elements(body: dict):
            return manage(
                self.editor.move, body.get("ids"), body.get("dx_mm"), body.get("dy_mm")
            )

        @app.post("/api/design/resize", dependencies=write)
        def resize_elements(body: dict):
            return manage(
                self.editor.resize,
                body.get("ids"),
                body.get("x_mm"),
                body.get("y_mm"),
                body.get("width_mm"),
                body.get("height_mm"),
            )

        @app.post("/api/design/rotate", dependencies=write)
        def rotate_elements(body: dict):
            return manage(
                self.editor.rotate,
                body.get("ids"),
                body.get("angle_deg"),
                bool(body.get("absolute", False)),
            )

        @app.post("/api/design/split", dependencies=write)
        def split_elements(body: dict):
            """
            Splitting a path into its separate pieces.

            A CAD export is often one path with dozens of subpaths; nothing in it can be
            clicked separately. After this every piece is a shape of its own.
            """
            return manage(self.editor.split, body.get("ids"))

        @app.post("/api/design/fill", dependencies=write)
        def fill_elements(body: dict):
            """
            Giving a shape a fill, or taking it off.

            Needed to be able to grid something you drew yourself: the rasteriser fills
            what has a fill and otherwise only draws a line.
            """
            return manage(
                self.drawing.fill,
                body.get("ids"),
                body.get("filled", True),
                body.get("color"),
            )

        @app.post("/api/design/single-layer", dependencies=write)
        def single_layer(body: dict):
            """The selection in one layer, and out of all the others."""
            return manage(
                self.drawing.single_layer,
                body.get("ids"),
                body.get("type") or "cut",
                body.get("operation_id"),
            )

        @app.post("/api/design/operations/prune", dependencies=write)
        def prune_operations():
            """Empty layers gone — an empty project has twelve of them."""
            return manage(self.drawing.prune_operations)

        @app.post("/api/design/assign", dependencies=write)
        def assign_elements(body: dict):
            """Add the elements to an operation — a layer in the UI."""
            return manage(self.editor.assign, body.get("ids"), body.get("operation_id"))

        @app.post("/api/design/unassign", dependencies=write)
        def unassign_elements(body: dict):
            return manage(self.editor.unassign, body.get("ids"), body.get("operation_id"))

        @app.post("/api/design/undo", dependencies=write)
        def undo_design():
            return manage(self.editor.undo)

        @app.post("/api/design/redo", dependencies=write)
        def redo_design():
            return manage(self.editor.redo)

        # ------------------------------------------------- materiaalbibliotheek

        @app.get("/api/library/materials")
        def list_materials():
            return self.library.materials()

        @app.post("/api/library/materials", dependencies=write, status_code=201)
        def add_material(body: dict):
            return manage(self.library.add_material, body.get("name"), body.get("synonyms"))

        @app.get("/api/library/materials/{material_id}/usage")
        def material_usage(material_id: int):
            """
            What hangs off this material, before anybody presses Remove.

            The dialog has to be able to name the count. Removing `Berkentriplex` from a
            copy of the author's library took six settings with it — two of them measured,
            with photographs — orphaned two boards and answered `{"removed": 6}`; a
            confirmation that says "remove?" and nothing else is what made that possible.
            """
            return manage(self.library.material_usage, material_id)

        @app.patch("/api/library/materials/{material_id}", dependencies=write)
        def update_material(material_id: int, body: dict):
            """
            Rename a material, or give it another word people call it by.

            There was no PATCH here at all, which is why the live library holds both
            `Multiplex berken` and `Berkentriplex` for one board: the only way to fix a
            typo was to add a second material beside the first.
            """
            return manage(
                self.library.update_material,
                material_id,
                body.get("name"),
                body.get("synonyms"),
            )

        @app.post(
            "/api/library/materials/{material_id}/merge-into/{target_id}",
            dependencies=write,
        )
        def merge_material(material_id: int, target_id: int):
            """Two names for one board, joined — settings, boards and recipes with them."""
            return manage(self.library.merge_material, material_id, target_id)

        @app.delete("/api/library/materials/{material_id}", dependencies=write)
        def remove_material(material_id: int, with_everything: bool = False):
            """
            Remove a material — refused while work hangs off it, unless you say so.

            `with_everything` is a deliberate second word and not a default, because the
            cascade behind it is `preset` CASCADE, `grid_recipe` CASCADE and
            `test_grid.material_id` SET NULL: the bare DELETE this route used to be was a
            data-loss button with a one-word label. The flag is a query parameter rather
            than a body because DELETE bodies do not survive every client.
            """
            return manage(
                self.library.remove_material, material_id, with_everything=with_everything
            )

        @app.get("/api/library/presets")
        def list_presets(
            material_id: int | None = None,
            operation: str | None = None,
            all_machines: bool = False,
        ):
            """
            The presets, by default of the machine that is active now.

            A preset holds for one laser on one material; showing everything mixed together
            is the confusion this solves. `all_machines=true` shows the rest as well.
            """
            profile = None if all_machines else self._active_profile()
            return self.library.presets(
                material_id, operation, profile["id"] if profile else None
            )

        @app.get("/api/library/active-machine")
        def active_machine():
            """
            The active machine's profile, freshly created if need be.

            The frontend needs this to say whose presets you are looking at, and to know
            whether there is a Z axis or autofocus.
            """
            profile = self._active_profile()
            if profile is None:
                raise HTTPException(status_code=409, detail="There is no active machine.")
            # The offer rides along, so no surface needs a second call to find out
            # whether this machine has anything at all. It costs six COUNT(*)s over the
            # library and no network at all — see Starter.offer.
            offer = self.starter.offer(profile)
            return {
                **profile,
                "starter": {k: v for k, v in offer.items() if k != "machine"},
            }

        @app.get("/api/library/starter")
        def starter_offer():
            """
            Whether this machine should be offered a set of starting points.

            Its own route as well as a field on `/api/library/active-machine`, because
            two surfaces ask it — the material library on opening and `/setup/done` at
            the end of the wizard — and the second one has no reason to fetch a profile
            it has just written. A machine that is not active answers `needed: false`
            rather than a refusal: that is a normal state, not a fault.
            """
            return self.starter.offer(self._active_profile())

        @app.post("/api/library/starter/dismiss", dependencies=write)
        def dismiss_starter(body: dict | None = None):
            """
            What the user said about starting points for this machine: not now, or
            "I don't know what my tube is".

            One route for both, because both are the same column and the card offers
            them side by side. `power_unknown` is not a dismissal — it keeps the offer
            and drops the wattage half of the match — but it is the same fact being
            recorded, and a second route would let the two get out of step.
            """
            return manage(
                self.starter.dismiss,
                self._active_profile(),
                (body or {}).get("state") or "dismissed",
            )

        @app.patch("/api/library/machines/{machine_id}", dependencies=write)
        def update_machine(machine_id: int, body: dict):
            return manage(self.library.update_machine, machine_id, body)

        @app.post("/api/library/presets", dependencies=write, status_code=201)
        def add_preset(body: dict):
            # Without a profile a preset hangs in mid-air; the active machine is the only
            # sensible default answer.
            fields = dict(body)
            if not fields.get("machine_id"):
                profile = self._active_profile()
                if profile:
                    fields["machine_id"] = profile["id"]
            return manage(lambda: self.library.add_preset(**fields))

        @app.patch("/api/library/presets/{preset_id}", dependencies=write)
        def update_preset(preset_id: int, body: dict):
            return manage(lambda: self.library.update_preset(preset_id, **body))

        @app.get("/api/library/suggest")
        def suggest_grid_range(
            material_id: int | None = None,
            operation: str | None = None,
            thickness_mm: float | None = None,
        ):
            """A suggested grid range around existing presets."""
            return self.library.suggest_range(material_id, operation, thickness_mm)

        @app.delete("/api/library/presets/{preset_id}", dependencies=write)
        def remove_preset(preset_id: int):
            return manage(self.library.remove_preset, preset_id)

        @app.get("/api/library/machines")
        def list_machine_profiles():
            """
            The machine profiles, with the question of whether the machine still exists.

            A profile outlives its device: the library sits beside the engine and does not
            follow along when somebody throws a machine away or wipes the engine's settings.
            Without this flag the list fills up with names that have nothing behind them,
            and then "for this machine" says nothing any more.

            Only configured machines count. Profiles the old version created for MeerK40t's
            lhystudios stand-in otherwise sit there as a live machine while nobody chose
            them — precisely the names that polluted the list.

            A profile with no device path at all is orphaned too, and that half was
            missing: the rule read `bool(device_path) and device_path not in paths`, so a
            row that never had a device could not fail it. Measured on the author's
            library, that is how `5030 CO2` — 27 presets, 60 W, `device_path: null` — was
            presented as a live machine attached to nothing, and it is one of the four
            mechanisms behind "the machines it names are not the machines I defined".

            The two states are told apart rather than merged, because the answer differs:
            a profile whose device is not here may get it back (plug it in, or the engine's
            settings were wiped), while one that points at no device at all is either a row
            somebody typed or one this library let go of when its slot was handed to a
            different laser, and its way out is a merge into the machine it belongs to.
            `no-device` says exactly that and no more — nothing records which of the two it
            was, so naming it "never attached" would claim a history the database does not
            hold.
            """
            live = {
                device.path: str(getattr(device, "label", "") or device.path)
                for device in self.kernel.services("device")
                if self.machines._configured(device)
            }
            self.library.refresh_names(live)
            paths = set(live)

            def attachment(profile) -> str | None:
                if not profile["device_path"]:
                    return "no-device"
                if profile["device_path"] not in paths:
                    return "device-gone"
                return None

            return [
                {
                    **profile,
                    "orphaned": attachment(profile) is not None,
                    "orphaned_because": attachment(profile),
                    **self.library.machine_usage(profile["id"]),
                }
                for profile in self.library.machines()
            ]

        @app.delete("/api/library/machines/{machine_id}", dependencies=write)
        def remove_machine_profile(machine_id: int):
            # The machine you are working on now keeps its profile. It would not be gone
            # anyway: the next read route creates it again, and then the only difference is
            # that all the presets that hung off it have come loose.
            active = self._active_profile()
            if active and active["id"] == machine_id:
                raise HTTPException(
                    status_code=409,
                    detail="This is the machine you are working on; it cannot go.",
                )
            return manage(self.library.remove_machine, machine_id)

        @app.post(
            "/api/library/machines/{machine_id}/merge-into/{target_id}",
            dependencies=write,
        )
        def merge_machine_profile(machine_id: int, target_id: int):
            """
            Two profiles for one laser, joined into the one you are working on.

            The case this exists for is measured: the author's library holds a device-less
            `5030 CO2` with 60 W and 27 presets beside the device-bound `KH-5030` with 3
            presets and no wattage, and they are one machine. `_dedupe_machines` cannot
            reach it — it only merges rows that share a device path, and the unique index
            it creates keeps that case from ever arising.

            Which slots hold a real machine, and which one is active, are facts about the
            engine that the library has no way to know, so they go in from here. Both
            refusals depend on them: two profiles that each belong to a machine that
            exists are two lasers, and merging the machine you are working on *away* would
            leave you working on the row that no longer exists.
            """
            device = getattr(self.kernel, "device", None)
            return manage(
                self.library.merge_machine,
                machine_id,
                target_id,
                live_paths=self._live_device_paths(),
                active_path=getattr(device, "path", None),
            )

        @app.post("/api/library/machines", dependencies=write, status_code=201)
        def add_machine_profile(body: dict):
            return manage(lambda: self.library.add_machine(**body))

        @app.post("/api/library/presets/adopt", dependencies=write)
        def adopt_presets(body: dict | None = None):
            """
            The settings and boards that belong to no machine, onto the active one.

            Never by itself. Four presets and eleven boards in the author's library carry
            `machine_id IS NULL` — measured on a machine nobody can name, the fingerprint
            of the lhystudios-fallback state — and `Library.presets()` shows them on every
            machine because its WHERE reads `machine_id = ? OR machine_id IS NULL`.
            Adopting them says they were measured here, which may be false; leaving them
            says they hold everywhere, which is false too. Only the user knows, so this is
            a button and the interface states the count beside it.
            """
            machine_id = (body or {}).get("machine_id")
            if not machine_id:
                profile = self._active_profile()
                machine_id = profile["id"] if profile else None
            return manage(self.library.adopt_presets, machine_id)

        # ------------------------------------------------ library exchange (B7)

        @app.get("/api/library/export.openkerf-lib")
        def export_library(filename: str = "library"):
            """The whole library as one file, photos included."""
            from fastapi.responses import FileResponse

            path = manage(self.library.export_bundle, filename)
            return FileResponse(
                path, media_type="application/zip", filename=path.name
            )

        @app.post("/api/library/import/upload", dependencies=write)
        async def upload_library(file: UploadFile):
            """
            Accept the file and say what it would do — nothing more yet.

            It stays under its own name in the upload directory, so that the preview can be
            recomputed without uploading again.
            """
            target = self._upload_path(file.filename or f"library{BUNDLE_SUFFIX}")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            preview = manage(self.library.preview_import, target)
            return {"bundle": target.name, **preview}

        def _bundle(body: dict) -> Path:
            name = Path(str(body.get("bundle") or "")).name
            if not name:
                raise HTTPException(status_code=422, detail="Choose a file first.")
            return self._upload_path(name)

        @app.post("/api/library/import/preview", dependencies=write)
        def preview_library(body: dict):
            """The same preview, recalculated with the merge choices in it."""
            target = _bundle(body)
            preview = manage(
                self.library.preview_import, target, body.get("merge_materials")
            )
            return {"bundle": target.name, **preview}

        @app.post("/api/library/import", dependencies=write)
        def import_library(body: dict):
            target = _bundle(body)
            # Which material lay on which sheet, by name: on a replace, materials get new
            # ids and the sheet would otherwise point at nothing.
            names = {m["id"]: m["name"] for m in self.library.materials()}
            sheet_names = {
                s["id"]: names.get(s.get("material_id"))
                for s in self.sheets.state()["sheets"]
            }
            result = manage(
                self.library.import_bundle,
                target,
                body.get("mode") or "merge",
                body.get("merge_materials"),
                body.get("on_conflict") or "mine",
                # The batch this import belongs to, if it is one that can be taken back.
                # `POST /api/presetariat/stage` mints the name and the client hands it
                # straight back here; a plain restore-from-backup sends nothing, because
                # there is nothing to undo about your own library arriving.
                str(body.get("import_batch") or ""),
            )
            again = {m["name"]: m["id"] for m in self.library.materials()}
            for sheet_id, name in sheet_names.items():
                if name and again.get(name) is not None:
                    self.sheets.update(sheet_id, material_id=again[name])
            # And back out again, so the answer itself names the way to undo it. A client
            # that has to remember a string it sent two requests ago is a client that
            # will lose it.
            return {**result, "import_batch": str(body.get("import_batch") or "")}

        @app.delete("/api/library/imports/{batch}", dependencies=write)
        def remove_import_batch(batch: str):
            """
            Take one import back: its settings, and the materials it brought with them.

            This is the answer to the state the author is actually in — 26 imported
            presets that created 14 materials for a machine he does not run, and no way
            back. An import you can undo is not a dump, which is why the batch stamp and
            this route are the first line of defence and not a check in another repository.

            Materials the batch created that something else now uses stay; the answer
            names both lists, because "3 removed, 1 kept" is a sentence a reader can check
            and "done" is not.
            """
            return manage(self.library.remove_import_batch, batch)

        @app.post("/api/library/presets/{preset_id}/apply", dependencies=write)
        def apply_preset(preset_id: int, body: dict):
            """Write a preset's speed, power and passes onto an operation."""
            operation_id = body.get("operation_id")
            if not operation_id:
                raise HTTPException(status_code=422, detail="'operation_id' is missing.")

            def run():
                preset = self.library.preset(preset_id)
                result = self.editor.apply_settings(
                    operation_id,
                    speed=preset["speed_mm_s"],
                    power_percent=preset["power_percent"],
                    passes=preset["passes"],
                )
                # Only after a successful application: a failed attempt is not use, and
                # "recently used" has to stay true.
                self.library.touch_preset(preset_id)
                # And remember *where* these numbers came from. Without that note the
                # pre-flight has to guess the provenance from the values, and then a setting
                # for another material cannot be seen.
                self.provenance.record(self.sheets.active_id, operation_id, preset)
                # And the palette remembers what this colour does now. That is something
                # other than the provenance above: the memory carries no evidence, only the
                # habit (see palette.py).
                self._remember_layer(operation_id)
                return {**result, "preset": preset}

            return manage(run)

        # ---------------------------------------------------------------- camera

        @app.get("/api/camera")
        def camera_state():
            """Whether there is a camera, whether it runs, and whether it is calibrated."""
            return self.camera.state()

        @app.get("/api/camera/list")
        def camera_list():
            return manage(self.camera.cameras)

        @app.post("/api/camera/start", dependencies=write)
        def camera_start(body: dict | None = None):
            return manage(self.camera.start, (body or {}).get("uri"))

        @app.post("/api/camera/stop", dependencies=write)
        def camera_stop():
            return manage(self.camera.stop)

        @app.get("/api/camera/frame.png")
        def camera_frame():
            """One frame — for calibrating, and as a fallback without a stream."""
            from fastapi.responses import Response

            return Response(
                content=manage(self.camera.frame_png),
                media_type="image/png",
                # Every request has to produce a fresh image; a cached image of the bed is
                # exactly what you do not want.
                headers={"Cache-Control": "no-store"},
            )

        @app.get("/api/camera/stream.mjpeg")
        async def camera_stream(request: Request):
            """
            A continuous image. The browser puts this in an ordinary <img> and decodes it
            itself — no JavaScript loop, no stuttering.

            The loop asks on every round whether the browser is still listening. Without
            that question the server does not notice a closed tab and the camera keeps
            running for a viewer who is no longer there; that is exactly what happened when
            this was an ordinary generator.
            """
            import anyio
            from fastapi.responses import StreamingResponse

            if not self.camera.available:
                raise HTTPException(status_code=409, detail=CAMERA_HINT)

            async def frames():
                with self.camera.viewer():
                    last = None
                    while not await request.is_disconnected():
                        part, last = await anyio.to_thread.run_sync(
                            self.camera.next_part, last
                        )
                        if part is None:
                            await anyio.sleep(0.04)
                            continue
                        yield part

            return StreamingResponse(
                frames(),
                media_type="multipart/x-mixed-replace; boundary=frame",
                headers={"Cache-Control": "no-store"},
            )

        @app.post("/api/camera/calibrate", dependencies=write)
        def camera_calibrate(body: dict):
            """The four bed corners in the image: top left, clockwise."""
            return manage(
                self.camera.calibrate, body.get("points"), body.get("corrected")
            )

        @app.delete("/api/camera/calibrate", dependencies=write)
        def camera_reset_calibration():
            return manage(self.camera.reset_calibration)

        @app.post("/api/camera/corrected", dependencies=write)
        def camera_corrected(body: dict):
            """While calibrating you want to see the unprocessed image."""
            return manage(self.camera.set_corrected, bool(body.get("corrected")))

        # ----------------------------------------------------------------- sheets

        @app.get("/api/sheets")
        def list_sheets():
            """The sheets of this project, and which one is active."""
            return manage(self.sheets.state)

        @app.post("/api/sheets", dependencies=write, status_code=201)
        def add_sheet(body: dict | None = None):
            fields = body or {}
            return manage(
                self.sheets.add,
                fields.get("name"),
                fields.get("width_mm"),
                fields.get("height_mm"),
                fields.get("material_id"),
                fields.get("thickness_mm"),
            )

        @app.post("/api/sheets/{sheet_id}/activate", dependencies=write)
        def activate_sheet(sheet_id: str):
            """
            Switching sheets: the current one is saved, the other loaded. What you see
            afterwards is exactly what gets burned.
            """
            return manage(self.sheets.activate, sheet_id)

        @app.patch("/api/sheets/{sheet_id}", dependencies=write)
        def update_sheet(sheet_id: str, body: dict):
            return manage(lambda: self.sheets.update(sheet_id, **body))

        @app.delete("/api/sheets/{sheet_id}", dependencies=write)
        def delete_sheet(sheet_id: str):
            def run():
                state = self.sheets.remove(sheet_id)
                # Sheet numbers are reused; without this a new sheet inherits the
                # provenance of the sheet that has just gone.
                self.provenance.forget_sheet(sheet_id)
                return state

            return manage(run)

        @app.post("/api/sheets/{sheet_id}/move", dependencies=write)
        def move_to_sheet(sheet_id: str, body: dict):
            return manage(self.sheets.move_selection, body.get("ids") or [], sheet_id)

        # ----------------------------------------------------------------- tiles

        @app.get("/api/tiling")
        def tiling_layout():
            """
            The active sheet's division: tiles, seams, mark positions.

            Computed, not stored — it is a function of the board size, the bed size and the
            design, so it holds by itself as soon as something there changes.
            """
            return manage(self.tiles.layout)

        @app.post("/api/tiling/start", dependencies=write)
        def tiling_start():
            """
            Begin a tile run — unless a series is already deciding what the next burn is.

            The mirror of the refusal `Series._refuse_other_run` makes from the other
            side. One half of that promise was here already and the other half was not,
            so the two runs could be begun in either order and only one order was
            refused.
            """

            def run():
                self.series.vet_tile_run()
                return self.tiles.start()

            return manage(run)

        @app.post("/api/tiling/align", dependencies=write)
        def tiling_align(body: dict):
            """
            The tapped points. `use_current: true` takes the head position, so that you can
            aim with the jog buttons and then press 'Here' once.
            """

            def run():
                points = list(body.get("points") or [])
                if body.get("use_current"):
                    current = self.motion._current_mm()
                    if current is None:
                        raise DesignError(
                            "This machine reports no position, so 'Here' does not know "
                            "where it is. Fill in the coordinates by hand."
                        )
                    points.append({"x_mm": current[0], "y_mm": current[1]})
                return self.tiles.align(points, body.get("reference") or "markers")

            return manage(run)

        @app.post("/api/tiling/burn", dependencies=write)
        def tiling_burn(body: dict | None = None):
            """
            Burn one tile — through the same gate as every other burn in this app.

            `TileRun.burn` is the third and last caller of `CommandRunner.start_job`,
            and it was the one that passed no series gate: a text asking the list for a
            column it has not got came off the machine as a frame with the name missing,
            without a word, on the one route that did not vet. See
            `Series.vet_tile_burn`.
            """
            confirm = bool((body or {}).get("confirm"))

            def run():
                self.series.vet_tile_burn()
                return self.tiles.burn(confirm_reburn=confirm)

            return manage(run)

        @app.post("/api/tiling/advance", dependencies=write)
        def tiling_advance():
            return manage(self.tiles.advance)

        @app.post("/api/tiling/cancel", dependencies=write)
        def tiling_cancel():
            return manage(self.tiles.cancel)

        # ---------------------------------------------------------------- series
        #
        # One design, burned once per row of a list. The reading of the list is ours —
        # see the head of series.py for the four kinds of file the engine's own loader
        # mishandles — while the substitution stays the engine's.

        def _series_read(body: dict) -> tuple:
            """
            One body, one reading, for the preview and for attaching alike.

            The preview and the button must not be able to ask different things: that is
            exactly the bug where the screen shows a header row and the burn reads it as
            data. So both routes come through here and the only difference between them
            is whether the answer is written down.

            Numbers are not a second kind of series, only a second way of filling the
            rows in. `first`/`last`/`step`/`padding` build the very shape `read_rows`
            returns, so everything after this function is the same for both doors: one
            attach path, one refusal set, and `source.kind` to tell them apart
            afterwards. A field on the same body rather than a route of its own, because
            a second route family would be a second place for the two to drift.
            """
            body = body or {}
            kind = str(body.get("kind") or ("file" if body.get("file") else "numbers"))
            if kind == "numbers":
                read = rows_from_numbers(
                    body.get("first"),
                    body.get("last"),
                    body.get("step", 1),
                    body.get("padding", 0),
                    str(body.get("column") or "number"),
                )
                return read, {
                    "kind": "numbers",
                    "first": body.get("first"),
                    "last": body.get("last"),
                    "step": body.get("step", 1),
                    "padding": body.get("padding", 0),
                }
            name = Path(str(body.get("file") or "")).name
            if not name:
                # A refusal of ours and not a bare 422: every other no in this API is a
                # 409 with its code in `X-OpenKerf-Error`, and the window reads that
                # header to say the sentence in the reader's own language. A 422 here
                # would be the one refusal in the family that only speaks English.
                raise DesignError(
                    "No file has been chosen, so there is no list to read. Pick a "
                    "file, or fill in the numbers to count from.",
                    code="series.noFileChosen",
                )
            target = self._upload_path(name)
            if not target.exists():
                # Uploads live in a temp directory that is wiped when the server stops,
                # so a page left open across a restart holds a name that means nothing
                # any more. Saying so beats a preview of an empty list.
                raise DesignError(
                    "That file is no longer on the server. Pick it again.",
                    code="series.uploadGone",
                )
            return read_rows(target.read_bytes(), body.get("has_header")), {
                "kind": "file",
                "name": name,
            }

        def _series_preview(read: dict, source: dict) -> dict:
            """
            What the window shows before anything is written down.

            `has_header` beside `header_guess`, and the delimiter and the encoding as
            well: every one of those is a decision this app took about somebody's file,
            and a decision taken silently is one they cannot overrule.
            """
            rows = read["rows"]
            return {
                "source": source,
                "columns": read["columns"],
                "row_count": len(rows),
                "rows": rows[:SERIES_PREVIEW_ROWS],
                "has_header": read["has_header"],
                "header_guess": read["header_guess"],
                "delimiter": read["delimiter"],
                "encoding": read["encoding"],
                "blanks": read["blanks"],
                "warnings": read["warnings"],
            }

        @app.get("/api/series")
        def series_state():
            """
            The list, the row the bed is showing, and what the design asks of the list.

            The rows themselves ride along here and nowhere else. This is the window's
            own route; `state()` also goes into the status payload every couple of
            seconds, and a thousand rows in there is a thousand rows down every open
            socket for a number that fits in a word.
            """
            return manage(lambda: {**self.series.state(), "rows": self.series.rows()})

        @app.post("/api/series/upload", dependencies=write)
        async def upload_series(file: UploadFile):
            """
            Accept the file and say what is in it — nothing is attached yet.

            It keeps its own name in the upload directory so that the header question
            can be answered again without uploading again. Two steps, like the library
            bundle and the machine profile.
            """
            target = self._upload_path(file.filename or "list.csv")
            written = 0
            with target.open("wb") as handle:
                while True:
                    chunk = await file.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > SERIES_UPLOAD_LIMIT:
                        break
                    handle.write(chunk)
            if written > SERIES_UPLOAD_LIMIT:
                target.unlink(missing_ok=True)
                limit = SERIES_UPLOAD_LIMIT // (1024 * 1024)
                raise refuse(
                    DesignError(
                        f"This file is larger than {limit} MB. "
                        "A list of names is a few kilobytes; this is probably not the "
                        "file you meant.",
                        code="series.fileTooBig",
                        values={"max_mb": limit},
                    )
                )

            def run():
                read, source = _series_read({"kind": "file", "file": target.name})
                return {"file": target.name, **_series_preview(read, source)}

            return manage(run)

        @app.post("/api/series/preview", dependencies=write)
        def preview_series(body: dict):
            """
            The same reading again, with a different answer to the header question.

            It computes and writes nothing, and it is still behind the write gate —
            unlike the two other previews in this API. It reads a file off this
            machine's disk by name, and that upload directory also holds library bundles
            and machine profiles somebody else put there, so this is not a read of the
            caller's own data alone.
            """

            def run():
                read, source = _series_read(body or {})
                return _series_preview(read, source)

            return manage(run)

        @app.post("/api/series/attach", dependencies=write)
        def attach_series(body: dict):
            """
            Take this list as the one the design burns from, and show its first row.

            The same body as the preview, so the window builds one request and decides
            only where to send it.
            """

            def run():
                read, source = _series_read(body or {})
                return self.series.attach(read, source, (body or {}).get("skip_blank"))

            return manage(run)

        @app.delete("/api/series", dependencies=write)
        def detach_series():
            """Take the list away, and stop the bed showing names it no longer has."""
            return manage(self.series.detach)

        @app.get("/api/series/plate")
        def plate_plan(
            ids: str | None = None,
            margin_mm: float | None = None,
            gap_mm: float | None = None,
        ):
            """
            How many of this piece fit on the plate, and what the rest of the list does.

            A read: the window asks it again on every change of a number, and it must
            never put a copy on the bed by being looked at.
            """
            picked = [part for part in (ids or "").split(",") if part]
            return manage(self.plating.plan, picked, margin_mm, gap_mm)

        @app.post("/api/series/plate", dependencies=write, status_code=201)
        def plate_fill(body: dict | None = None):
            """Lay the piece out over the plate, each copy taking the next row."""
            body = body or {}
            return manage(
                self.plating.fill,
                body.get("ids") or [],
                body.get("margin_mm"),
                body.get("gap_mm"),
            )

        @app.post("/api/series/row", dependencies=write)
        def series_row(body: dict):
            """
            Point the bed at one row, without starting anything.

            The window's burn list is a list of rows, and looking at row twelve is
            reading and not burning. Without this route the only way to see another
            name was to press Start, which writes a run — an operator looking around
            would be starting one.
            """
            return manage(lambda: self.series.set_row((body or {}).get("row")))

        @app.post("/api/series/start", dependencies=write)
        def series_start(body: dict | None = None):
            """Begin the run. `row` counts from nought; absent is where the bed is."""
            return manage(lambda: self.series.start((body or {}).get("row")))

        @app.post("/api/series/burn", dependencies=write)
        def series_burn(body: dict | None = None):
            """
            Burn the row the bed is showing.

            Through the same `spooling()` context as the ordinary Burn button: a series
            adds no placement of its own, so a zero point and a print-and-cut pose apply
            to it exactly as they do to any other job.
            """
            confirm = bool((body or {}).get("confirm"))

            def run():
                with spooling() as pose:
                    return self.series.burn(confirm=confirm, mutators=pose)

            return manage(run)

        @app.post("/api/series/advance", dependencies=write)
        def series_advance():
            """Move on to the next burn that still has to happen."""
            return manage(self.series.advance)

        @app.post("/api/series/redo", dependencies=write)
        def series_redo(body: dict):
            """Burn one of these again: point at its burn and mark that burn undone."""
            return manage(lambda: self.series.redo((body or {}).get("row")))

        @app.post("/api/series/stop", dependencies=write)
        def series_stop():
            """End the run and keep the list."""
            return manage(self.series.stop)

        # --------------------------------------------------------------- clipart

        @app.get("/api/clipart/search")
        def clipart_search(
            q: str, sources: str | None = None, limit: int = 24, page: int = 1
        ):
            """
            Zoeken in openbare collecties, via onze server.

            A source that does not answer does not hold the rest up: it comes back in
            'unavailable' so that the app can report it.
            """
            chosen = [s.strip() for s in (sources or "").split(",") if s.strip()]
            return manage(self.clipart.search, q, chosen or None, limit, page)

        @app.post("/api/clipart/insert", dependencies=write, status_code=201)
        def clipart_insert(body: dict):
            return manage(
                self.clipart.insert,
                body.get("url"),
                body.get("width_mm", 60.0),
                body.get("x_mm", 10.0),
                body.get("y_mm", 10.0),
            )

        # ----------------------------------------------------------- generatoren

        @app.get("/api/design/autosave")
        def autosave_state():
            """Whether work from a previous session is waiting."""
            return self.autosave.state()

        @app.post("/api/design/autosave/restore", dependencies=write)
        def restore_autosave():
            def run():
                if any(True for _ in self.kernel.elements.elems()):
                    raise LibraryError(
                        "There is already something on the canvas. Empty it first; "
                        "recovering on top of existing work gives a jumble."
                    )
                return self.autosave.restore()

            return manage(run)

        @app.delete("/api/design/autosave", dependencies=write)
        def discard_autosave():
            return self.autosave.discard()

        @app.post("/api/design/path", dependencies=write, status_code=201)
        def create_path(body: dict):
            """A freely drawn path: the pen."""
            return manage(
                self.drawing.create_path,
                body.get("points"),
                bool(body.get("closed")),
                body.get("label"),
            )

        @app.post("/api/design/nest", dependencies=write)
        def nest_elements(body: dict):
            return manage(
                self.nesting.nest,
                body.get("ids") or [],
                body.get("margin_mm", 3.0),
                body.get("origin_x_mm", 0.0),
                body.get("origin_y_mm", 0.0),
            )

        @app.post("/api/design/generate/preview")
        def preview_generator(body: dict):
            """
            What a generator would make, without making it.

            **A POST without `write`, and that is a deliberate exception.** POST because a
            form goes in that does not fit in a query string, not because anything changes:
            `Generators.preview` computes the shape with the same `_plan_*` functions as the
            real work and hands it back as path data. It hangs nothing on the element tree,
            creates no sheet and puts nothing on the undo stack — not even temporarily. That
            is the whole ground for the missing guard: if it touched the tree and cleaned up
            afterwards, it would change the work of anybody else looking on with every key
            stroke, and that is a write action however neat the cleaning up is.

            Proven, not claimed: `test_the_preview_leaves_the_drawing_alone` lays the whole
            snapshot from before and after thirty previews side by side (including the box
            that spans two sheets, where the *real* generator does add a sheet), and
            `test_the_preview_adds_nothing_to_undo` does the same for the undo stack. The
            other side of the agreement is in `test_write_actions.py`: the route is in
            `READ_ONLY_POSTS` there, and every other POST *must* have the guard.

            Two things that follow from it and that you should not remove:
            - The arc text fetches its letters with `cfont.render()` into a loose `FontPath`
              rather than through a text node, precisely because a node would end up in the
              document.
            - That same route does *not* set `context.last_font`, while the real text
              placement does (extra/hershey.py:492).
            """
            what = str(body.get("what") or "")
            return manage(self.generators.preview, what, body)

        @app.post("/api/design/generate/grid", dependencies=write)
        def generate_grid(body: dict):
            """Repeating the selection in rows and columns."""
            return manage(
                self.generators.grid,
                body.get("ids") or [],
                body.get("columns"),
                body.get("rows"),
                body.get("gap_x_mm", 5.0),
                body.get("gap_y_mm", 5.0),
                # Gap: a repeated `{name}` gave the same name every time. With this on
                # each copy reads the next row of the attached list.
                body.get("follow_list", False),
            )

        @app.post("/api/design/generate/radial", dependencies=write)
        def generate_radial(body: dict):
            return manage(
                self.generators.radial,
                body.get("ids") or [],
                body.get("repeats"),
                body.get("radius_mm"),
                body.get("start_deg", 0.0),
                body.get("end_deg", 360.0),
                body.get("rotate", True),
            )

        @app.post("/api/design/generate/polygon", dependencies=write, status_code=201)
        def generate_polygon(body: dict):
            return manage(
                self.generators.polygon,
                body.get("corners"),
                body.get("cx_mm"),
                body.get("cy_mm"),
                body.get("radius_mm"),
                body.get("inner_radius_mm"),
                body.get("start_deg", 0.0),
            )

        @app.post("/api/design/generate/box", dependencies=write, status_code=201)
        def generate_box(body: dict):
            return manage(
                self.generators.box,
                body.get("width_mm"),
                body.get("depth_mm"),
                body.get("height_mm"),
                body.get("thickness_mm"),
                body.get("finger_mm", 10.0),
                body.get("kerf_mm", 0.0),
                body.get("gap_mm", 5.0),
                body.get("lid", True),
                body.get("spread", True),
            )

        @app.post("/api/design/generate/arctext", dependencies=write, status_code=201)
        def generate_arc_text(body: dict):
            """Text along an arc; a path afterwards, no longer text."""
            return manage(
                self.generators.arc_text,
                body.get("text"),
                body.get("cx_mm"),
                body.get("cy_mm"),
                body.get("radius_mm"),
                body.get("font_size_mm", 10.0),
                body.get("font"),
                body.get("spacing"),
                bool(body.get("inside")),
            )

        @app.post("/api/design/generate/hinge", dependencies=write, status_code=201)
        def generate_hinge(body: dict):
            """A field of slits that lets rigid sheet material bend."""
            return manage(
                self.generators.hinge,
                body.get("ids") or [],
                body.get("pattern") or "staggered",
                body.get("slit_mm", 8.0),
                body.get("gap_mm", 3.0),
                body.get("row_mm", 2.0),
                body.get("x_mm", 0.0),
                body.get("y_mm", 0.0),
                body.get("width_mm", 60.0),
                body.get("height_mm", 40.0),
                body.get("from_selection", False) is True,
            )

        @app.post("/api/design/generate/focus", dependencies=write, status_code=201)
        def generate_focus(body: dict):
            """
            A focus test: the same mark burned at a series of heights (gap H4).

            Only on a machine whose Z the software can move; the refusal explains why,
            because on a Ruida this would burn ten identical marks and call it an answer.
            """
            return manage(
                self.focus.draw,
                z_from_mm=body.get("z_from_mm", -2.0),
                z_to_mm=body.get("z_to_mm", 2.0),
                marks=body.get("marks", 9),
                mark_mm=body.get("mark_mm", 15.0),
                gap_mm=body.get("gap_mm", 8.0),
                x_mm=body.get("x_mm", 10.0),
                y_mm=body.get("y_mm", 10.0),
                speed_mm_s=body.get("speed_mm_s"),
                power_percent=body.get("power_percent"),
                text=body.get("text", True) is not False,
                label_speed_mm_s=body.get("label_speed_mm_s"),
                label_power_percent=body.get("label_power_percent"),
            )

        @app.post("/api/design/generate/barcode", dependencies=write, status_code=201)
        def generate_barcode(body: dict):
            return manage(
                self.generators.barcode,
                body.get("text"),
                body.get("kind") or "code128",
                body.get("x_mm", 0.0),
                body.get("y_mm", 0.0),
                body.get("width_mm", 60.0),
                body.get("height_mm", 20.0),
            )

        @app.post("/api/design/generate/qrcode", dependencies=write, status_code=201)
        def generate_qrcode(body: dict):
            return manage(
                self.generators.qrcode,
                body.get("text"),
                body.get("x_mm", 0.0),
                body.get("y_mm", 0.0),
                body.get("size_mm", 30.0),
                body.get("border", 2),
            )

        # ---------------------------------------------------------- presetariat

        @app.get("/api/presetariat")
        def browse_catalogue(
            machine_id: int | None = None,
            material: str | None = None,
            operation: str | None = None,
            refresh: bool = False,
        ):
            """The shared catalogue, filtered on what this machine is."""
            return manage(
                self.presetariat.browse, machine_id, material, operation, refresh
            )

        @app.post("/api/presetariat/stage", dependencies=write)
        def stage_catalogue_presets(body: dict | None = None):
            """
            Write the chosen starting points as a library file and say what it would do.

            The catalogue stops having an importer of its own here. What comes back is
            what `/api/library/import/upload` answers — the same preview, the same
            wording, the same "this is what is going to happen" screen — and the client
            hands the bundle and the batch straight to `/api/library/import`. That one
            call is a transaction, maps materials, detects clashes on `_preset_key` and
            re-points sheets, none of which the old importer did.

            With `ids` this is the per-material drawer taking over one row; without them
            it is the offer fetching the set that suits this machine. `Starter.stage`
            holds the difference, including which refusals apply to which.
            """
            def run():
                staged = self.starter.stage(
                    self._active_profile(),
                    self._upload_dir_for_stage(),
                    (body or {}).get("ids"),
                )
                target = self._upload_path(staged["bundle"])
                return {**staged, **self.library.preview_import(target)}

            return manage(run)

        # Superseded by the route above and kept only until its two callers go with it:
        # `frontend/src/lib/presetariat.svelte.ts` (deleted with the Presetariat window)
        # and `api/tests/test_presetariat.py`. It is the importer this round set out to
        # remove: `_material_id` creates the material before `add_preset` can refuse, so
        # `[good, bad]` leaves materials written and raises, in a library that until now
        # had no way to remove a material.
        @app.post("/api/presetariat/import", dependencies=write)
        def import_catalogue_presets(body: dict):
            return manage(
                self.presetariat.import_presets,
                body.get("ids") or [],
                body.get("machine_id"),
            )

        @app.get("/api/presetariat/contribution/{preset_id}")
        def preset_contribution(preset_id: int):
            """
            One of your own presets in catalogue form, and what it still needs.

            A read, so it is the call the share panel opens with: `ready`, `needs`,
            `tier` and `tier_reason` say what would go out and under what label before
            anything is written or any tab is opened. `preset` is null until the offer
            would validate — the repository's CI is not the place to find out that the
            app has never asked for a GitHub handle.
            """
            return manage(self.presetariat.as_contribution, preset_id)

        @app.post("/api/presetariat/contribution/{preset_id}", dependencies=write)
        def offer_preset(preset_id: int, body: dict | None = None):
            """
            The two answers a contribution needs, and then the contribution.

            Writes twice: the handle beside the library, so it is asked once, and the
            outcome onto the setting, so a second offer of the same row does not ask
            again and a library handed on carries its own evidence. Both are the reader's
            own words about their own machine, and both are behind the token for that
            reason.
            """
            fields = body or {}
            return manage(
                self.presetariat.offer,
                preset_id,
                fields.get("by"),
                fields.get("result"),
            )

        # ---------------------------------------------------------- testrasters

        def grid_fields(body: dict) -> dict:
            """
            What the board adds to the form of its own accord: machine, date, material.

            Preview and reality use the same lines here. They have to: the caption decides
            how wide the board becomes, so a preview without a date reports a narrower board
            than the one that burns.
            """
            from datetime import date

            fields = dict(body)
            # `text`/`border` are the planner's spelling and `text_enabled`/
            # `border_enabled` are the column's, and the two halves of this feature were
            # written a round apart (see the comment on `code_enabled` in
            # `testgrid.plan_grid`). So a caller that hands back a row it read from the
            # database, or a stored recipe, used to reach `plan_grid` with a keyword it has
            # no parameter for and get a bare **500**: measured on the live server,
            # `text_enabled: true` and `border_enabled: false` each answered 500 where
            # `text: true` answered 200. Accepting the column's spelling here costs one
            # line and keeps the route's own database readable by the route.
            for stored, planned in (("text_enabled", "text"), ("border_enabled", "border")):
                if stored in fields:
                    fields[planned] = bool(fields.pop(stored))
            # A grid is a trial on *this* machine; without that fact the presets that come
            # out of it cannot be placed back.
            if not fields.get("machine_id"):
                profile = self._active_profile()
                if profile:
                    fields["machine_id"] = profile["id"]
            fields["stamp"] = date.today().isoformat()
            if fields.get("material_id"):
                material = next(
                    (
                        m
                        for m in self.library.materials()
                        if m["id"] == fields["material_id"]
                    ),
                    None,
                )
                if material:
                    fields["material_name"] = material["name"]
            # The cut setting the rim is cut with, looked up here rather than asked of
            # whoever fills in the form. `cutout_setting` is the half of the cut-out that
            # needs a library, which is why it cannot live in the planner — and until this
            # line nothing called it at all: a board posted with `cutout_enabled` and
            # nothing else reached `_cutout` with no speed and was refused with
            # `library.grid.cutoutNoSetting`, which names no way out. Measured before this
            # line, every cut-out asked for through this route refused, so the feature was
            # unreachable and the two refusals that *are* actionable — no material, and no
            # cut setting for this thickness — could not be reached either. Only when the
            # caller brought no setting of its own, so a script that knows its own speed
            # keeps the number it sent.
            if fields.get("cutout_enabled") and not fields.get("cut_speed_mm_s"):
                fields.update(cutout_setting(self.library, fields))
            # Everything from here on is handed to `plan_grid` as keywords, so a field it
            # has no parameter for is a `TypeError` and, through FastAPI, a 500 that names
            # nothing. A misspelling must not be dropped in silence either — a board that
            # burns without the cut-out you asked for is worse than one that refuses — so
            # it is said out loud, with the name that was not understood.
            takes = inspect.signature(plan_grid).parameters
            strange = sorted(key for key in fields if key not in takes)
            if strange:
                raise LibraryError(
                    f"A board has no field called {strange[0]}.",
                    code="library.grid.unknownField",
                    values={"field": strange[0]},
                )
            return fields

        @app.post("/api/library/testgrids/preview")
        def preview_test_grid(body: dict):
            """Work out the cells without drawing anything, so it can be shown first."""
            def run():
                plan, cells = plan_grid(**grid_fields(body))
                return {
                    "plan": plan,
                    "cells": cells,
                    # What *this* engine can do with this kind of layer. Without a
                    # rasteriser a grid board comes out of the machine blank, and you have
                    # to know that before the wood goes in — see raster_supported.
                    "engine": {"raster": raster_supported(self.kernel)},
                }

            return manage(run)

        @app.post("/api/library/testgrids", dependencies=write, status_code=201)
        def create_test_grid(body: dict):
            """Plan the grid, draw it into the design, and remember it."""
            def run():
                # The caption goes into the planning: it is aligned left on the board and
                # runs to the right, so it helps decide how wide the board becomes. Adding it
                # afterwards gave a reported measure narrower than what burns.
                fields = grid_fields(body)
                plan, cells = plan_grid(**fields)
                # A name already burned on another plank must not be burned onto this one.
                # `add_test_grid` mints a fresh name for the *row* when the one it is given
                # is taken (`_fresh_grid_uid`), but by then the code is drawn: the row would
                # say one name and the wood another, and a photograph of that wood would be
                # filed under the older board — precisely the mix-up the code exists to
                # prevent. Reachable through this route, and measured: posting the same
                # `uid` twice gave a second plank burned `7X4M QB2K` under a row named
                # `45E0JKKA`, with `test_grid_for_uid("7X4MQB2K")` answering board 1. The
                # trigger is ordinary rather than exotic — a client that previews, gets a
                # name, and then creates twice from that one preview.
                #
                # Planned again rather than patched, because the name is on the plank in two
                # places: the code and the printed line in the caption, and `caption_text`
                # is worked out inside `plan_grid`.
                if plan.get("uid") and self.library.test_grid_for_uid(plan["uid"]):
                    plan, cells = plan_grid(**{**fields, "uid": None})
                # The grid is one object on the canvas — squares, axis labels,
                # caption and frame in one group, in one action. The cells keep their own
                # operations, because those *are* the sweep.
                drawn, group_id = self.grids.draw(plan, cells)
                grid = self.library.add_test_grid(plan, drawn)
                if group_id:
                    self.library.set_grid_group(grid["id"], group_id)
                    grid = self.library.test_grid(grid["id"])
                return grid

            return manage(run)

        @app.get("/api/library/testgrids")
        def list_test_grids():
            return self.library.test_grids()

        @app.get("/api/library/testgrids/defaults")
        def test_grid_defaults(material_id: int | None = None):
            """
            The settings of the previous grid for this material (T3).

            No separate preferences table: the previous grid *is* the setting. `null` when
            there is no grid for this material yet.
            """
            return self.library.last_grid_settings(material_id)

        # ------------------------------------------- named recipes (gap T7)
        #
        # Before `/testgrids/{grid_id}`, otherwise that route catches "recipes" as an id.
        # That is FastAPI's order of declaration, not of specificity.

        @app.get("/api/library/testgrids/recipes")
        def list_grid_recipes(material_id: int | None = None):
            """
            Saved generator settings under a name.

            T3 remembers the previous grid per material; this is the same in the plural, so
            that "cut birch" and "engrave birch" can sit beside each other. The same keys as
            T3 uses, so the form fills itself in from either of them the same way.
            """
            return manage(self.library.grid_recipes, material_id)

        @app.post("/api/library/testgrids/recipes", dependencies=write, status_code=201)
        def save_grid_recipe(body: dict):
            return manage(
                self.library.save_grid_recipe,
                body.get("name"),
                body.get("settings") or {},
                body.get("material_id"),
            )

        @app.delete("/api/library/testgrids/recipes/{recipe_id}", dependencies=write)
        def remove_grid_recipe(recipe_id: int):
            return manage(self.library.remove_grid_recipe, recipe_id)

        @app.get("/api/library/testgrids/{grid_id}")
        def get_test_grid(grid_id: int):
            return manage(self.library.test_grid, grid_id)

        @app.post("/api/library/testgrids/{grid_id}/remove-from-design", dependencies=write)
        def remove_grid_from_design(grid_id: int):
            """
            Take the grid off the canvas: the group *and* all its cell operations.

            The stored grid stays — the photo and the presets' provenance hang off it.
            """
            def run():
                grid = self.library.test_grid(grid_id)
                removed = {"elements": 0, "operations": 0}
                # Only what really belongs to this grid. Ids hold per document, so the same
                # id stands for something else on another sheet — see the explanation at
                # `is_cel_operatie`.
                if grid.get("group_id"):
                    node = self.kernel.elements.find_node(grid["group_id"])
                    if node is not None and is_raster_group(node):
                        removed["elements"] = len(list(node.flat())) - 1
                        node.remove_node(children=True, destroy=True)
                for cell in grid["cells"]:
                    for key, hoort_erbij in (
                        ("element_id", is_cel_element),
                        ("operation_id", is_cel_operatie),
                    ):
                        node = self.kernel.elements.find_node(cell.get(key) or "")
                        if node is not None and hoort_erbij(node, cell):
                            node.remove_node(children=True, destroy=True)
                            removed["operations" if key == "operation_id" else "elements"] += 1
                for op in list(self.kernel.elements.ops()):
                    if getattr(op, "label", None) in LABEL_LAYERS and not list(op.children):
                        op.remove_node()
                self.library.set_grid_group(grid_id, None)
                self.kernel.elements.signal("rebuild_tree", "all")
                return removed

            return manage(run)

        @app.delete("/api/library/testgrids/{grid_id}", dependencies=write)
        def remove_test_grid(grid_id: int):
            return manage(self.library.remove_test_grid, grid_id)

        # ------------------------------------------- a photograph and its board
        #
        # Eleven of the author's thirty-two boards are physically indistinguishable from
        # another one: same material, same square size, same sweep, burned minutes apart.
        # By the time the wood is off the machine, filing the picture under the right row
        # is guesswork, and a preset carrying the wrong board's photograph is evidence for
        # something nobody burned. The code on the plank is what takes the guess out, and
        # these two routes are its two halves — one that names the board from the picture,
        # one that refuses a picture filed under the wrong board.

        def boards_that_named_themselves(data: bytes):
            """
            The boards whose code is in this picture: ours, and strangers.

            Two lists rather than one, because the difference between them is a different
            sentence. `known` are rows in this library. `strangers` are codes that read
            back as board names but name nothing here — somebody else's library, or a QR
            that happened to be in shot. A stranger is not automatically an error: see
            `upload_grid_photo`, where refusing on one would let a sticker on the bench
            block an honest photograph.

            The bytes of the **upload**, never a stored copy. Measured on a synthetic board
            photograph, an 18 mm code on a 300 mm board: 1600 px across the frame decoded 16
            of 40, 2000 px and up decoded 40 of 40 (the module docstring of `boardcode`
            carries the table and the harness). A contribution's copy is 1600 px, so
            anything that decoded that would be reading the one size that half works.
            """
            known, strangers = [], []
            for uid in boardcode.read(data):
                board = self.library.test_grid_for_uid(uid)
                if board is None:
                    strangers.append(uid)
                else:
                    known.append(board)
            return known, strangers

        def a_decoder_or_a_refusal():
            """OpenCV, or the refusal that says what to do instead."""
            if boardcode.available():
                return
            raise LibraryError(
                f"{boardcode.NO_DECODER_HINT} Choose the board yourself for now.",
                code="library.photo.noDecoder",
            )

        @app.post("/api/library/testgrids/photo", dependencies=write)
        async def upload_photo_of_its_own_board(file: UploadFile):
            """
            A photograph with no board id: it decodes the code and names its own board.

            Four ways this can go, four sentences, because each one sends the reader
            somewhere else: no OpenCV in this copy (install it, or pick the board by hand),
            no code in the picture (photograph it more squarely, or pick the board by
            hand), a code this library does not know (it is not this library's board), and
            two boards in one frame (photograph one at a time). One sentence covering all
            four would send three of those four readers the wrong way.

            The board is not created here and nothing is guessed: this route only files a
            photograph against a row that already exists, which is why it answers with the
            same grid the id route does — one code path for the caller.
            """
            suffix = Path(file.filename or "").suffix
            data = await file.read()
            if not data:
                raise HTTPException(status_code=422, detail="Empty photo.")

            def run():
                a_decoder_or_a_refusal()
                known, strangers = boards_that_named_themselves(data)
                if not known and not strangers:
                    raise LibraryError(
                        "No code was found in this photograph. Choose the board it "
                        "belongs to yourself, or photograph the code more squarely.",
                        code="library.photo.noCode",
                    )
                if not known:
                    found = boardcode.human(strangers[0])
                    raise LibraryError(
                        f"The code in this photograph says board {found}, and this "
                        "library holds no board of that name. It belongs to another "
                        "library, or the picture caught a code that is not a board.",
                        code="library.photo.unknownBoard",
                        values={"found": found},
                    )
                if len(known) > 1:
                    named = " and ".join(boardcode.human(b["uid"]) for b in known[:2])
                    raise LibraryError(
                        f"This photograph holds the codes of more than one board "
                        f"({named}). Photograph one board at a time, so the picture is "
                        "evidence for the board it is filed under.",
                        code="library.photo.manyBoards",
                        values={"found": named, "n": len(known)},
                    )
                return self.library.set_grid_photo(known[0]["id"], suffix, data)

            return manage(run)

        @app.post("/api/library/testgrids/{grid_id}/photo", dependencies=write)
        async def upload_grid_photo(grid_id: int, file: UploadFile):
            """
            The photo of the burned grid — usually taken on a phone — filed by hand.

            The code is still read, for one purpose: to refuse a photograph whose code
            names a *different* board of this library. That is the mix-up this feature
            exists to prevent, and it is the only thing here that cannot be recovered
            later — the picture would sit under a row it is not of, and every preset drawn
            from it would carry it as evidence.

            Only a code naming a board this library actually holds refuses. A code that
            reads back but names nothing here is left alone deliberately: `boardcode.parse`
            accepts eight characters of Crockford base32, and plenty of ordinary words
            survive that folding (`notacode` reads back as `N0TAC0DE`), so a stranger's QR
            in the corner of the frame would otherwise block a picture that is perfectly
            right. Without a code, or without OpenCV, this route does exactly what it did
            before: it stores what the user gave it.
            """
            suffix = Path(file.filename or "").suffix
            data = await file.read()
            if not data:
                raise HTTPException(status_code=422, detail="Empty photo.")

            def run():
                picked = self.library.test_grid(grid_id)
                known, _ = boards_that_named_themselves(data)
                # Every code that named a board of this library, and none of them is the
                # one the user picked. Two boards in one frame is fine here as long as the
                # picked one is among them — it named itself, which is all that was asked.
                if known and not any(b["id"] == picked["id"] for b in known):
                    found = boardcode.human(known[0]["uid"])
                    # A board with no name cannot happen: the migration back-filled the
                    # thirty-two that predate this and every insert mints one. The number
                    # is here because a refusal with a dash in it is not a sentence.
                    mine = (
                        boardcode.human(picked["uid"])
                        if picked.get("uid")
                        else f"number {picked['id']}"
                    )
                    raise LibraryError(
                        f"The code in this photograph says board {found}; you picked "
                        f"{mine}. File it under {found}, or pick that board here.",
                        code="library.photo.codeMismatch",
                        values={
                            "found": found,
                            "picked": mine,
                            # The row the picture really belongs to, so the interface can
                            # offer "File it under {found}" as a button rather than as a
                            # sentence the reader has to act on themselves. It stays a
                            # number safely because this refusal keeps its English
                            # sentence — the codes in it are per-call data, not a constant
                            # of ours — so it never passes through `values()` in core.ts,
                            # which would write it through `Intl` and turn 1234 into
                            # "1.234" for a Dutch reader.
                            "found_id": known[0]["id"],
                        },
                    )
                return self.library.set_grid_photo(grid_id, suffix, data)

            return manage(run)

        @app.put("/api/library/testgrids/{grid_id}/alignment", dependencies=write)
        def set_grid_alignment(grid_id: int, body: dict):
            """
            Where the board lies on the photo (T4).

            This used to be in localStorage: aligning on the desktop and pointing out the
            square on the tablet then produced two different overlays.
            """
            return manage(
                self.library.set_grid_alignment, grid_id, body.get("corners")
            )

        @app.get("/api/library/testgrids/{grid_id}/photo")
        def get_grid_photo(grid_id: int, cell: str | None = None):
            """
            The photo of the burned board.

            With `?cell=<row>-<column>` the square pointed out comes along circled (M4),
            according to the alignment stored with this grid. Without that parameter it is
            the user's file, unprocessed.
            """
            from fastapi.responses import FileResponse, Response

            grid = manage(self.library.test_grid, grid_id)
            path = grid.get("photo_path")
            if not path or not Path(path).is_file():
                raise HTTPException(status_code=404, detail="No photo yet.")
            if not cell:
                return FileResponse(path)
            try:
                row, column = (int(part) for part in str(cell).split("-", 1))
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="cell has the shape <row>-<column>."
                ) from None
            data = manage(markeer_foto, grid, path, row, column)
            return Response(content=data, media_type="image/jpeg")

        @app.post("/api/library/testgrids/{grid_id}/presets", dependencies=write, status_code=201)
        def presets_from_cells(grid_id: int, body: dict):
            """
            Turn the cells the user pointed at into presets.

            This closes the loop: the resulting preset carries source
            "testraster" and points back at the grid it came from, which is
            what earns it the "geverifieerd" badge.
            """
            chosen = body.get("cells")
            if not isinstance(chosen, list) or not chosen:
                raise HTTPException(status_code=422, detail="Pick at least one square.")

            def run():
                grid = self.library.test_grid(grid_id)
                if grid["material_id"] is None:
                    raise LibraryError(
                        "This grid belongs to no material; link one to it first."
                    )
                by_position = {(c["row"], c["column"]): c for c in grid["cells"]}
                created = []
                for pick in chosen:
                    key = (pick.get("row"), pick.get("column"))
                    cell = by_position.get(key)
                    if cell is None:
                        raise LibraryError(f"Cell {key} does not belong to this grid.")
                    preset = self.library.add_preset(
                        material_id=grid["material_id"],
                        machine_id=grid["machine_id"],
                        thickness_mm=grid["thickness_mm"],
                        operation=grid["operation"],
                        speed_mm_s=cell["speed_mm_s"],
                        power_percent=cell["power_percent"],
                        # The board burned with this number of passes; without that number
                        # the preset later cuts once where the square needed two, and you
                        # notice that on material.
                        passes=grid.get("passes") or 1,
                        # On a grid trial the line spacing belongs with the outcome;
                        # without it the preset cannot be burned again.
                        interval_mm=cell.get("interval_mm"),
                        source="testraster",
                        origin_id=f"testgrid:{grid_id}",
                        note=str(pick.get("note") or ""),
                    )
                    self.library.mark_cell(grid_id, key[0], key[1], preset["id"])
                    created.append(preset)
                return {"presets": created}

            return manage(run)

        # -------------------------------------------------------- machine setup

        @app.get("/api/machines/catalog")
        def machine_catalog():
            """MeerK40t's own machine catalogue, grouped by family."""
            return self.machines.catalog()

        @app.get("/api/machines")
        def machine_list():
            return self.machines.list()

        @app.get("/api/machines/scan")
        def machine_scan(network: bool = True, seconds: float = 2.0):
            """
            Search USB, serial and the local network for machines.

            A GET on purpose: this looks, it does not touch. Nothing is created,
            activated or connected here — the caller turns a proposal into a
            machine through POST /api/machines, which does carry the write
            guard. See BESLISSINGEN.md B6.
            """
            return manage(self.machines.scan, network, seconds)

        @app.post("/api/machines", dependencies=write, status_code=201)
        def machine_create(body: dict):
            info = body.get("info")
            if not info:
                raise HTTPException(status_code=422, detail="'info' is missing.")
            return manage(self.machines.create, info, body.get("label"))

        # --------------------------------------- exchanging a machine profile (E5)
        #
        # Before `/machines/{path}`, otherwise that one reads "import" as a path.

        @app.post("/api/machines/import/upload", dependencies=write)
        async def upload_machine_profile(file: UploadFile):
            """Accept the profile and say what it would do — nothing more yet."""
            from .machines import PROFILE_SUFFIX

            target = self._upload_path(file.filename or f"machine{PROFILE_SUFFIX}")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            preview = manage(self.machines.preview_profile, target)
            return {"profile": target.name, **preview}

        @app.post("/api/machines/import", dependencies=write, status_code=201)
        def import_machine_profile(body: dict):
            name = Path(str(body.get("profile") or "")).name
            if not name:
                raise HTTPException(status_code=422, detail="Choose a file first.")
            return manage(
                self.machines.import_profile,
                self._upload_path(name),
                body.get("label"),
            )

        @app.get("/api/machines/{path}/export.openkerf-machine")
        def export_machine_profile(path: str):
            """
            One machine as a file, in the same shape as the library (B7).

            Gap E5: LightBurn supplies `.lbdev`, so that a manufacturer can send a profile
            along and a second computer types nothing over.
            """
            from fastapi.responses import JSONResponse

            from .machines import PROFILE_SUFFIX

            profile = manage(self.machines.export_profile, path)
            safe = "".join(
                c if c.isalnum() or c in "-_" else "-"
                for c in str(profile["machine"]["label"] or path)
            ).strip("-") or path
            return JSONResponse(
                profile,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{safe}{PROFILE_SUFFIX}"'
                    )
                },
            )

        @app.post("/api/machines/{path}/activate", dependencies=write)
        def machine_activate(path: str):
            return manage(self.machines.activate, path)

        @app.post("/api/machines/{path}/rename", dependencies=write)
        def machine_rename(path: str, body: dict):
            label = (body.get("label") or "").strip()
            if not label:
                raise HTTPException(status_code=422, detail="'label' is missing.")
            result = manage(self.machines.rename, path, label)
            # The library carries a copy of the name. It catches up by itself as soon as
            # somebody asks for the active profile, but until that moment an old name is in
            # the list — and right after a rename is exactly when you look at it. The event
            # is here, so it happens here.
            try:
                self.library.profile_for_device(
                    path, label, machine_uid=self.machines.machine_uid_for(path)
                )
            except (LibraryError, MachineError):
                pass
            return result

        @app.delete("/api/machines/{path}", dependencies=write)
        def machine_remove(path: str):
            return manage(self.machines.remove, path)

        @app.get("/api/machines/{path}/settings")
        def machine_settings(path: str, essential: bool = False):
            return manage(self.machines.settings, path, essential)

        @app.patch("/api/machines/{path}/settings", dependencies=write)
        def machine_update_settings(path: str, body: dict):
            return manage(self.machines.update_settings, path, body)

        @app.websocket("/api/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.bridge.add_client(websocket)
            try:
                # Who am I, and since when (gap E2). The WebSocket reconnects by itself,
                # but the page still open then may be from before a restart: the element tree
                # is gone, the sheet is gone, and the app cheerfully goes on showing the
                # design that no longer exists. By this one number the client sees the
                # difference between a network hiccup (same process, nothing wrong) and a
                # restart (fetch everything again).
                await websocket.send_text(
                    json.dumps({"type": "hello", "instance": INSTANCE_ID})
                )
                await websocket.send_text(
                    json.dumps(
                        {"type": "snapshot", "data": self._status_payload()},
                        default=str,
                    )
                )
                while True:
                    # Read-only: incoming frames are drained and ignored, so a
                    # client cannot command the machine over this socket.
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                self.bridge.remove_client(websocket)

        # The static mount has to come last: mounted at "/" it swallows every
        # path that no earlier route claimed.
        if self.frontend is not None and self.frontend.is_dir():
            app.mount("/", _spa_files(str(self.frontend)), name="frontend")
        else:

            @app.get("/", response_class=HTMLResponse)
            def index():
                return _DEV_PAGE

        return app

    async def _heartbeat(self):
        """Push a full snapshot periodically so clients converge after a miss."""
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if self.bridge.client_count:
                await self.bridge.broadcast(
                    {"type": "snapshot", "data": self._status_payload()}
                )

    # ------------------------------------------------------------- lifecycle

    def start(self):
        import uvicorn

        app = self.build_app()
        config = uvicorn.Config(
            app, host=self.bind, port=self.port, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="openkerf-api", daemon=True
        )
        self._thread.start()
        self._attach_signals()
        # Close the camera as soon as nobody is watching. A read thread that runs on for
        # hours costs power and keeps the device busy for other programs; the brake is in
        # Camera.reap().
        self._camera_job = self.kernel.add_job(
            self.camera.reap, name="openkerf-camera-reap", interval=5.0
        )
        # The tail of the automatic saving. `touch` hangs off tree signals, so the last
        # change before you walk away never got a write: no further signal comes to pick it
        # up. This job does, on the kernel thread, so without a second thread in the element
        # tree.
        self._autosave_job = self.kernel.add_job(
            self.autosave.flush, name="openkerf-autosave-flush", interval=5.0
        )
        self.channel(f"OpenKerf API listening on http://{self.bind}:{self.port}/")
        if self.local_only:
            self.channel("Write actions are open (bound to localhost).")
        else:
            self.channel(f"Write actions need this token: {self.token}")

    def _beside(self, name: str, was: str | None = None) -> Path:
        """
        A state file next to the library, moved along if it still has its old name.

        These names were Dutch before the interface became English. They hold live
        work — the sheets you are drawing on, where a layer's settings came from,
        what every palette colour last did — so renaming them without moving them
        would quietly throw that away. Moving only happens when the new name is not
        taken yet; anything else would overwrite newer state with older.

        `was` is optional because a file that never had a Dutch name has nothing to be
        moved from, and passing its own name twice would mean "rename this onto itself"
        — true today, and a trap for whoever reads it next.
        """
        target = Path(self.library.path).with_name(name)
        if was is None:
            return target
        legacy = Path(self.library.path).with_name(was)
        if legacy.exists() and not target.exists():
            try:
                legacy.rename(target)
            except OSError:  # pragma: no cover - a read-only or busy directory
                return legacy
        return target

    def _upload_path(self, filename: str) -> Path:
        """Uploads land in a private temp dir; only the basename is honoured."""
        if self._upload_dir is None:
            self._upload_dir = Path(tempfile.mkdtemp(prefix="openkerf-uploads-"))
        return self._upload_dir / Path(filename).name

    def _upload_dir_for_stage(self) -> Path:
        """
        The same directory, for a file this server writes rather than receives.

        A staged catalogue bundle goes exactly where an uploaded one goes, so that the
        import routes that follow need no idea which of the two it was — and so that it
        is cleaned up with the rest when the server stops.
        """
        return self._upload_path("stage").parent

    def stop(self):
        self._detach_signals()
        job = getattr(self, "_camera_job", None)
        if job is not None:
            self.kernel.unschedule(job)
            self._camera_job = None
        job = getattr(self, "_autosave_job", None)
        if job is not None:
            self.kernel.unschedule(job)
            self._autosave_job = None
        # Once more, while it still can: what was drawn after the last write must not
        # disappear with the process.
        self.autosave.save()
        self.camera.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._server = None
        if self._upload_dir is not None:
            shutil.rmtree(self._upload_dir, ignore_errors=True)
            self._upload_dir = None
        self._wait_for_the_machine_to_go_quiet()
        self.channel("OpenKerf API stopped.")

    # How long we wait on shutdown for the machine to finish talking. Long enough for the
    # tail of a transmission, short enough not to get in the way when a job really is still
    # running.
    QUIET_TIMEOUT_S = 2.0

    def _wait_for_the_machine_to_go_quiet(self):
        """
        Letting the driver's send thread finish its sentence.

        On shutdown this appeared in the user's log:

            Exception in thread Thread-3 (_data_sender):
              ruida/controller.py:128 in _data_sender -> self.write(data)
              ruida/ruidasession.py:186 in write -> ConnectionError(
                  'Not connected to the Ruida controller.')

        That is a thread of MeerK40t's own: `_data_sender` empties its queue without
        checking whether the connection is still there, so as soon as the session under it
        drops out it trips. Fixing that belongs there (see the upstream list in CLAUDE.md) —
        we do not touch `meerk40t/`.

        What we *can* do: not be the first to pull the door shut. We start the device
        service, so we wait here for a moment until it has finished talking before the rest
        of the shutdown removes the connection. Everything behind `getattr`: a dummy device
        has none of these things, and the shutdown must never break on this.
        """
        import time

        device = getattr(self.kernel, "device", None)
        controller = getattr(getattr(device, "driver", None), "controller", None)
        if controller is None:
            return
        deadline = time.monotonic() + self.QUIET_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                if not controller.is_busy:
                    return
            except Exception:
                return
            time.sleep(0.05)

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # ---------------------------------------------------------------- signals

    def _attach_signals(self):
        for code in SIGNALS:
            handler = self._make_handler(code)
            self.kernel.listen(code, handler)
            self._listeners.append((code, handler))

    def _detach_signals(self):
        for code, handler in self._listeners:
            try:
                self.kernel.unlisten(code, handler)
            except Exception:
                pass
        self._listeners.clear()

    def _make_handler(self, code):
        def handler(origin, *args):
            # Tree changes are also the signal to save automatically; the brake is in
            # Autosave, because dragging produces dozens of signals.
            if code in ("tree_changed", "rebuild_tree", "element_property_update"):
                self.autosave.touch()
            self.bridge.publish_threadsafe(
                {
                    "type": "signal",
                    "code": code,
                    "origin": origin,
                    "args": list(args),
                    "time": time.time(),
                }
            )

        return handler


_DEV_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>OpenKerf API — live status</title>
<style>
  body { font: 13px/1.45 "IBM Plex Sans", system-ui, sans-serif;
         background: #16181B; color: #E8EAED; margin: 0; padding: 24px; }
  h1 { font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 16px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 999px;
         background: #9AA3AE; margin-right: 8px; vertical-align: middle; }
  .dot.on { background: #4CAF6D; }
  pre { font: 12px/1.5 "IBM Plex Mono", ui-monospace, monospace;
        background: #1E2126; border: 1px solid #33383F; border-radius: 10px;
        padding: 16px; overflow-x: auto; }
  h2 { font-size: 13px; color: #9AA3AE; font-weight: 500; margin: 24px 0 8px; }
</style>
<h1><span class="dot" id="dot"></span>OpenKerf API — live status</h1>
<h2>Snapshot</h2>
<pre id="snapshot">connecting…</pre>
<h2>Latest signals</h2>
<pre id="events">—</pre>
<script>
  const events = [];
  const ws = new WebSocket(`ws://${location.host}/api/ws`);
  ws.onopen = () => document.getElementById("dot").classList.add("on");
  ws.onclose = () => document.getElementById("dot").classList.remove("on");
  ws.onmessage = (msg) => {
    const payload = JSON.parse(msg.data);
    if (payload.type === "snapshot") {
      document.getElementById("snapshot").textContent =
        JSON.stringify(payload.data, null, 2);
    } else {
      events.unshift(`${payload.code}  ${JSON.stringify(payload.args)}`);
      document.getElementById("events").textContent =
        events.slice(0, 15).join("\\n");
    }
  };
</script>
"""
