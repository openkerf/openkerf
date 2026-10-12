"""Hardware-free disposable API for UI checks.

Default: the dummy driver only, with simulated status. `--ruida-emulator`: a Ruida
device (path `ruida`) on OpenKerf's own line to the engine's emulator on 127.0.0.1
(`api/tests/ruida_peer.py`), so the interface's real Ruida code paths can be seen.
Either way nothing leaves this computer.
"""
import argparse
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from meerk40t.kernel import Kernel
from openkerf_api.server import ApiServer
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse


#: The status words a KH-5030 gave on 11 October (CLAUDE.md, "Pending hardware
#: validation"); "moving" has no `peer.state` of its own in the emulator.
KH5030_MOVING_WORD = 16975360

#: `second_client`: 2 of every 5 status answers lost, the ~40 % measured with a second
#: program on the controller (CLAUDE.md, "One program per Ruida controller").
SECOND_CLIENT_PATTERN = (True, False, True, False, False)


def start_ruida_peer():
    """The emulator peer on 127.0.0.1 at a free port; the API's Ruida links go there."""
    tests = str(Path(__file__).resolve().parents[2] / "api" / "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    from ruida_peer import RuidaPeer

    peer = RuidaPeer(host="127.0.0.1", send_port=0).start()
    # Read by `Links._make` for every Ruida link this process makes.
    os.environ["OPENKERF_RUIDA_SEND_PORT"] = str(peer.send_port)
    os.environ["OPENKERF_RUIDA_LISTEN_PORT"] = "0"
    return peer


def bootstrap(root, frontend=None, ruida_emulator=False):
    """The kernel, the server and the marker. With `ruida_emulator` the server carries
    the running peer as `server.gauntlet_peer`; whoever bootstraps closes it."""
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
    modules = [basedevice, dummydevice, core, imagetools, vectrace, param_functions, fills, cag, hershey, svg_io]
    peer = None
    if ruida_emulator:
        # Before any Ruida device exists: the engine's own session must never be made
        # (`ruida/closed.py`), exactly as our plugin does at `register`.
        from openkerf_api.ruida.closed import install as keep_the_engine_ruida_closed
        from openkerf_api.ruida_speed import install as repair_ruida_speed
        keep_the_engine_ruida_closed()
        repair_ruida_speed()
        from meerk40t.extra import coolant
        from meerk40t.ruida import plugin as ruida_plugin
        # coolant before the driver: the Ruida service claims a coolant channel at init.
        modules += [coolant, ruida_plugin]
        peer = start_ruida_peer()
    for module in modules:
        kernel.add_plugin(module.plugin)
    kernel(partial=True)
    from openkerf_api.rasterizer import register
    register(kernel)
    if ruida_emulator:
        kernel.console("service device start -i ruida\n")
        if getattr(kernel.device, "path", None) != "ruida":
            peer.close()
            raise RuntimeError("The scratch Ruida did not become the active machine at path 'ruida'")
        kernel.device.label = "KH-5030 (emulated)"
        kernel.device.address = "127.0.0.1"
    else:
        kernel.console("service device start dummy 0\n")
        kernel.device.label = "Desktop review (simulated)"
    kernel.device.bedwidth, kernel.device.bedheight = "500mm", "300mm"
    kernel.device.realize()
    server = ApiServer(kernel, port=8092, bind="127.0.0.1", frontend=frontend,
                       library_path=root / "library.db", operations_path=root / "operations.cfg",
                       projects=root / "projects")
    server.gauntlet_peer = peer
    # Let the normal library profile flow recognize this isolated device.
    server.machines._mark_configured(kernel.device)
    # Searching the network sends a Ruida probe to every address on the subnet, a real
    # controller included. The scratch server looks at USB and serial only.
    from openkerf_api.machines import MachineScanner
    def scan(network=True, seconds=2.0):
        found = MachineScanner(server.machines.catalog()).scan(network=False, seconds=seconds)
        if network:
            found["notes"].append("Network not searched: the scratch server never probes the local network.")
        return found
    server.machines.scan = scan
    marker = {"marker": "openkerf-gauntlet-v1", "isolated": True, "hardware": False,
              "paths": {"kernel": str(kernel._config_file), "operations": str(root / "operations.cfg"),
                        "library": str(root / "library.db"), "projects": str(root / "projects"),
                        "workdir": kernel.os_information["WORKDIR"]}}
    if ruida_emulator:
        marker["emulator"] = {"ruida": f"127.0.0.1:{peer.send_port}"}
        state = {"connection": "connected", "phase": "idle", "second_client": False, "z_step": False}
    else:
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

    if not ruida_emulator:
        server._status_payload = visual_status

    def until(predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    def drive_emulator(body):
        """
        Put the emulator where `body` says and wait until our own line reads it back:
        the connection first, then the machine's phase, then the second-client warning,
        so a script that photographs next sees the state it asked for. `settled` says
        whether every wait ended in time.
        """
        link = server.links.for_device(kernel.device)
        reading = link.connection
        settled = True
        connection = body.get("connection")
        if connection == "connected":
            peer.silent = False
            if reading()["state"] == "disconnected":
                link.connect()
        elif connection == "connecting":
            # A line that was up and then hears nothing: the session probes on its own.
            if reading()["state"] == "disconnected":
                peer.silent = False
                link.connect()
            peer.silent = True
        elif connection == "disconnected":
            # Connecting to a controller that does not answer: the link lets it go after
            # its bounded wait, with its own sentence naming the silent address.
            peer.silent = True
            link.disconnect()
            link.connect()
        if connection is not None:
            settled = until(lambda: reading()["state"] == connection, 15)
        connected = reading()["state"] == "connected"
        if "phase" in body:
            from meerk40t.ruida.rdjob import MEM_MACHINE_STATUS
            phase = body["phase"]
            peer.state = {"idle": "idle", "moving": "idle", "running": "busy", "paused": "hold"}[phase]
            if phase == "moving":
                peer.memory[MEM_MACHINE_STATUS] = KH5030_MOVING_WORD
            else:
                peer.memory.pop(MEM_MACHINE_STATUS, None)
            if connected:
                settled = until(lambda: link.machine_state() == phase, 15) and settled
        if "second_client" in body:
            peer.swallow_replies(SECOND_CLIENT_PATTERN if body["second_client"] else ())
            if connected:
                # Raising needs 5 of the last 20 reads lost, clearing 1 or fewer; each
                # lost read waits out the session's reply time: seconds, not a moment.
                warned = lambda: (reading().get("warning") is not None) == body["second_client"]
                settled = until(warned, 30) and settled
        return {**state, "settled": settled, "reading": reading(), "machine_state": link.machine_state()}

    def set_state(body: dict = Body(...)):
        if ruida_emulator:
            if (set(body) - state.keys()
                    or body.get("connection", state["connection"]) not in ("connected", "connecting", "disconnected")
                    or body.get("phase", state["phase"]) not in ("idle", "moving", "running", "paused")
                    or any(type(body.get(k, state[k])) is not bool for k in ("z_step", "second_client"))):
                raise HTTPException(422, "Unknown emulator fixture state")
            state.update(body)
            return drive_emulator(body)
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
        if not ruida_emulator:
            # With the emulator the real capabilities of the Ruida link answer.
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
    parser.add_argument("--ruida-emulator", action="store_true",
                        help="a Ruida at path 'ruida' on the emulator on 127.0.0.1 instead of the dummy")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="openkerf-gauntlet-", dir="/tmp"))
    kernel, server, marker = bootstrap(root, args.frontend, ruida_emulator=args.ruida_emulator)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        server.start()
        emulated = f" | Ruida emulator: {marker['emulator']['ruida']}" if args.ruida_emulator else ""
        print(f"Scratch UI: http://127.0.0.1:8092 | storage: {root}{emulated}", flush=True)
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
            try:
                kernel()
            finally:
                if server.gauntlet_peer is not None:
                    server.gauntlet_peer.close()
