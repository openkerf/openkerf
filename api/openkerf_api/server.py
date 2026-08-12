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
    "Camerabeeld vraagt OpenCV. Installeer het naast de engine met "
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

# Wie deze server is, in dit proces (gat E2). Nieuw bij elke start; de client
# vergelijkt hem bij het herverbinden en weet zo of hij tegen dezelfde engine
# praat als vóór de stilte.
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

    Een onbekend `/api`-pad valt hier **niet** onder. Dat gebeurde eerder wel,
    met twee misleidende gevolgen: een GET kreeg de HTML-pagina terug (waar de
    frontend JSON verwachtte) en een POST kreeg "405 Method Not Allowed", omdat
    de fallback alleen GET kent. Wie een oudere server draait naast een nieuwere
    frontend, zag dus een onbegrijpelijke foutmelding in plaats van "die route
    ken ik niet".
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
                            f"Onbekende API-route '/{path}'. Draait de server "
                            "misschien op oudere code dan de frontend? Herstart "
                            "hem dan."
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
        # Waar de instellingen van een laag vandaan komen. Naast de bibliotheek,
        # want het gaat over presets; niet erín, want het gaat over dit project.
        self.provenance = Provenance(
            Path(self.library.path).with_name("openkerf-herkomst.json")
        )
        # Wat elke paletkleur op deze machine het laatst deed (besluit B2).
        # Naast de herkomst en nadrukkelijk niet erin: dit is gewoonte, geen
        # bewijs — zie de kop van palette.py.
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
        # Besluit B2: een laag die tijdens het tekenen ontstaat, begint op wat
        # die kleur op deze machine eerder deed.
        self.drawing.color_memory = lambda kleur: self.palette.recall(
            self._palette_machine()[0], kleur
        )
        # Gat J12: het nulpunt woont op de machine (machine.py) en bepaalt waar
        # het werk terechtkomt. Eén bron, twee lezers — de pre-flight en het
        # spoolen.
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
        Het bibliotheekprofiel van de machine die de engine nu gebruikt.

        De engine kent devices, de bibliotheek kent profielen; dit is de knoop
        ertussen. Geen actief device betekent geen profiel — dan tonen we alles.
        """
        device = getattr(self.kernel, "device", None)
        pad = getattr(device, "path", None) if device is not None else None
        if not pad:
            return None
        try:
            return self.library.profile_for_device(
                str(pad), str(getattr(device, "label", "") or pad)
            )
        except Exception:
            return None

    def _palette_machine(self):
        """
        Onder welke machine het palet-geheugen valt, en hoe die heet.

        Snelheid en vermogen zijn machine-eigenschappen: 12 mm/s op 80 watt is
        een andere snede dan op 40. Een geheugen dat dat door elkaar haalt is
        erger dan geen geheugen, dus het hangt aan de machine of aan niets.
        """
        profile = self._active_profile()
        naam = None
        if profile:
            naam = profile.get("name") or profile.get("device_path")
        return machine_key(profile), naam

    def _remember_layer(self, operation_id: str) -> None:
        """
        Leg vast wat de kleur van deze laag nu doet.

        Aangeroepen ná een geslaagde wijziging, want een geweigerde poging is
        geen gewoonte. Faalt dit, dan is er hoogstens geen geheugen — het mag
        nooit de wijziging zelf laten stranden.
        """
        try:
            operation = self.drawing._operation(operation_id)
            color = self.drawing._usable_color(operation)
            if color is None:
                return
            power = getattr(operation, "power", None)
            key, naam = self._palette_machine()
            self.palette.remember(
                key,
                color,
                speed=getattr(operation, "speed", None),
                power_percent=None if power is None else float(power) / 10,
                kind=str(getattr(operation, "type", "") or ""),
                machine_name=naam,
            )
        except Exception:
            return

    def _active_sheet(self):
        """
        Het vel waarop nu gewerkt wordt, met de naam van zijn materiaal erbij.

        Het vel bewaart alleen een id — de bibliotheek weet hoe het heet, en
        zonder die naam kan de pre-flight niet zeggen wáárin je brandt.
        """
        try:
            sheet = self.sheets.active()
        except Exception:
            return None
        if sheet is None:
            return None
        naam = None
        if sheet.get("material_id") is not None:
            try:
                naam = next(
                    (
                        m["name"]
                        for m in self.library.materials()
                        if m["id"] == sheet["material_id"]
                    ),
                    None,
                )
            except Exception:
                naam = None
        return {**sheet, "material_name": naam}

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
            """Same for machine management, where failures are our own."""
            try:
                return action(*args)
            except (MachineError, DesignError, LibraryError) as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
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
            return self.reader.snapshot()

        @app.get("/api/devices")
        def devices():
            return self.reader.snapshot()["devices"]

        @app.get("/api/design")
        def design():
            """Element outlines and the operations that claim them."""
            snapshot = self.design.snapshot()
            # Zodat de frontend weet of openen werk zou weggooien.
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
                # Gat J11: bijstellen tijdens een lopende job kan alleen als de
                # driver een realtime kanaal heeft. Op een Ruida staat hier
                # false, en dan hoort er geen knop te zijn.
                "adjust": self.motion.adjust_capabilities(),
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
            # De naam van het vel als jobnaam (gat P4): dat is wat er in de
            # machine gaat, en het is het enige woord dat de gebruiker zelf
            # heeft gekozen. Zonder dit heet een naamloze job "Spooler:3 items".
            sheet = self._active_sheet() or {}

            def run():
                # Gat J12: staat er een nulpunt, dan gaat het werk daarvandaan
                # de machine in. De verschuiving leeft alleen zolang het plan
                # gebouwd wordt; daarna staat de tekening weer waar hij stond.
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

        # ------------------------------------------------ tekenen en lagen

        @app.post("/api/design/elements", dependencies=write, status_code=201)
        def create_element(body: dict):
            """Draw a shape or a line of text on the bed."""
            kind = body.get("type")
            return manage(lambda: self.drawing.create(kind, **body))

        @app.post("/api/design/clear", dependencies=write)
        def clear_design():
            """Leeg het ontwerp — wat openen doet voordat het een bestand inleest."""
            def run():
                self.kernel.elements.clear_all()
                self.drawing.user_operations.clear()
                self.document.clean()
                return {"cleared": True}

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
            """De pixels van een afbeelding, zodat het canvas hem kan tonen."""
            from fastapi.responses import Response

            return Response(
                content=manage(self.images.render_png, element_id),
                media_type="image/png",
            )

        @app.get("/api/design/elements/{element_id}/image")
        def image_adjustments(element_id: str):
            """Welke bewerkingen aanstaan en met welke waarden."""
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
            """De knooppunten van een vorm, om ze los te kunnen verslepen."""
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
            """Bijsnijden terugdraaien; het origineel is nooit weggegooid."""
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
            """Welke vectoriseerders geladen zijn — potrace kan ontbreken."""
            return {"methods": self.images.vectorisers()}

        @app.get("/api/design/fonts")
        def list_fonts(refresh: bool = False):
            """
            De lettertypen die de engine kan gebruiken.

            De engine houdt die lijst in een cachebestand, dus een net
            geïnstalleerd lettertype verschijnt pas na `refresh=true`.
            """
            if refresh:
                manage(self.fonts.refresh)
            return manage(self.drawing.fonts)

        @app.get("/api/design/fonts/file")
        def font_file(name: str):
            """
            Het lettertypebestand zelf, zodat de keuzelijst elke naam in zijn
            eigen letter kan tonen — kiezen op zicht in plaats van op naam.
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
            """Lettertypen op dit systeem die de engine niet leest, maar wij wel."""
            return manage(self.fonts.importable)

        @app.post("/api/design/fonts/import", dependencies=write, status_code=201)
        def import_font(body: dict):
            return manage(self.fonts.import_font, body.get("file"))

        @app.get("/api/job/layers")
        def job_layers():
            """
            Wat er gebrand wordt en waar die instellingen vandaan komen —
            zonder de klok.

            Bewust een eigen route naast `/api/job/estimate`: die bouwt voor de
            tijdschatting het hele snijplan, en dat duurt op een zwaar ontwerp
            minuten (gat J1). Een waarschuwing dat een laag een instelling van
            ánder materiaal draagt, mag daar niet achteraan hoeven staan — dat
            is nu juist wat je vóór het starten moet weten. Hier wordt niets
            gepland: dit leest de elementenboom, de bibliotheek en de herkomst.

            Om diezelfde reden dragen ook `bounds` en `engine` hier: dat een
            vorm buiten het bed valt of dat deze engine geen rasters brandt, is
            geen klokgegeven maar een blokkade. Stond het alleen in
            `/api/job/estimate`, dan verscheen "valt buiten het bed" pas als de
            tijdschatting terug was.
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
            Wat de machine gaat doen, vóór starten: tijd, onderdelen én per
            laag de instellingen met hun herkomst.

            `exact=1` rekent langs het volledige snijplan, zoals deze route
            vroeger altijd deed. Dat kost op een zwaar ontwerp minuten en is
            alleen bedoeld om de snelle schatting tegen te ijken.
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
            """Een eindpunt verzetten; een lijn is twee punten, geen kader."""
            return manage(lambda: self.drawing.update_line(element_id, **body))

        @app.post("/api/design/offset", dependencies=write)
        def offset_elements(body: dict):
            return manage(self.drawing.offset, body.get("ids"), body.get("distance_mm"))

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
            """Naar het nulpunt. De kop beweegt echt."""
            return manage(self.motion.home, bool((body or {}).get("physical")))

        @app.post("/api/machine/move", dependencies=write)
        def machine_move(body: dict):
            return manage(self.motion.move_to, body.get("x_mm"), body.get("y_mm"))

        @app.post("/api/machine/jog", dependencies=write)
        def machine_jog(body: dict):
            return manage(self.motion.jog, body.get("dx_mm"), body.get("dy_mm"))

        # -- bewaarde posities (gat J6) — eigen blokje, zie machine.py ------
        @app.get("/api/machine/positions")
        def machine_positions():
            """Posities die deze machine onthoudt: mal, nulpunt van een jig."""
            return manage(lambda: {"positions": self.motion.positions()})

        @app.post("/api/machine/positions", dependencies=write, status_code=201)
        def save_machine_position(body: dict):
            """Zonder x/y: waar de kop nu staat."""
            return manage(
                self.motion.save_position,
                body.get("name"),
                body.get("x_mm"),
                body.get("y_mm"),
            )

        @app.delete("/api/machine/positions", dependencies=write)
        def delete_machine_position(name: str):
            return manage(self.motion.delete_position, name)

        # -- einde blok posities --------------------------------------------

        # -- gebruikersoorsprong (gat J12) — zie machine.py -----------------
        @app.get("/api/machine/origin")
        def machine_origin():
            """Het nulpunt van deze machine, of null als er geen gezet is."""
            return manage(lambda: {"origin": self.motion.origin()})

        @app.post("/api/machine/origin", dependencies=write)
        def set_machine_origin(body: dict | None = None):
            """Zonder x/y: waar de kop nu staat."""
            velden = body or {}
            return manage(
                self.motion.set_origin, velden.get("x_mm"), velden.get("y_mm")
            )

        @app.delete("/api/machine/origin", dependencies=write)
        def clear_machine_origin():
            return manage(self.motion.clear_origin)

        # -- bijstellen tijdens een lopende job (gat J11) -------------------
        @app.get("/api/job/adjust")
        def job_adjustment():
            """Wat er nu bijgesteld staat, en of deze machine het überhaupt kan."""
            return manage(self.motion.adjustment)

        @app.post("/api/job/adjust", dependencies=write)
        def adjust_job(body: dict):
            """Snelheid en/of vermogen schalen, ook midden in een job."""
            return manage(self.motion.adjust, body.get("power"), body.get("speed"))

        @app.post("/api/machine/focus", dependencies=write)
        def focus_machine(body: dict):
            """Scherpstellen: de kop hoger of lager. Alleen als het apparaat het kent."""
            return manage(self.motion.focus, body.get("distance_mm"))

        @app.post("/api/machine/frame", dependencies=write)
        def frame_design(body: dict | None = None):
            """
            De kop langs de omtrek van het werk sturen, zonder te branden.

            Zonder maten in het verzoek pakt hij de omhullende rechthoek van wat
            er nu op het bed ligt — dat is wat je wilt controleren.
            """
            def run():
                velden = body or {}
                if velden.get("width_mm"):
                    return self.motion.frame(
                        velden.get("x_mm"), velden.get("y_mm"),
                        velden.get("width_mm"), velden.get("height_mm"),
                    )
                doos = self.design.bounds_mm()
                if doos is None:
                    raise DesignError("Er ligt niets op het bed om te omkaderen.")
                # Gat J12: kaderen moet laten zien waar het écht komt te
                # liggen. Een kader op de tekencoördinaten terwijl het nulpunt
                # het werk 100 mm opzij zet, is precies de controle die je
                # dacht gedaan te hebben.
                nulpunt = self.motion.origin() or {}
                x, y, breedte, hoogte = doos
                return self.motion.frame(
                    x + float(nulpunt.get("x_mm") or 0.0),
                    y + float(nulpunt.get("y_mm") or 0.0),
                    breedte,
                    hoogte,
                )

            return manage(run)

        @app.post("/api/machine/unlock", dependencies=write)
        def machine_unlock():
            return manage(self.motion.unlock)

        @app.post("/api/machine/lock", dependencies=write)
        def machine_lock():
            return manage(self.motion.lock)

        @app.patch("/api/design/elements/{element_id}/text", dependencies=write)
        def update_text(element_id: str, body: dict):
            """Bestaande tekst bijwerken in plaats van weggooien en opnieuw plaatsen."""
            return manage(lambda: self.drawing.update_text(element_id, **body))

        @app.post("/api/design/elements/delete", dependencies=write)
        def delete_elements(body: dict):
            return manage(self.drawing.delete, body.get("ids"))

        @app.post("/api/design/elements/duplicate", dependencies=write)
        def duplicate_elements(body: dict):
            return manage(self.drawing.duplicate, body.get("ids"))

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
                # Besluit B2: de kleur onthoudt wat je er het laatst mee deed.
                self._remember_layer(operation_id)
                return result

            return manage(run)

        # ------------------------------------------------------- palet (B2)

        @app.get("/api/design/palette")
        def design_palette():
            """
            De kleurenstrook onder het canvas: tien kleuren met hun geheugen.

            Alleen het geheugen komt hiervandaan. Wélke laag nu welke kleur
            heeft, staat al in `/api/design` — dat twee keer sturen is twee
            waarheden die uit elkaar kunnen lopen.
            """
            key, naam = self._palette_machine()
            onthouden = self.palette.all(key)
            return {
                "machine": {"key": key, "name": naam},
                "default_color": self.drawing.default_color(),
                "colors": [
                    {"color": kleur.lower(), "memory": onthouden.get(kleur.lower())}
                    for kleur in self.drawing.PALETTE
                ],
            }

        @app.post("/api/design/palette", dependencies=write)
        def use_palette_color(body: dict):
            """
            Eén klik op een paletvakje.

            Mét selectie: die verhuist naar de laag van die kleur, die zo nodig
            wordt aangemaakt op wat die kleur eerder deed. Zonder selectie: de
            kleur voor nieuw werk. Dat onderscheid komt van LightBurn en is de
            reden dat toewijzen daar één handeling is en bij ons drie.
            """
            kleur = body.get("color")
            ids = body.get("ids") or []
            key, _naam = self._palette_machine()

            def run():
                memory = self.palette.recall(key, kleur)
                if ids:
                    result = self.drawing.paint(ids, kleur, memory)
                    self._remember_layer(result["operation_id"])
                    return result
                return {**self.drawing.set_default_color(kleur), "operation_id": None}

            return manage(run)

        @app.get("/api/design/capabilities")
        def design_capabilities():
            """
            Wat een laag op déze machine kan (besluit B11).

            Air assist staat als schakelaar in de rij, maar alleen als de
            driver er een commando voor kent — dezelfde regel als bij de Z-as.
            Wat de machine niet kan, hoort niet als knop op het scherm.
            """
            return {"air_assist": self.drawing.air_assist_supported()}

        @app.post("/api/design/operations/sort", dependencies=write)
        def sort_operations():
            """Graveren vóór snijden, in één handeling (gat L2)."""
            return manage(self.drawing.sort_operations)

        @app.post("/api/design/operations/{operation_id}/move", dependencies=write)
        def move_operation(operation_id: str, body: dict):
            """
            Een laag verplaatsen in de brandvolgorde.

            `direction` is één stap (de knoppen), `index` is een bestemming
            (slepen, gat L1).
            """
            return manage(
                lambda: self.drawing.move_operation(
                    operation_id, body.get("direction"), body.get("index")
                )
            )

        @app.post("/api/design/operations/{operation_id}/type", dependencies=write)
        def retype_operation(operation_id: str, body: dict):
            """
            Een snijlaag graveerlaag maken, met de vormen erin (gat L3).

            Een eigen route en geen PATCH: de laag wordt vervangen en krijgt
            een nieuw id. Dat stilzwijgend onder een PATCH doen zou betekenen
            dat de aanroeper achteraf naar een laag verwijst die niet meer
            bestaat.
            """
            return manage(
                lambda: self.drawing.change_operation_type(
                    operation_id, body.get("type")
                )
            )

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
            De presets, standaard van de machine die nu actief is.

            Een preset geldt voor één laser op één materiaal; alles door elkaar
            tonen is de verwarring die dit oplost. `all_machines=true` toont de
            rest erbij.
            """
            profiel = None if all_machines else self._active_profile()
            return self.library.presets(
                material_id, operation, profiel["id"] if profiel else None
            )

        @app.get("/api/library/active-machine")
        def active_machine():
            """
            Het profiel van de actieve machine, desnoods vers aangemaakt.

            De frontend heeft dit nodig om te zeggen wiens presets je ziet, en
            om te weten of er een Z-as of autofocus is.
            """
            profiel = self._active_profile()
            if profiel is None:
                raise HTTPException(status_code=409, detail="Er is geen actieve machine.")
            return profiel

        @app.patch("/api/library/machines/{machine_id}", dependencies=write)
        def update_machine(machine_id: int, body: dict):
            return manage(self.library.update_machine, machine_id, body)

        @app.post("/api/library/presets", dependencies=write, status_code=201)
        def add_preset(body: dict):
            # Zonder profiel hangt een preset in de lucht; de actieve machine is
            # het enige zinnige standaardantwoord.
            velden = dict(body)
            if not velden.get("machine_id"):
                profiel = self._active_profile()
                if profiel:
                    velden["machine_id"] = profiel["id"]
            return manage(lambda: self.library.add_preset(**velden))

        @app.patch("/api/library/presets/{preset_id}", dependencies=write)
        def update_preset(preset_id: int, body: dict):
            return manage(lambda: self.library.update_preset(preset_id, **body))

        @app.get("/api/library/suggest")
        def suggest_grid_range(
            material_id: int | None = None,
            operation: str | None = None,
            thickness_mm: float | None = None,
        ):
            """Voorstel voor een rasterbereik rond bestaande presets."""
            return self.library.suggest_range(material_id, operation, thickness_mm)

        @app.delete("/api/library/presets/{preset_id}", dependencies=write)
        def remove_preset(preset_id: int):
            return manage(self.library.remove_preset, preset_id)

        @app.get("/api/library/machines")
        def list_machine_profiles():
            return self.library.machines()

        @app.post("/api/library/machines", dependencies=write, status_code=201)
        def add_machine_profile(body: dict):
            return manage(lambda: self.library.add_machine(**body))

        # ------------------------------------------ bibliotheek uitwisselen (B7)

        @app.get("/api/library/export.openkerf-lib")
        def export_library(filename: str = "bibliotheek"):
            """De hele bibliotheek als één bestand, foto's inbegrepen."""
            from fastapi.responses import FileResponse

            path = manage(self.library.export_bundle, filename)
            return FileResponse(
                path, media_type="application/zip", filename=path.name
            )

        @app.post("/api/library/import/upload", dependencies=write)
        async def upload_library(file: UploadFile):
            """
            Het bestand aannemen en zeggen wat het zou doen — nog niets meer.

            Het blijft onder zijn eigen naam in de uploadmap staan, zodat het
            voorbeeld herrekend kan worden zonder opnieuw te uploaden.
            """
            target = self._upload_path(file.filename or f"bibliotheek{BUNDLE_SUFFIX}")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            preview = manage(self.library.preview_import, target)
            return {"bundle": target.name, **preview}

        def _bundle(body: dict) -> Path:
            naam = Path(str(body.get("bundle") or "")).name
            if not naam:
                raise HTTPException(status_code=422, detail="Kies eerst een bestand.")
            return self._upload_path(naam)

        @app.post("/api/library/import/preview", dependencies=write)
        def preview_library(body: dict):
            """Hetzelfde voorbeeld, herrekend met de samenvoegkeuzes erin."""
            target = _bundle(body)
            preview = manage(
                self.library.preview_import, target, body.get("merge_materials")
            )
            return {"bundle": target.name, **preview}

        @app.post("/api/library/import", dependencies=write)
        def import_library(body: dict):
            target = _bundle(body)
            # Welk materiaal op welk vel lag, in namen: bij vervangen krijgen
            # materialen nieuwe id's en zou het vel anders naar niets wijzen.
            namen = {m["id"]: m["name"] for m in self.library.materials()}
            vellen = {
                s["id"]: namen.get(s.get("material_id"))
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
            for sheet_id, naam in vellen.items():
                if naam and opnieuw.get(naam) is not None:
                    self.sheets.update(sheet_id, material_id=opnieuw[naam])
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
                # Pas ná een geslaagde toepassing: een mislukte poging is geen
                # gebruik, en "onlangs gebruikt" moet waar blijven.
                self.library.touch_preset(preset_id)
                # En onthouden wáár deze getallen vandaan komen. Zonder dat
                # briefje moet de pre-flight de herkomst raden aan de waarden,
                # en dan is een instelling voor ander materiaal niet te zien.
                self.provenance.record(self.sheets.active_id, operation_id, preset)
                # En het palet onthoudt wat deze kleur nu doet. Dat is iets
                # anders dan de herkomst hierboven: het geheugen draagt geen
                # bewijs mee, alleen de gewoonte (zie palette.py).
                self._remember_layer(operation_id)
                return {**result, "preset": preset}

            return manage(run)

        # ---------------------------------------------------------------- camera

        @app.get("/api/camera")
        def camera_state():
            """Of er een camera is, of hij draait, en of hij geijkt is."""
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
            """Eén beeld — voor het ijken, en als terugval zonder stream."""
            from fastapi.responses import Response

            return Response(
                content=manage(self.camera.frame_png),
                media_type="image/png",
                # Elk verzoek moet vers beeld opleveren; een gecachet beeld van
                # het bed is precies wat je niet wilt.
                headers={"Cache-Control": "no-store"},
            )

        @app.get("/api/camera/stream.mjpeg")
        async def camera_stream(request: Request):
            """
            Doorlopend beeld. De browser zet dit in een gewone <img> en
            decodeert zelf — geen JavaScript-lus, geen haperingen.

            De lus vraagt bij elke ronde of de browser nog luistert. Zonder die
            vraag merkt de server een weggeklikt tabblad niet en blijft de
            camera draaien voor een kijker die er niet meer is; dat is precies
            wat er gebeurde toen dit een gewone generator was.
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
            """De vier bedhoeken in het beeld: linksboven met de klok mee."""
            return manage(
                self.camera.calibrate, body.get("points"), body.get("corrected")
            )

        @app.delete("/api/camera/calibrate", dependencies=write)
        def camera_reset_calibration():
            return manage(self.camera.reset_calibration)

        @app.post("/api/camera/corrected", dependencies=write)
        def camera_corrected(body: dict):
            """Tijdens het ijken wil je juist het onbewerkte beeld zien."""
            return manage(self.camera.set_corrected, bool(body.get("corrected")))

        # ----------------------------------------------------------------- vellen

        @app.get("/api/sheets")
        def list_sheets():
            """De vellen van dit project, en welke actief is."""
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
            Wisselen van vel: het huidige wordt opgeslagen, het andere geladen.
            Wat je ziet is daarna precies wat er gebrand wordt.
            """
            return manage(self.sheets.activate, sheet_id)

        @app.patch("/api/sheets/{sheet_id}", dependencies=write)
        def update_sheet(sheet_id: str, body: dict):
            return manage(lambda: self.sheets.update(sheet_id, **body))

        @app.delete("/api/sheets/{sheet_id}", dependencies=write)
        def delete_sheet(sheet_id: str):
            def run():
                state = self.sheets.remove(sheet_id)
                # Vel-nummers worden hergebruikt; zonder dit erft een nieuw
                # vel de herkomst van het vel dat hier net weg is.
                self.provenance.forget_sheet(sheet_id)
                return state

            return manage(run)

        @app.post("/api/sheets/{sheet_id}/move", dependencies=write)
        def move_to_sheet(sheet_id: str, body: dict):
            return manage(self.sheets.move_selection, body.get("ids") or [], sheet_id)

        # --------------------------------------------------------------- clipart

        @app.get("/api/clipart/search")
        def clipart_search(
            q: str, sources: str | None = None, limit: int = 24, page: int = 1
        ):
            """
            Zoeken in openbare collecties, via onze server.

            Een bron die niet antwoordt, houdt de rest niet op: hij komt terug
            in 'unavailable' zodat de app het kan melden.
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
            """Of er werk van een vorige sessie klaarstaat."""
            return self.autosave.state()

        @app.post("/api/design/autosave/restore", dependencies=write)
        def restore_autosave():
            def run():
                if any(True for _ in self.kernel.elements.elems()):
                    raise LibraryError(
                        "Er staat al iets op het canvas. Maak eerst leeg; "
                        "herstellen bovenop bestaand werk geeft een mengelmoes."
                    )
                return self.autosave.restore()

            return manage(run)

        @app.delete("/api/design/autosave", dependencies=write)
        def discard_autosave():
            return self.autosave.discard()

        @app.post("/api/design/path", dependencies=write, status_code=201)
        def create_path(body: dict):
            """Een vrij getekend pad: de pen."""
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
            """Tekst langs een boog; daarna een pad, geen tekst meer."""
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
            """De gedeelde catalogus, gefilterd op wat deze machine is."""
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
            """Een eigen preset in catalogusvorm, met een voorgevuld voorstel."""
            return manage(self.presetariat.as_contribution, preset_id)

        # ---------------------------------------------------------- testrasters

        def grid_fields(body: dict) -> dict:
            """
            Wat het bord aan het formulier toevoegt: machine, datum, materiaal.

            Voorbeeld en werkelijkheid gebruiken hier dezelfde regels. Dat moet
            ook: het opschrift bepaalt hoe breed het bord wordt, dus een
            voorbeeld zonder datum meldt een smaller bord dan er brandt.
            """
            from datetime import date

            velden = dict(body)
            # Een raster is een proef op déze machine; zonder dat gegeven zijn
            # de presets die eruit komen niet terug te plaatsen.
            if not velden.get("machine_id"):
                profiel = self._active_profile()
                if profiel:
                    velden["machine_id"] = profiel["id"]
            velden["stamp"] = date.today().isoformat()
            if velden.get("material_id"):
                materiaal = next(
                    (
                        m
                        for m in self.library.materials()
                        if m["id"] == velden["material_id"]
                    ),
                    None,
                )
                if materiaal:
                    velden["material_name"] = materiaal["name"]
            return velden

        @app.post("/api/library/testgrids/preview")
        def preview_test_grid(body: dict):
            """Work out the cells without drawing anything, so it can be shown first."""
            def run():
                plan, cells = plan_grid(**grid_fields(body))
                return {
                    "plan": plan,
                    "cells": cells,
                    # Wat déze engine met dit soort laag kan. Zonder rasteraar
                    # komt een rasterbord blanco uit de machine, en dat moet je
                    # weten vóór het hout eraan gaat — zie raster_supported.
                    "engine": {"raster": raster_supported(self.kernel)},
                }

            return manage(run)

        @app.post("/api/library/testgrids", dependencies=write, status_code=201)
        def create_test_grid(body: dict):
            """Plan the grid, draw it into the design, and remember it."""
            def run():
                # Het opschrift gaat mee de planning in: het staat links
                # uitgelijnd op het bord en loopt naar rechts door, dus het
                # bepaalt mede hoe breed het bord wordt. Achteraf toevoegen gaf
                # een gemelde maat die smaller was dan wat er brandt.
                plan, cells = plan_grid(**grid_fields(body))
                drawn = self.grids.draw(plan, cells)
                grid = self.library.add_test_grid(plan, drawn)
                # Het raster is één object op het canvas; de cellen houden hun
                # eigen operaties, want die zijn de sweep.
                group_id = self.grids.group_drawn(drawn)
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
            De instellingen van het vorige raster voor dit materiaal (T3).

            Geen aparte voorkeurentabel: het vorige raster ís de instelling.
            `null` als er nog geen raster voor dit materiaal is.
            """
            return self.library.last_grid_settings(material_id)

        # ---------------------------------------- benoemde recepten (gat T7)
        #
        # Vóór `/testgrids/{grid_id}`, anders vangt die route "recipes" op als
        # een id. Dat is FastAPI's volgorde van declareren, niet van specificiteit.

        @app.get("/api/library/testgrids/recipes")
        def list_grid_recipes(material_id: int | None = None):
            """
            Bewaarde generatorinstellingen onder een naam.

            T3 onthoudt het vorige raster per materiaal; dit is hetzelfde in het
            meervoud, zodat "berk snijden" en "berk graveren" naast elkaar
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
            Haal het raster van het canvas: de groep én al zijn cel-operaties.

            Het bewaarde raster blijft bestaan — daar hangen de foto en de
            herkomst van de presets aan.
            """
            def run():
                grid = self.library.test_grid(grid_id)
                removed = {"elements": 0, "operations": 0}
                # Alleen wat werkelijk van dit raster is. Id's gelden per
                # document, dus hetzelfde id staat op een ander vel voor iets
                # anders — zie de toelichting bij `is_cel_operatie`.
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
            Waar het bord op de foto ligt (T4).

            Stond in localStorage: uitlijnen op de desktop en het vakje aanwijzen
            op de tablet leverde dan twee verschillende overlays op.
            """
            return manage(
                self.library.set_grid_alignment, grid_id, body.get("corners")
            )

        @app.get("/api/library/testgrids/{grid_id}/photo")
        def get_grid_photo(grid_id: int, cell: str | None = None):
            """
            De foto van het gebrande bord.

            Met `?cell=<rij>-<kolom>` komt het aangewezen vakje omcirkeld mee
            (M4), volgens de uitlijning die bij dit raster bewaard is. Zonder
            die parameter is het onbewerkt het bestand van de gebruiker.
            """
            from fastapi.responses import FileResponse, Response

            grid = manage(self.library.test_grid, grid_id)
            path = grid.get("photo_path")
            if not path or not Path(path).is_file():
                raise HTTPException(status_code=404, detail="Nog geen foto.")
            if not cell:
                return FileResponse(path)
            try:
                row, column = (int(deel) for deel in str(cell).split("-", 1))
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="cell heeft de vorm <rij>-<kolom>."
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
                        "Dit raster hoort bij geen materiaal; koppel er eerst een aan."
                    )
                by_position = {(c["row"], c["column"]): c for c in grid["cells"]}
                created = []
                for pick in chosen:
                    key = (pick.get("row"), pick.get("column"))
                    cell = by_position.get(key)
                    if cell is None:
                        raise LibraryError(f"Cel {key} hoort niet bij dit raster.")
                    preset = self.library.add_preset(
                        material_id=grid["material_id"],
                        machine_id=grid["machine_id"],
                        thickness_mm=grid["thickness_mm"],
                        operation=grid["operation"],
                        speed_mm_s=cell["speed_mm_s"],
                        power_percent=cell["power_percent"],
                        # Bij een rasterproef hoort de lijnafstand bij de
                        # uitkomst; zonder haar is de preset niet na te branden.
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
        # Vóór `/machines/{path}`, anders leest die "import" als een pad.

        @app.post("/api/machines/import/upload", dependencies=write)
        async def upload_machine_profile(file: UploadFile):
            """Het profiel aannemen en zeggen wat het zou doen — nog niets meer."""
            from .machines import PROFILE_SUFFIX

            target = self._upload_path(file.filename or f"machine{PROFILE_SUFFIX}")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            preview = manage(self.machines.preview_profile, target)
            return {"profile": target.name, **preview}

        @app.post("/api/machines/import", dependencies=write, status_code=201)
        def import_machine_profile(body: dict):
            naam = Path(str(body.get("profile") or "")).name
            if not naam:
                raise HTTPException(status_code=422, detail="Kies eerst een bestand.")
            return manage(
                self.machines.import_profile,
                self._upload_path(naam),
                body.get("label"),
            )

        @app.get("/api/machines/{path}/export.openkerf-machine")
        def export_machine_profile(path: str):
            """
            Eén machine als bestand, in dezelfde vorm als de bibliotheek (B7).

            Gat E5: LightBurn levert `.lbdev`, zodat een fabrikant een profiel
            kan meesturen en een tweede computer niets overtypt.
            """
            from fastapi.responses import JSONResponse

            from .machines import PROFILE_SUFFIX

            profiel = manage(self.machines.export_profile, path)
            veilig = "".join(
                c if c.isalnum() or c in "-_" else "-"
                for c in str(profiel["machine"]["label"] or path)
            ).strip("-") or path
            return JSONResponse(
                profiel,
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
            return manage(self.machines.rename, path, label)

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
                # Wie ben ik, en sinds wanneer (gat E2). De WebSocket verbindt
                # vanzelf terug, maar de pagina die dan nog openstaat kan van
                # vóór een herstart zijn: de elementenboom is dan weg, het vel
                # is weg, en de app blijft vrolijk het ontwerp tonen dat er niet
                # meer is. Aan dit ene getal ziet de client het verschil tussen
                # een netwerkhik (zelfde proces, niets aan de hand) en een
                # herstart (alles opnieuw ophalen).
                await websocket.send_text(
                    json.dumps({"type": "hello", "instance": INSTANCE_ID})
                )
                await websocket.send_text(
                    json.dumps(
                        {"type": "snapshot", "data": self.reader.snapshot()},
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
                    {"type": "snapshot", "data": self.reader.snapshot()}
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
        # De camera sluiten zodra er niemand meer kijkt. Een leesthread die
        # uren doorloopt kost stroom en houdt het apparaat bezet voor andere
        # programma's; de rem zit in Camera.reap().
        self._camera_job = self.kernel.add_job(
            self.camera.reap, name="openkerf-camera-reap", interval=5.0
        )
        # De staart van het automatisch bewaren. `touch` hangt aan boomsignalen,
        # dus de laatste wijziging vóór je wegloopt kreeg nooit een schrijfbeurt:
        # er komt geen signaal meer om hem op te halen. Deze job doet dat wel, op
        # de kernelthread, dus zonder een tweede thread in de elementenboom.
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
        # Nog één keer, nu het nog kan: wat na de laatste schrijfbeurt getekend
        # is, mag niet met het proces verdwijnen.
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

    # Hoe lang we bij het afsluiten wachten tot de machine uitgepraat is. Lang
    # genoeg voor het staartje van een verzending, kort genoeg om niet in de
    # weg te lopen als er echt nog een job draait.
    QUIET_TIMEOUT_S = 2.0

    def _wait_for_the_machine_to_go_quiet(self):
        """
        De verzendthread van de driver zijn zin laten afmaken.

        Bij het afsluiten kwam dit in het log van de gebruiker:

            Exception in thread Thread-3 (_data_sender):
              ruida/controller.py:128 in _data_sender -> self.write(data)
              ruida/ruidasession.py:186 in write -> ConnectionError(
                  'Not connected to the Ruida controller.')

        Dat is een thread van MeerK40t zelf: `_data_sender` leegt zijn wachtrij
        zonder te controleren of de verbinding er nog is, dus zodra de sessie
        eronder wegvalt struikelt hij. Repareren hoort daar te gebeuren (zie de
        upstream-lijst in CLAUDE.md) — wij raken `meerk40t/` niet aan.

        Wat wij wél kunnen: niet de eersten zijn die de deur dichttrekken. Wij
        starten de device-service, dus wachten we hier even tot hij is
        uitgepraat voordat de rest van het afsluiten de verbinding weghaalt.
        Alles achter `getattr`: een dummy-device heeft geen van deze dingen, en
        het afsluiten mag hier nooit op stukgaan.
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
            # Boomwijzigingen zijn ook het sein om automatisch te bewaren; de
            # rem zit in Autosave, want slepen levert tientallen signalen op.
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
