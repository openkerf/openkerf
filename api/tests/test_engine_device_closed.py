"""
Can the engine's Ruida device stay closed while OpenKerf owns the connection?

We keep a MeerK40t Ruida device service for its settings, its bed and its RD encoding
(`CommandRunner.build_job_bytes`, the `rdjob` encoders). In the new design that service
must never open a session, a socket or a serial port towards the machine. Measured on
engine 5f68a45 with `deploy/patches/ruida-session.patch`, which OpenKerf shipped until
phase 6 of the own-connection plan, and checked again on 5f68a45 as released, which is
what the image installs now. Where the two differ, it says so.

**What opens, and when** (`test_today_activation_opens_a_session_that_outlives_the_device`)

- *Starting* the service (`service device start ruida`, no `-i`) builds `RuidaDevice` →
  `RuidaDriver` → `RuidaController`, and the controller's `__init__` starts the
  `_status_monitor` thread unconditionally (`ruida/controller.py:51-53`). No session, no
  transport: 0 sessions, 0 opens.
- *Activating* it — `-i`, `device add`, `activate_service_path`, or the engine's own boot
  (`device/basedevice.py:19-25`) — calls `service_attach` (`ruida/device.py:697-699`),
  which runs `.interface_update`: a `RuidaSession` (`device.py:409`), whose `__init__`
  starts the `_ruida_handshaker` thread (`ruida/ruidasession.py:67-68`), and `open()`
  (`device.py:414`) enables it. The worker then opens the configured transport by
  itself (`ruidasession.py:286-300`): with the default `usb`, 2 `USBTransport.open`
  attempts in the first second; with `udp`, 2 `UDPTransport.open` per second — each one
  binds `("", 40200)` (`ruida/udp_transport.py:40`) and sends an ENQ — retried every
  0.5 s after a failure (`ruidasession.py:330-332`) for as long as nobody answers.
- *Nothing closes it.* After switching the active device to the dummy the session is
  still the device's and its handshaker still runs (`RuidaDevice` has no
  `service_detach`); after `kernel()` shutdown too. With the patch it went on opening
  UDP, 2 per second; as released, a refused UDP open is not retried (the worker keeps
  writing into the closed transport, `ruidasession.py:256-272`) but the thread lives on.
- `ruida_connect` (`device.py:452-457`) calls `active_session.open()` again.
- An `interface` that is neither `usb` nor `udp` does not close it either. Measured
  during this investigation with `interface = "none"`: the session and its thread are
  created all the same, and the worker fails on "Unsupported interface"
  (`ruidasession.py:293-294`) every 0.5 s — generation 3 after 1.5 s — each time calling
  `recv(None)` and signalling "Disconnected".
- The engine as released does the same at activation: a session, a handshaker thread
  and USB open attempts within the first second. Its `shutdown()` busy-waits on
  `_is_shutdown` (`ruidasession.py:123-130`), which only the handshaker's last line sets:
  a worker that died on an exception leaves it spinning for ever. Measured once while
  investigating, switching such a device to `udp` with `interface_update` hung for more
  than 120 s. Hence `stop()` below, which never calls that `shutdown()`.

So the session must never be *created*; shutting it down after activation races a worker
that has already started opening, and a session left bound to 40200 would hold the very
port our own transport needs.

**The mechanism** (`test_a_closed_session_keeps_the_device_closed`)

`device.py` imports `RuidaSession` once (`device.py:20`) and constructs it in exactly one
place (`:409`). Replacing that module attribute with `ClosedSession` (`openkerf_api/ruida/closed.py`), *before* any
Ruida device activates, keeps everything shut: 0 real sessions, 0 transport opens, no
socket bound and no handshaker thread, also after `interface = "udp"` + `interface_update`,
`ruida_connect`, `ruida_disconnect`, `ruida_connect`. The live status monitor made 0
writes in 3.6 s (it only polls while `connected`, `controller.py:172`). A realtime
`pause` reached `ClosedSession.write` once, which raises `ConnectionError`, and
`RDJob.__call__` swallows exactly that (`ruida/rdjob.py:576-580`). The device's
`connected` and `is_busy` read `False`. The controller's own `is_busy` does not, as
released: its status monitor sets `_waiting` on the not-connected branch and nothing
clears it (`controller.py:186-189`; the patch cleared it). Nothing of ours reads it: the
API's shutdown no longer waits on the engine's controller (that wait only ever served the
engine's Ruida line), and a Ruida's busy state is our own session's.

**The bytes** (`test_build_job_bytes_and_the_encoders_are_unchanged`)

`build_job_bytes` never used the live session: it builds through its own `RuidaDriver`
(`commands.py`, `_upload_driver_for`) whose `write` is a no-op. On a 20×30 mm
rectangle in a cut layer: 440 bytes (433 before `ruida_speed`) ending `e5 05 … d7` (`SET_FILE_SUM`, `END_OF_FILE`),
byte-identical with and without the closed session; `move_abs_xy`, `home_xy` and
`pause_process` with `output=` are identical too (`88…`, `d8 2a`, `d8 02`).

**What stays.** One `_status_monitor` thread per `RuidaController` — the live driver's
and the build driver's — because `__init__` starts it and its loop has no way out
(`controller.py:176`). Neither does I/O here. The tests stop them with `halt()`.

The other side of "nothing closes it": run after `test_ruida_upload.py`, 76 handshaker
threads from earlier tests' devices were still alive in this process, together retrying
532 USB opens in one 3.6 s window. Hence `Opens.of(device)` below.
"""

import socket
import threading
import time

import pytest
import meerk40t.ruida.device as ruida_device_module
import meerk40t.ruida.ruidasession as ruidasession
import meerk40t.ruida.udp_transport as udp
import meerk40t.ruida.usb_transport as usb
from meerk40t.ruida.rdjob import END_OF_FILE, HOME_XY, MOVE_ABS_XY, SET_FILE_SUM
from meerk40t.ruida.ruidatransport import TransportError

from conftest import _bootstrap
from openkerf_api.commands import CommandRunner
# Proposed here first, and since phase 2 of the plan installed by our plugin at
# `register` for every kernel (`openkerf_api/ruida/closed.py`). The measurements of
# today's behaviour below therefore put the engine's own `RuidaSession` back after
# `_bootstrap()`, which is where the plugin installs the closed one.
from openkerf_api.ruida.closed import ClosedSession

#: These measurements construct the engine's own session on purpose (see `conftest.py`).
ENGINE_RUIDA_SESSION_ALLOWED = True


class _Halt:
    """Ends a `_status_monitor` loop at its next look at `service.connected`."""

    def __getattr__(self, name):
        raise SystemExit


def halt(*controllers):
    """
    Stop the status-monitor threads of these controllers and wait for them.

    `RuidaController.__init__` starts that thread unconditionally and its loop has no
    way out (`ruida/controller.py:51-53,176`), so without this every test here would
    leave one behind per controller. `SystemExit` from `service.connected` ends it; the
    excepthook is told to let exactly those threads go quietly.
    """
    controllers = [c for c in controllers if c is not None]
    threads = {c._status_thread for c in controllers}
    previous = threading.excepthook

    def quiet(args):
        if args.thread in threads and args.exc_type is SystemExit:
            return
        previous(args)

    threading.excepthook = quiet
    try:
        for controller in controllers:
            controller.service = _Halt()
        for thread in threads:
            # Up to the 3 s start-up sleep (`controller.py:175`) plus one poll.
            thread.join(4)
            assert not thread.is_alive()
    finally:
        threading.excepthook = previous


def stop(session):
    """
    End a real engine session's handshaker, bounded, on either engine.

    The patched session's `shutdown()` is a bounded join. The released one's is
    `while not self._is_shutdown: continue` (`ruidasession.py:123-130`), and only the
    handshaker's last line sets that flag — so it is not called here: the flag the loops
    watch is set, the thread joined with a limit, the transport closed.
    """
    thread = session._handshake_thread
    if hasattr(session, "_state"):  # the patched session
        session.shutdown()
    else:
        session._shutdown = True
        if thread is not None:
            thread.join(3)
        session.close()
    assert thread is None or not thread.is_alive()


@pytest.fixture(autouse=True)
def no_threads_left_behind():
    before = set(threading.enumerate())
    yield
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        extra = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        if not extra:
            return
        time.sleep(0.02)
    pytest.fail(f"threads left behind: {extra}")


class Opens:
    """
    Every transport open, real `RuidaSession` and socket `bind` in the process, with the
    service and thread it came from, so a test can count only its own device's.

    That filter is not tidiness. Run after `test_ruida_upload.py`, 76 handshaker threads
    left by earlier tests were still alive and retrying their USB open — 532 opens in
    one 3.6 s window — because nothing ever closes an activated device's session (see
    the module docstring). Counting the whole process would measure them, not us.

    `refuse=True` makes every open fail before a socket or serial port exists — for the
    measurement of today's behaviour, which would otherwise bind 40200 and send ENQs.
    `refuse=False` lets an open through, so the closed design is checked against the
    real thing: if it ever let a transport open, the bind would be recorded.
    """

    def __init__(self, monkeypatch, refuse):
        self.calls = []
        self.binds = []
        self.started = set(threading.enumerate())

        def wrap(kind, real):
            def open_(transport):
                self.calls.append((kind, transport.service))
                if refuse:
                    raise TransportError(f"{kind} refused by the test")
                return real(transport)

            return open_

        monkeypatch.setattr(udp.UDPTransport, "open", wrap("udp", udp.UDPTransport.open))
        monkeypatch.setattr(usb.USBTransport, "open", wrap("usb", usb.USBTransport.open))
        real_init = ruidasession.RuidaSession.__init__

        def counted(session, service):
            self.calls.append(("session", service))
            real_init(session, service)

        monkeypatch.setattr(ruidasession.RuidaSession, "__init__", counted)
        real_bind = socket.socket.bind

        def bind(sock, address):
            self.binds.append((threading.current_thread(), address))
            return real_bind(sock, address)

        monkeypatch.setattr(socket.socket, "bind", bind)

    def of(self, device):
        counts = {"udp": 0, "usb": 0, "session": 0}
        for kind, service in self.calls:
            if service is device:
                counts[kind] += 1
        return counts

    def binds_from_new_threads(self):
        return [b for b in self.binds if b[0] not in self.started]

    def new(self, fragment):
        return [t for t in threading.enumerate()
                if t not in self.started and fragment in t.name and t.is_alive()]


def ruida_device(kernel):
    return next(d for d in kernel.services("device") if d.path.startswith("ruida"))


def a_rectangle(kernel):
    """The rectangle of `test_ruida_upload.a_rectangle`: 20×30 mm, one cut layer."""
    kernel.elements.clear_all()
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def encoded(device):
    job = device.driver.controller.job
    out = []
    job.move_abs_xy(10_000, 20_000, output=out.append)
    job.home_xy(output=out.append)
    job.pause_process(output=out.append)
    return out


def test_today_activation_opens_a_session_that_outlives_the_device(monkeypatch):
    """The problem, measured with every open refused before it reaches a socket:
    nothing at service start, a session and a worker at activation that opens the
    transport, and that worker still running after a device switch and a kernel
    shutdown."""
    opens = Opens(monkeypatch, refuse=True)
    kernel = _bootstrap()
    monkeypatch.setattr(ruida_device_module, "RuidaSession", ruidasession.RuidaSession)
    device = session = None
    try:
        kernel.console("service device start ruida\n")
        device = ruida_device(kernel)
        assert device.active_session is None
        assert opens.of(device) == {"udp": 0, "usb": 0, "session": 0}
        assert device.driver.controller._status_thread.is_alive()
        assert opens.new("_ruida_handshaker") == []

        kernel.activate_service_path("device", device.path)
        session = device.active_session
        assert type(session) is ruidasession.RuidaSession
        assert opens.of(device)["session"] == 1
        assert opens.new("_ruida_handshaker")
        time.sleep(1.0)
        assert opens.of(device)["usb"] >= 1  # 2 measured

        # Away from USB before the switch: the released `shutdown()` that
        # `interface_update` calls (`device.py:405`) waits for the handshaker, which
        # ends within its 1 s retry sleep while every open is refused.
        device.address = "127.0.0.1"
        device.interface = "udp"
        kernel.console(".interface_update\n")
        session = device.active_session
        time.sleep(1.0)
        assert opens.of(device)["udp"] >= 1  # 2 measured with the patch, 1 without

        kernel.console("device activate 0\n")
        assert kernel.device is not device
        time.sleep(1.0)
        assert device.active_session is session
        assert session._handshake_thread.is_alive()
    finally:
        kernel()
        if session is not None:
            time.sleep(0.5)
            assert session._handshake_thread.is_alive()  # after kernel shutdown too
            stop(session)
        if device is not None:
            halt(device.driver.controller)


def test_a_closed_session_keeps_the_device_closed(monkeypatch):
    """`RuidaSession` replaced in `meerk40t.ruida.device` before the device activates:
    no session, no worker, no open, no socket, and no write from the status monitor in
    3.6 s — past its 3 s start-up sleep — whatever the console asks for."""
    monkeypatch.setattr(ruida_device_module, "RuidaSession", ClosedSession)
    opens = Opens(monkeypatch, refuse=False)
    kernel = _bootstrap()
    device = None
    try:
        started = time.monotonic()
        kernel.console("service device start ruida -i\n")
        device = kernel.device
        assert type(device.active_session) is ClosedSession

        device.address = "127.0.0.1"
        device.interface = "udp"
        for line in ("interface_update", "ruida_connect", "ruida_disconnect", "ruida_connect"):
            kernel.console(f".{line}\n")
        session = device.active_session
        assert type(session) is ClosedSession and session.interface == "udp"

        writes = session.writes
        kernel.console("pause\n")
        assert session.writes == writes + 1  # refused, and swallowed by RDJob

        writes = session.writes
        time.sleep(max(0.0, 3.6 - (time.monotonic() - started)))
        assert session.writes == writes

        assert opens.of(device) == {"udp": 0, "usb": 0, "session": 0}
        assert opens.binds_from_new_threads() == []
        assert opens.new("_ruida_handshaker") == []
        assert (device.connected, device.is_busy) == (False, False)
    finally:
        kernel()
        if device is not None:
            halt(device.driver.controller)


def test_build_job_bytes_and_the_encoders_are_unchanged(monkeypatch):
    """The same rectangle built twice, first with today's session and then with the
    closed one: 440 bytes both times, byte for byte equal, and so are the encoders.
    (433 before the first-layer speed repair in `ruida_speed`, which adds the layer's own
    `Speed Laser 1` after the first jump: 7 bytes.)
    With the session closed the build opens nothing and starts no session."""
    opens = Opens(monkeypatch, refuse=False)
    results = {}
    for label in ("today", "closed"):
        if label == "closed":
            monkeypatch.setattr(ruida_device_module, "RuidaSession", ClosedSession)
        kernel = _bootstrap()
        if label == "today":
            monkeypatch.setattr(
                ruida_device_module, "RuidaSession", ruidasession.RuidaSession)
        device = runner = None
        try:
            kernel.console("service device start ruida -i\n")
            device = kernel.device
            if label == "today":
                handshakers_today = opens.new("_ruida_handshaker")
            a_rectangle(kernel)
            runner = CommandRunner(kernel)
            results[label] = (runner.build_job_bytes(), encoded(device))
            if label == "closed":
                assert opens.of(device) == {"udp": 0, "usb": 0, "session": 0}
                assert opens.binds_from_new_threads() == []
                assert [t for t in opens.new("_ruida_handshaker")
                        if t not in handshakers_today] == []
                # `stop_record` starts a `_data_sender` per build (`driver.py:301`); it
                # writes into the build driver's no-op and ends.
                deadline = time.monotonic() + 1
                while opens.new("_data_sender"):
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
        finally:
            session = getattr(device, "active_session", None)
            kernel()
            if isinstance(session, ruidasession.RuidaSession):
                stop(session)
            build = runner._upload_driver if runner is not None else None
            halt(device.driver.controller if device is not None else None,
                 build.controller if build is not None else None)

    data, commands = results["closed"]
    assert len(data) == 440
    assert data.endswith(END_OF_FILE) and SET_FILE_SUM in data
    assert data == results["today"][0]
    assert commands == results["today"][1]
    assert commands[0].startswith(MOVE_ABS_XY) and commands[1] == HOME_XY
