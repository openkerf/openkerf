"""Hardware-free disposable API for UI checks; never loads driver plugins."""
import argparse
import signal
import tempfile
import time
from pathlib import Path

from meerk40t.kernel import Kernel
from openkerf_api.server import ApiServer
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse


def bootstrap(root, frontend=None):
    root = Path(root).resolve()
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and not root.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("Scratch storage must be in the temporary directory")
    root.mkdir(parents=True, exist_ok=True)
    # An absolute kernel name keeps ALL engine Settings and WORKDIR under root.
    kernel = Kernel(str(root), "gauntlet", "scratch", ansi=False, ignore_settings=True)
    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import cag, hershey, param_functions, vectrace
    from meerk40t.fill import fills
    from meerk40t.image import imagetools
    for module in (basedevice, dummydevice, core, imagetools, vectrace, param_functions, fills, cag, hershey, svg_io):
        kernel.add_plugin(module.plugin)
    kernel(partial=True)
    from openkerf_api.rasterizer import register
    register(kernel)
    kernel.console("service device start dummy 0\n")
    kernel.device.label = "Desktop review (simulated)"
    kernel.device.bedwidth, kernel.device.bedheight = "500mm", "300mm"
    kernel.device.realize()
    server = ApiServer(kernel, port=8092, bind="127.0.0.1", frontend=frontend,
                       library_path=root / "library.db", operations_path=root / "operations.cfg",
                       projects=root / "projects")
    # Let the normal library profile flow recognize this isolated dummy device.
    server.machines._mark_configured(kernel.device)
    marker = {"marker": "openkerf-gauntlet-v1", "isolated": True, "hardware": False,
              "paths": {"kernel": str(kernel._config_file), "operations": str(root / "operations.cfg"),
                        "library": str(root / "library.db"), "projects": str(root / "projects"),
                        "workdir": kernel.os_information["WORKDIR"]}}
    state = {"connection": "disconnected", "phase": "idle", "z_step": False}
    # Only the disposable drawing planner sees this simulated capability.
    server.drawing.z_step_supported = lambda: state["z_step"]
    marker["state"] = state
    read_status = server._status_payload

    def visual_status():
        payload = read_status()
        for device in payload["devices"]:
            if not device["active"]:
                continue
            phase = state["phase"]
            device["connection"] = {"state": state["connection"], "detail": "Simulated gauntlet state"}
            device["laser_status"] = "busy" if phase == "running" else "idle"
            device["paused"] = phase == "paused"
            jobs = [] if phase == "idle" else [{
                "label": "Desktop review job", "type": "LaserJob", "priority": 0,
                "status": "Queued" if phase == "queued" else "Running" if phase == "running" else "Waiting",
                "running": phase in ("running", "paused"), "paused": phase == "paused",
                "steps_done": 100 if phase == "done" else 42, "steps_total": 100,
                "progress": 1 if phase == "done" else .42, "loops_executed": 0, "loops": 1,
                "elapsed_seconds": 0 if phase == "queued" else 42, "estimate_seconds": 100,
            }]
            device["spooler"] = {"present": True, "idle": not jobs, "queue_length": len(jobs), "jobs": jobs}
        return payload

    server._status_payload = visual_status

    def set_state(body: dict = Body(...)):
        if set(body) - state.keys() or body.get("connection", state["connection"]) not in ("connected", "disconnected", "unknown") or body.get("phase", state["phase"]) not in ("idle", "queued", "running", "paused", "done") or type(body.get("z_step", state["z_step"])) is not bool:
            raise HTTPException(422, "Unknown visual fixture state")
        state.update(body)
        return state

    async def alarm(body: dict = Body(...)):
        messages = {
            "usb_missing": "Simulated fixture: USB connection did not exist",
            "usb_recovered": "Simulated fixture: USB connected",
        }
        kind = body.get("kind")
        if set(body) != {"kind"} or kind not in messages:
            raise HTTPException(422, "Unknown alarm fixture")
        event = {"type": "signal", "code": "pipe;usb_status", "origin": "gauntlet",
                 "args": [messages[kind]], "time": time.time()}
        # Deliberately bypass the kernel: this is a UI event, never a driver signal.
        await server.bridge.broadcast(event)
        return event

    def capabilities():
        return {"actions": dict.fromkeys(("start", "pause", "resume", "stop", "clear_queue", "load", "upload"), True),
                "motion": dict.fromkeys(("home", "physical_home", "unlock", "lock", "move", "jog", "focus"), True),
                "adjust": {"power": False, "speed": False},
                "connection": {"connect": True, "disconnect": True}, "auth_required": False}

    original = server.build_app
    def build_app():
        app = original()
        # Prepend: the frontend catch-all must not hide this scratch-only endpoint.
        from fastapi.routing import APIRoute
        app.router.routes.insert(0, APIRoute("/api/gauntlet", lambda: marker, methods=["GET"]))
        app.router.routes.insert(0, APIRoute("/api/gauntlet/state", set_state, methods=["POST"]))
        app.router.routes.insert(0, APIRoute("/api/gauntlet/alarm", alarm, methods=["POST"]))
        app.router.routes.insert(0, APIRoute("/api/capabilities", capabilities, methods=["GET"]))

        @app.middleware("http")
        async def refuse_execution(request: Request, call_next):
            path = request.url.path
            # Capabilities describe visual fixtures, never permission to execute them.
            if request.method != "GET" and (
                (path.startswith("/api/job/") and path != "/api/job/load")
                or path.startswith("/api/machine/")
                or path in ("/api/tiling/start", "/api/tiling/burn", "/api/series/start", "/api/series/burn", "/api/series/redo")
            ):
                return JSONResponse({"detail": "Hardware commands are disabled in the visual gauntlet."}, status_code=409)
            return await call_next(request)
        return app
    server.build_app = build_app
    return kernel, server, marker


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", default=str(Path(__file__).resolve().parents[1] / "build"))
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="openkerf-gauntlet-", dir="/tmp"))
    kernel, server, marker = bootstrap(root, args.frontend)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        server.start()
        print(f"Scratch UI: http://127.0.0.1:8092 | storage: {root}", flush=True)
        while server._thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            server.stop()
        finally:
            kernel()
