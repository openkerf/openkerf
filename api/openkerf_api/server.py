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
from .edits import DesignEditor, DesignError
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

    def __init__(self, kernel, port=8080, bind="127.0.0.1", frontend=None, token=None):
        self.kernel = kernel
        self.port = port
        self.bind = bind
        self.frontend = Path(frontend).expanduser() if frontend else None
        self.reader = StatusReader(kernel)
        self.commands = CommandRunner(kernel)
        self.machines = MachineManager(kernel, self.commands)
        self.design = DesignReader(kernel)
        self.editor = DesignEditor(kernel, self.commands)
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
            except (MachineError, DesignError) as e:
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
            return self.design.snapshot()

        @app.get("/api/capabilities")
        def capabilities():
            """
            Which control actions the *active* device supports. pause/resume/
            estop are registered by the Ruida service, not by the kernel, so
            this changes when the user switches device.
            """
            return {
                "actions": self.commands.capabilities(),
                "auth_required": not self.local_only,
            }

        # ---------------------------------------------------------- write API

        @app.post("/api/job/load", dependencies=write)
        async def load_job(file: UploadFile):
            """Upload a design and load it into the element tree."""
            target = self._upload_path(file.filename or "upload.svg")
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            return act(self.commands.load_file, str(target))

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

        # ------------------------------------------------------- design edits

        @app.post("/api/design/elements/{element_id}/move", dependencies=write)
        def move_element(element_id: str, body: dict):
            return manage(
                self.editor.move, element_id, body.get("dx_mm"), body.get("dy_mm")
            )

        @app.post("/api/design/elements/{element_id}/resize", dependencies=write)
        def resize_element(element_id: str, body: dict):
            return manage(
                self.editor.resize,
                element_id,
                body.get("x_mm"),
                body.get("y_mm"),
                body.get("width_mm"),
                body.get("height_mm"),
            )

        @app.post("/api/design/undo", dependencies=write)
        def undo_design():
            return manage(self.editor.undo)

        @app.post("/api/design/redo", dependencies=write)
        def redo_design():
            return manage(self.editor.redo)

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
