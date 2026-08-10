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
from pathlib import Path

from .auth import extract_token, generate_token, is_loopback, token_matches
from .commands import CommandError, CommandRunner
from .design import DesignReader
from .document import Document
from .drawing import Drawing
from .edits import DesignEditor, DesignError
from .images import Images
from .library import Library, LibraryError, default_path
from .generators import Generators
from .nodes import Nodes
from .presetariat import Presetariat
from .testgrid import TestGridGenerator, plan_grid
from .machine import MachineControl
from .machines import MachineError, MachineManager
from .status import StatusReader

# Kernel signals worth forwarding to connected clients. Every one of these is
# emitted by the engine itself; we only listen.
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
    """
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
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
        self.generators = Generators(kernel, self.commands)
        self.design = DesignReader(
            kernel,
            keep_operations=self.drawing.user_operations,
            grid_operations=lambda: self.library.grid_operations(),
        )
        self.drawing.grid_operations = lambda: self.library.grid_operations()
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
            return act(self.commands.start_job)

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

            path = manage(self.drawing.export_project, self.library, filename)
            self.document.clean()
            return FileResponse(
                path, media_type="application/zip", filename=path.name
            )

        @app.post("/api/project/open", dependencies=write)
        async def open_project(file: UploadFile):
            target = self._upload_path(file.filename or "project.openkerf")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            result = manage(self.drawing.import_project, str(target), self.library)
            self.document.clean()
            return result

        @app.get("/api/design/elements/{element_id}/image.png")
        def element_image(element_id: str):
            """De pixels van een afbeelding, zodat het canvas hem kan tonen."""
            from fastapi.responses import FileResponse

            path = manage(self.images.render_png, element_id)
            return FileResponse(path, media_type="image/png")

        @app.post("/api/design/elements/{element_id}/image", dependencies=write)
        def adjust_image(element_id: str, body: dict):
            if body.get("dpi") is not None:
                return manage(self.images.set_dpi, element_id, body["dpi"])
            if body.get("factor") is not None:
                return manage(
                    self.images.enhance,
                    element_id,
                    body.get("adjustment"),
                    body["factor"],
                )
            return manage(self.images.adjust, element_id, body.get("adjustment"))

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
        def list_fonts():
            return manage(self.drawing.fonts)

        @app.get("/api/job/estimate")
        def estimate_job():
            """Geschatte brandtijd van het huidige ontwerp, vóór starten."""
            return manage(self.drawing.estimate)

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
            return manage(lambda: self.drawing.update_operation(operation_id, **body))

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
            return manage(self.editor.rotate, body.get("ids"), body.get("angle_deg"))

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
        def list_presets(material_id: int | None = None, operation: str | None = None):
            return self.library.presets(material_id, operation)

        @app.post("/api/library/presets", dependencies=write, status_code=201)
        def add_preset(body: dict):
            return manage(lambda: self.library.add_preset(**body))

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
                return {**result, "preset": preset}

            return manage(run)

        # ----------------------------------------------------------- generatoren

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

        @app.post("/api/library/testgrids/preview")
        def preview_test_grid(body: dict):
            """Work out the cells without drawing anything, so it can be shown first."""
            def run():
                plan, cells = plan_grid(**body)
                return {"plan": plan, "cells": cells}

            return manage(run)

        @app.post("/api/library/testgrids", dependencies=write, status_code=201)
        def create_test_grid(body: dict):
            """Plan the grid, draw it into the design, and remember it."""
            def run():
                plan, cells = plan_grid(**body)
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
                if grid.get("group_id"):
                    node = self.kernel.elements.find_node(grid["group_id"])
                    if node is not None:
                        removed["elements"] = len(list(node.flat())) - 1
                        node.remove_node(children=True, destroy=True)
                for cell in grid["cells"]:
                    for key in ("element_id", "operation_id"):
                        node = self.kernel.elements.find_node(cell.get(key) or "")
                        if node is not None:
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

        @app.get("/api/library/testgrids/{grid_id}/photo")
        def get_grid_photo(grid_id: int):
            from fastapi.responses import FileResponse

            grid = manage(self.library.test_grid, grid_id)
            path = grid.get("photo_path")
            if not path or not Path(path).is_file():
                raise HTTPException(status_code=404, detail="Nog geen foto.")
            return FileResponse(path)

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

        @app.post("/api/machines", dependencies=write, status_code=201)
        def machine_create(body: dict):
            info = body.get("info")
            if not info:
                raise HTTPException(status_code=422, detail="'info' ontbreekt.")
            return manage(self.machines.create, info, body.get("label"))

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
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._server = None
        if self._upload_dir is not None:
            shutil.rmtree(self._upload_dir, ignore_errors=True)
            self._upload_dir = None
        self.channel("OpenKerf API stopped.")

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
