"""
The line to a Ruida as a `MachineLink`: our session and monitor, the engine's settings.

The engine's Ruida device keeps the address and the swizzle magic (`device.address`,
`device.magic`; `ruida/device.py:270-280,355`), so the user sets them where they always
have; this class reads them at every `connect()` and builds the line from
`ruida/transport.py`, `ruida/session.py` and `ruida/monitor.py`. The engine's own
Ruida session is not opened by anything in here.

- **Nothing happens in the constructor.** No socket, no thread: a link can be made for
  every Ruida device at startup and cost nothing until somebody connects.
- **`connect()` is bounded.** It waits `reply_seconds × 3` for the first answer. A
  controller that has not answered by then is let go — the session is closed, the
  state is "disconnected" and the detail says which address stayed silent — instead
  of a line that goes on probing nobody behind the user's back.
- **Once connected, a silence is ridden out.** The session goes to "connecting" and
  probes again on its own; the monitor goes on reading as soon as it is back. Measured
  in `test_a_five_second_silence_ends_connected_without_asking`.
- **`disconnect()` stays disconnected** until `connect()`: the session's own rule,
  and the monitor stops too, so not one packet leaves.
- **A host name is refused** before anything is opened, with the transport's own
  sentence, because the engine's resolver on the shutdown path is what the session
  patch had to work around (`ruida/transport.py`).
"""

import threading
import time

from . import framing
from .monitor import Monitor, machine_state
from .session import RuidaSession
from .transport import LISTEN_PORT, SEND_PORT, UdpTransport

#: Before the first `connect()`, and after a `close()`.
NOT_OPENED = "The line to the Ruida is not open."
#: After `disconnect()`.
CLOSED = "The connection to the Ruida was closed."


class RuidaLink:
    kind = "ruida"

    def __init__(self, device, *, send_port: int = SEND_PORT,
                 listen_port: int = LISTEN_PORT, reply_seconds: float = 1.0,
                 poll_seconds: float = 0.2):
        self.device = device
        self.send_port = send_port
        self.listen_port = listen_port
        self.reply_seconds = reply_seconds
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._changed = threading.Condition()
        self._session: RuidaSession | None = None
        self._monitor: Monitor | None = None
        self._settings: tuple[str, int] | None = None
        self._wanted = False
        self._detail: str | None = None

    # -- the engine's settings ----------------------------------------------

    def _address(self) -> str:
        return str(getattr(self.device, "address", "") or "").strip()

    def _magic(self) -> int:
        magic = getattr(self.device, "magic", None)
        return magic if isinstance(magic, int) else framing.DEFAULT_MAGIC

    def _refusal(self, address: str) -> str | None:
        """The transport's sentence when `address` is not one it will take."""
        try:
            UdpTransport(address, send_port=self.send_port, listen_port=self.listen_port)
        except ValueError as error:
            return str(error)
        return None

    # -- MachineLink ----------------------------------------------------------

    @property
    def connect_seconds(self) -> float:
        return self.reply_seconds * 3

    @property
    def generation(self) -> int | None:
        session = self._session
        return None if session is None else session.generation

    @property
    def session(self) -> RuidaSession | None:
        return self._session

    @property
    def monitor(self) -> Monitor | None:
        return self._monitor

    def connect(self) -> dict:
        with self._lock:
            address = self._address()
            refusal = self._refusal(address)
            if refusal is not None:
                self._detail = refusal
                self._wanted = False
                if self._session is not None:
                    self._monitor.stop()
                    self._session.close()
                return self.connection()
            settings = (address, self._magic())
            if self._session is not None and settings != self._settings:
                self._release()
            if self._session is None:
                self._session = RuidaSession(
                    lambda: UdpTransport(address, send_port=self.send_port,
                                         listen_port=self.listen_port),
                    magic=settings[1], reply_seconds=self.reply_seconds,
                    on_state=self._on_state)
                self._monitor = Monitor(self._session, poll_seconds=self.poll_seconds)
                self._settings = settings
            session, monitor = self._session, self._monitor
            self._wanted = True
            self._detail = None
            session.open()
            monitor.start()
        bound = self.connect_seconds
        with self._changed:
            self._changed.wait_for(
                lambda: session.connected or not self._wanted
                or self._session is not session, timeout=bound)
        with self._lock:
            if self._session is session and self._wanted and not session.connected:
                self._wanted = False
                self._detail = (f"The Ruida at {address} did not answer within "
                                f"{bound:g} seconds.")
                monitor.stop()
                session.close()
            return self.connection()

    def disconnect(self) -> dict:
        with self._lock:
            self._wanted = False
            self._detail = CLOSED
            if self._session is not None:
                self._monitor.stop()
                self._session.close()
        self._notify()
        return self.connection()

    def connection(self) -> dict:
        try:
            with self._lock:
                session = self._session
                if session is None or not self._wanted:
                    refusal = self._refusal(self._address())
                    return {"state": "disconnected",
                            "detail": refusal or self._detail or NOT_OPENED}
                state = session.state
                if state == "connected":
                    return {"state": "connected", "detail": None}
                if state == "connecting":
                    return {"state": "connecting",
                            "detail": session.detail
                            or f"Connecting to the Ruida at {self._settings[0]}."}
                return {"state": "disconnected", "detail": self._detail or CLOSED}
        except Exception as error:  # never raises, by the Protocol
            return {"state": "unknown", "detail": f"The Ruida line could not be read: {error}."}

    def position(self) -> tuple[int, int] | None:
        monitor = self._monitor
        return None if monitor is None else monitor.position

    def machine_state(self) -> str:
        monitor = self._monitor
        if monitor is None or not self._wanted:
            return "unknown"
        return machine_state(monitor.status_word)

    def line_in_use(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            self._wanted = False
            self._detail = None
            self._release()
        self._notify()

    # -- inside ------------------------------------------------------------------

    def _release(self) -> None:
        monitor, session = self._monitor, self._session
        self._monitor = self._session = None
        self._settings = None
        if monitor is not None:
            monitor.stop()
        if session is not None:
            session.shutdown()

    def _notify(self) -> None:
        with self._changed:
            self._changed.notify_all()

    def _on_state(self, state: str, detail: str) -> None:
        self._notify()
