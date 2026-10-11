"""
Keeping the engine's Ruida device away from the machine.

We keep MeerK40t's Ruida device service for its settings, its bed and its RD encoding;
the line to the controller is ours (`ruida/link.py`). The engine must therefore never open
a session of its own. Measured in `test_engine_device_closed.py`: *activating* a Ruida
device constructs `meerk40t.ruida.device.RuidaSession` (`ruida/device.py:409`), whose
worker binds UDP 40200 every 0.5 s for as long as nobody answers, and nothing closes it
again — not a device switch, not a kernel shutdown. Shutting it down afterwards races a
worker that has already started opening, and a session bound to 40200 holds the very
port our own transport needs.

So the session is never *created*: `install()` replaces that one module attribute with
`ClosedSession` before any device activates, from our plugin's `register` lifecycle.
`device.py` imports the name once (`:20`) and constructs it in exactly one place
(`:409`), which is what makes one attribute enough.
"""

from __future__ import annotations


class ClosedSession:
    """
    The stand-in for `RuidaSession` on the engine's Ruida device. It opens nothing.

    It carries what the device, the controller and our own layer read off
    `active_session` — `interface` (compared by `interface_update`, `device.py:401`),
    `connected`, `is_connecting`, `is_busy`, `set_timeout`, `location` — and every verb
    the device calls on it is a no-op. `write` raises `ConnectionError` rather than
    returning quietly, as the engine's own session does when it is not connected
    (`ruidasession.py:182-186`): bytes that reach it went nowhere, and nothing may
    pretend otherwise. `RDJob.__call__` drops exactly that exception (`rdjob.py:579`),
    so a realtime verb on the engine's console is a quiet no-op. The controller's
    `_data_sender` does not catch it (`controller.py:125-132`): a job spooled to the
    engine's Ruida driver ends its send thread on it, having sent nothing. No route of
    ours spools to a Ruida — its jobs go down our own line (`CommandRunner`,
    `carries_jobs`).
    """

    connected = False
    is_connecting = False
    is_busy = False
    is_open = False
    generation = 0
    transport = None

    def __init__(self, service):
        self.interface = getattr(service, "interface", None)
        self.writes = 0

    def set_swizzles(self, swizzle, unswizzle):
        pass

    def open(self):
        pass

    def connect(self):
        pass

    def close(self):
        pass

    def abort_connect(self):
        pass

    def shutdown(self, *args, **kwargs):
        pass

    def update_connect_status(self):
        pass

    def set_timeout(self, seconds):
        pass

    def location(self):
        return "closed"

    def write(self, data):
        self.writes += 1
        raise ConnectionError("The engine's Ruida device does not talk to the machine.")


def install() -> bool:
    """
    Put `ClosedSession` where the engine's Ruida device looks for its session class.

    Returns whether this call changed anything: `False` when it was already in place, so
    a second plugin registration (tests build many kernels in one process) is harmless.

    No Ruida module in the engine means no Ruida device can exist, and then there is
    nothing to keep closed. A Ruida module *without* the attribute is different: the
    engine has changed under us, and quietly carrying on would let a device open the
    line we own. That raises, so it is found the first time anybody starts the app.
    """
    try:
        import meerk40t.ruida.device as device_module
    except ImportError:
        return False
    if not hasattr(device_module, "RuidaSession"):
        raise RuntimeError(
            "meerk40t.ruida.device no longer has RuidaSession, so OpenKerf cannot keep "
            "the engine's Ruida device closed. See openkerf_api/ruida/closed.py."
        )
    if device_module.RuidaSession is ClosedSession:
        return False
    device_module.RuidaSession = ClosedSession
    return True


def installed() -> bool:
    """Whether the engine's Ruida device is kept closed in this process."""
    try:
        import meerk40t.ruida.device as device_module
    except ImportError:
        return False
    return getattr(device_module, "RuidaSession", None) is ClosedSession
