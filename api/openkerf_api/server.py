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
import json
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .auth import extract_token, generate_token, is_loopback, token_matches
from .commands import CommandError, CommandRunner
from .design import DesignReader
from .document import Document
from .drawing import Drawing
from .edits import DesignEditor, DesignError
from .images import Images
from .library import BUNDLE_SUFFIX, Library, LibraryError, default_path
from .autosave import Autosave
from .camera import Camera
from .clipart import Clipart
from .fonts import Fonts
from .generators import Generators
from .nesting import Nesting
from .nodes import Nodes
from .palette import Palette, machine_key
from .presetariat import Presetariat
from .provenance import Provenance
from .sheets import Sheets
from .tilerun import TileRun
from .testgrid import (
    TestGridGenerator,
    is_cel_element,
    is_cel_operatie,
    is_raster_groep,
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

# Who this server is, in this process (gap E2). New at every start; the client compares it
# on reconnecting and so knows whether it is talking to the same engine as before the
# silence.
INSTANCE_ID = uuid.uuid4().hex


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
            self.library, Path(self.library.path).with_name("presetariat-cache.json")
        )
        self.editor = DesignEditor(kernel, self.commands)
        self.drawing = Drawing(kernel, self.commands)
        self.motion = MachineControl(kernel, self.commands)
        self.images = Images(kernel, self.commands)
        self.nodes = Nodes(kernel, self.commands)
        self.sheets = Sheets(
            kernel,
            self.drawing,
            self.document,
            Path(self.library.path).with_name("openkerf-vellen"),
        )
        self.tiles = TileRun(
            kernel,
            self.drawing,
            self.sheets,
            self.commands,
            Path(self.library.path).with_name("openkerf-tegelreeks.json"),
        )
        # Where a layer's settings come from. Beside the library, because it is about
        # presets; not *in* it, because it is about this project.
        self.provenance = Provenance(
            Path(self.library.path).with_name("openkerf-herkomst.json")
        )
        # What every palette colour last did on this machine (decision B2). Beside the
        # provenance and emphatically not in it: this is habit, not evidence — see the head
        # of palette.py.
        self.palette = Palette(Path(self.library.path).with_name("openkerf-palet.json"))
        self.generators = Generators(kernel, self.commands, self.drawing, self.sheets)
        self.nesting = Nesting(kernel, self.editor)
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
                str(path), str(getattr(device, "label", "") or path)
            )
        except Exception:
            return None

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

    def _status_payload(self) -> dict:
        """
        Eén snapshot, overal hetzelfde.

        `reader.snapshot()` alone was the kernel and device status; the tile series was
        missing on the WebSocket (`/api/ws`, used by the
        running app) while `/api/status` already sent it along. Top bar, canvas and phone
        view all three read the live socket, so without this field here a running tile
        series never arrived there — exactly what `_tiling_state`'s docstring promised to
        prevent.
        """
        payload = self.reader.snapshot()
        payload["tiling"] = self._tiling_state()
        return payload

    def build_app(self):
        from contextlib import asynccontextmanager

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
            """Run a write action and turn engine-side failure into a 409."""
            try:
                return {"ok": True, "output": action(*args)}
            except CommandError as e:
                raise HTTPException(
                    status_code=409,
                    detail={"command": e.command, "output": e.output},
                ) from e

        def manage(action, *args):
            """
            Same for machine management, where failures are our own.

            Our own refusals carry an optional code, and it travels in a header
            rather than in the body: `detail` is a string everywhere in this API and
            every client reads it that way. A header adds the machine-readable half
            without breaking the human-readable one, so the web app can say the
            refusal in the reader's language while curl still shows a sentence.
            """
            try:
                return action(*args)
            except (MachineError, DesignError, LibraryError) as e:
                code = getattr(e, "code", None)
                raise HTTPException(
                    status_code=409,
                    detail=str(e),
                    headers={"X-OpenKerf-Error": code} if code else None,
                ) from e
            except CommandError as e:
                raise HTTPException(
                    status_code=409, detail={"command": e.command, "output": e.output}
                ) from e

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
            """Upload a design and load it into the element tree."""
            target = self._upload_path(file.filename or "upload.svg")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            result = act(self.commands.load_file, str(target))
            # Net geladen: het ontwerp is gelijk aan het bestand.
            self.document.clean()
            return result

        @app.post("/api/job/start", dependencies=write)
        def start_job():
            """Plan the current operations and hand the job to the spooler."""
            # The sheet's name as the job name (gap P4): that is what goes into the
            # machine, and it is the only word the user chose themselves. Without this a
            # nameless job is called "Spooler:3 items".
            sheet = self._active_sheet() or {}

            def run():
                # Gap J12: when a zero point is set, the work goes into the machine from
                # there. The shift lives only while the plan is being built; after that the
                # drawing is back where it was.
                with self.drawing.verschoven(self.motion.origin()):
                    return self.commands.start_job(sheet.get("name"))

            return act(run)

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
            Opnieuw beginnen: leeg ontwerp, één leeg sheet.

            Saving and opening already existed, starting over did not — the only way to
            make a new project was to remove everything by hand, and anybody who forgets
            that burns yesterday's remnants along.

            The library stays. Materials, presets and machine profiles are what you know
            about your laser; they belong not to *this* project but to this workshop. A
            project file does carry them along, because there they go to somebody else.
            """

            def run():
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
            """Ontwerp plus bibliotheek-context in één bestand."""
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
            """
            return manage(
                lambda: self.drawing.estimate(
                    self.library,
                    self.provenance,
                    self._active_sheet(),
                    exact=exact,
                )
            )

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
            """Verenigen, verschil, doorsnede of uitsluiten."""
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
            """To the zero point. The head really moves."""
            return manage(self.motion.home, bool((body or {}).get("physical")))

        @app.post("/api/machine/move", dependencies=write)
        def machine_move(body: dict):
            return manage(self.motion.move_to, body.get("x_mm"), body.get("y_mm"))

        @app.post("/api/machine/jog", dependencies=write)
        def machine_jog(body: dict):
            return manage(self.motion.jog, body.get("dx_mm"), body.get("dy_mm"))

        # -- bewaarde positions (gat J6) — eigen blokje, zie machine.py ------
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

        # -- einde blok positions --------------------------------------------

        # -- gebruikersoorsprong (gat J12) — zie machine.py -----------------
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

        # -- bijstellen tijdens een lopende job (gat J11) -------------------
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
                nulpunt = self.motion.origin() or {}
                x, y, width, height = doos
                return self.motion.frame(
                    x + float(nulpunt.get("x_mm") or 0.0),
                    y + float(nulpunt.get("y_mm") or 0.0),
                    width,
                    height,
                )

            return manage(run)

        @app.post("/api/machine/connect", dependencies=write)
        def connect_machine():
            """
            De verbinding opzetten.

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
            Eén klik op een paletvakje.

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
            """Graveren vóór snijden, in één handeling (gat L2)."""
            return manage(self.drawing.sort_operations)

        @app.post("/api/design/operations/{operation_id}/move", dependencies=write)
        def move_operation(operation_id: str, body: dict):
            """
            Een layer verplaatsen in de brandvolgorde.

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
            Een path opdelen in zijn losse stukken.

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

        @app.delete("/api/library/materials/{material_id}", dependencies=write)
        def remove_material(material_id: int):
            return manage(self.library.remove_material, material_id)

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
            return profile

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
            """
            levend = {
                device.path: str(getattr(device, "label", "") or device.path)
                for device in self.kernel.services("device")
                if self.machines._configured(device)
            }
            self.library.refresh_names(levend)
            paden = set(levend)
            return [
                {
                    **profile,
                    "orphaned": bool(profile["device_path"])
                    and profile["device_path"] not in paden,
                    **self.library.machine_usage(profile["id"]),
                }
                for profile in self.library.machines()
            ]

        @app.delete("/api/library/machines/{machine_id}", dependencies=write)
        def remove_machine_profile(machine_id: int):
            # The machine you are working on now keeps its profile. It would not be gone
            # anyway: the next read route creates it again, and then the only difference is
            # that all the presets that hung off it have come loose.
            actief = self._active_profile()
            if actief and actief["id"] == machine_id:
                raise HTTPException(
                    status_code=409,
                    detail="This is the machine you are working on; it cannot go.",
                )
            return manage(self.library.remove_machine, machine_id)

        @app.post("/api/library/machines", dependencies=write, status_code=201)
        def add_machine_profile(body: dict):
            return manage(lambda: self.library.add_machine(**body))

        # ------------------------------------------ bibliotheek uitwisselen (B7)

        @app.get("/api/library/export.openkerf-lib")
        def export_library(filename: str = "bibliotheek"):
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
            target = self._upload_path(file.filename or f"bibliotheek{BUNDLE_SUFFIX}")
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
            vellen = {
                s["id"]: names.get(s.get("material_id"))
                for s in self.sheets.state()["sheets"]
            }
            result = manage(
                self.library.import_bundle,
                target,
                body.get("mode") or "samenvoegen",
                body.get("merge_materials"),
                body.get("on_conflict") or "eigen",
            )
            opnieuw = {m["name"]: m["id"] for m in self.library.materials()}
            for sheet_id, name in vellen.items():
                if name and opnieuw.get(name) is not None:
                    self.sheets.update(sheet_id, material_id=opnieuw[name])
            return result

        @app.post("/api/library/presets/{preset_id}/apply", dependencies=write)
        def apply_preset(preset_id: int, body: dict):
            """Write a preset's speed, power and passes onto an operation."""
            operation_id = body.get("operation_id")
            if not operation_id:
                raise HTTPException(status_code=422, detail="'operation_id' ontbreekt.")

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

        # ----------------------------------------------------------------- vellen

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

        # ----------------------------------------------------------------- tegels

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
            return manage(self.tiles.start)

        @app.post("/api/tiling/align", dependencies=write)
        def tiling_align(body: dict):
            """
            The tapped points. `use_current: true` takes the head position, so that you can
            aim with the jog buttons and then press 'Here' once.
            """

            def run():
                points = list(body.get("points") or [])
                if body.get("use_current"):
                    huidig = self.motion._current_mm()
                    if huidig is None:
                        raise DesignError(
                            "This machine reports no position, so 'Here' does not know "
                            "where it is. Fill in the coordinates by hand."
                        )
                    points.append({"x_mm": huidig[0], "y_mm": huidig[1]})
                return self.tiles.align(points, body.get("reference") or "markers")

            return manage(run)

        @app.post("/api/tiling/burn", dependencies=write)
        def tiling_burn(body: dict | None = None):
            confirm = bool((body or {}).get("confirm"))
            return manage(lambda: self.tiles.burn(confirm_reburn=confirm))

        @app.post("/api/tiling/advance", dependencies=write)
        def tiling_advance():
            return manage(self.tiles.advance)

        @app.post("/api/tiling/cancel", dependencies=write)
        def tiling_cancel():
            return manage(self.tiles.cancel)

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
            """De selectie in rijen en kolommen herhalen."""
            return manage(
                self.generators.grid,
                body.get("ids") or [],
                body.get("columns"),
                body.get("rows"),
                body.get("gap_x_mm", 5.0),
                body.get("gap_y_mm", 5.0),
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

        @app.post("/api/presetariat/import", dependencies=write)
        def import_catalogue_presets(body: dict):
            return manage(
                self.presetariat.import_presets,
                body.get("ids") or [],
                body.get("machine_id"),
            )

        @app.get("/api/presetariat/contribution/{preset_id}")
        def preset_contribution(preset_id: int):
            """One of your own presets in catalogue form, with a prefilled proposal."""
            return manage(self.presetariat.as_contribution, preset_id)

        # ---------------------------------------------------------- testrasters

        def grid_fields(body: dict) -> dict:
            """
            Wat het bord aan het formulier toevoegt: machine, datum, material.

            Preview and reality use the same lines here. They have to: the caption decides
            how wide the board becomes, so a preview without a date reports a narrower board
            than the one that burns.
            """
            from datetime import date

            fields = dict(body)
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
                plan, cells = plan_grid(**grid_fields(body))
                # Het grid is één object op het canvas — vakjes, aslabels,
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

        # ---------------------------------------- benoemde recepten (gat T7)
        #
        # Before `/testgrids/{grid_id}`, otherwise that route catches "recipes" as an id.
        # That is FastAPI's order of declaration, not of specificity.

        @app.get("/api/library/testgrids/recipes")
        def list_grid_recipes(material_id: int | None = None):
            """
            Bewaarde generatorinstellingen onder een name.

            T3 remembers the previous grid per material; this is the same in the plural, so
            that "cut birch" and "engrave birch" can sit beside
            kunnen bestaan. Dezelfde sleutels, zodat de wizard beide op
            dezelfde manier invult.
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
                    if node is not None and is_raster_groep(node):
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
                    if getattr(op, "label", None) == "Raster-labels" and not list(op.children):
                        op.remove_node()
                self.library.set_grid_group(grid_id, None)
                self.kernel.elements.signal("rebuild_tree", "all")
                return removed

            return manage(run)

        @app.delete("/api/library/testgrids/{grid_id}", dependencies=write)
        def remove_test_grid(grid_id: int):
            return manage(self.library.remove_test_grid, grid_id)

        @app.post("/api/library/testgrids/{grid_id}/photo", dependencies=write)
        async def upload_grid_photo(grid_id: int, file: UploadFile):
            """The photo of the burned grid — usually taken on a phone."""
            suffix = Path(file.filename or "").suffix
            data = await file.read()
            if not data:
                raise HTTPException(status_code=422, detail="Lege foto.")
            return manage(self.library.set_grid_photo, grid_id, suffix, data)

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
                row, column = (int(deel) for deel in str(cell).split("-", 1))
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
                raise HTTPException(status_code=422, detail="Kies minstens één vakje.")

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
                raise HTTPException(status_code=422, detail="'info' ontbreekt.")
            return manage(self.machines.create, info, body.get("label"))

        # ------------------------------------- machineprofiel uitwisselen (E5)
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
            veilig = "".join(
                c if c.isalnum() or c in "-_" else "-"
                for c in str(profile["machine"]["label"] or path)
            ).strip("-") or path
            return JSONResponse(
                profile,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{veilig}{PROFILE_SUFFIX}"'
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
                raise HTTPException(status_code=422, detail="'label' ontbreekt.")
            result = manage(self.machines.rename, path, label)
            # The library carries a copy of the name. It catches up by itself as soon as
            # somebody asks for the active profile, but until that moment an old name is in
            # the list — and right after a rename is exactly when you look at it. The event
            # is here, so it happens here.
            try:
                self.library.profile_for_device(path, label)
            except LibraryError:
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

    def _upload_path(self, filename: str) -> Path:
        """Uploads land in a private temp dir; only the basename is honoured."""
        if self._upload_dir is None:
            self._upload_dir = Path(tempfile.mkdtemp(prefix="openkerf-uploads-"))
        return self._upload_dir / Path(filename).name

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
        einde = time.monotonic() + self.QUIET_TIMEOUT_S
        while time.monotonic() < einde:
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
<pre id="snapshot">verbinden…</pre>
<h2>Laatste signalen</h2>
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
