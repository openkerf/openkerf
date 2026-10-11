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

import concurrent.futures
import threading
import time

from ..link import LineTaken, SendInterrupted
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
        #: One file on the line at a time; held for the whole of `send_file`.
        self._file = threading.Lock()
        self._uploading = False

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

    def line_in_use(self) -> str | None:
        return "uploading" if self._uploading else None

    carries_files = True

    #: How often `send_file` looks again at a line that is still busy before a packet.
    CLEAR_POLL_SECONDS = 0.005

    def send_file(self, packets, *, packet_seconds: float = 10.0,
                  claim_seconds: float = 2.0) -> None:
        """
        The `MachineLink` contract, on our session.

        - **One generation for the whole file.** It is read once, before the first
          packet, and every write names it (`RuidaSession.write(generation=...)`). A
          reconnect anywhere in the file moves it on, and the next write is refused:
          the file fails at that packet and is never resumed on the new connection.
        - **One packet at a time.** Each is written only once the one before it is
          confirmed; a missing ACK fails it in the session and the file stops there —
          the session never sends it again. A NAK is resent by the session, bounded.
        - **The monitor is paused for the length of the file**, as the engine's own
          sender holds the status monitor off with `_job_lock`. Measured against
          `ruida_peer` (`test_ruida_upload_link.py`): unpaused, the monitor put 0 reads
          between the blocks of an eight-circle file in 6 of 6 runs, with and without a
          30 ms ACK delay — it skips while the session is busy, and the gap between one
          receipt and the next write is shorter than its period. Hold the line idle for
          0.2 s between two blocks and, unpaused, reads go out in that gap; paused, none
          (`test_no_status_poll_goes_out_during_the_upload`). The upload took the same
          time either way (280–288 ms with the 30 ms delay). So the pause costs nothing
          measured and makes "no read inside a file" a rule rather than a timing. It
          matters on hardware: a read does no harm to the file
          (`test_a_status_poll_between_blocks_does_not_damage_the_file`), but a KH-5030
          left memory reads acknowledged and unanswered — the first on a fresh socket,
          and about 40% at 0.2 s polling — and such a read holds the next block for the
          session's whole reply wait.
        - **Before the first packet the line must be clear**: a read that was already
          on it is let finish, within `packet_seconds`; otherwise the file stalls at
          packet 0 with nothing sent.
        """
        if not self._file.acquire(timeout=claim_seconds):
            raise LineTaken("Another file is being sent on this line.")
        try:
            with self._lock:
                session, monitor = self._session, self._monitor
                if session is None or not self._wanted or not session.connected:
                    raise SendInterrupted(
                        0, on_line=False, stalled=False,
                        why="Not connected to the Ruida controller.")
                generation = session.generation
                self._uploading = True
            if monitor is not None:
                monitor.pause()
            try:
                for index, packet in enumerate(packets):
                    self._until_clear(session, index, packet_seconds)
                    self._send_one(session, index, packet, generation, packet_seconds)
            finally:
                if monitor is not None:
                    monitor.resume()
        finally:
            self._uploading = False
            self._file.release()

    def _until_clear(self, session, index: int, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while session.busy:
            if not session.connected:
                raise SendInterrupted(index, on_line=False, stalled=False,
                                      why="The Ruida stopped answering.")
            if time.monotonic() > deadline:
                raise SendInterrupted(index, on_line=False, stalled=True,
                                      why="The line to the Ruida did not come free.")
            time.sleep(self.CLEAR_POLL_SECONDS)

    @staticmethod
    def _send_one(session, index: int, packet: bytes, generation: int,
                  seconds: float) -> None:
        try:
            receipt = session.write(packet, generation=generation)
        except (ConnectionError, OSError) as error:
            raise SendInterrupted(index, on_line=False, stalled=False,
                                  why=str(error)) from error
        try:
            receipt.result(timeout=seconds)
        except concurrent.futures.TimeoutError as error:
            if receipt.done():
                # The session's own `TimeoutError`, set on the receipt: gone out and
                # not confirmed, the same as a missing ACK.
                raise SendInterrupted(index, on_line=True, stalled=False,
                                      why=str(error)) from error
            # Still in the queue: take it back. Already on the line: never resent.
            cancelled = receipt.cancel()
            raise SendInterrupted(index, on_line=not cancelled, stalled=True,
                                  why="The Ruida did not confirm the packet in time.") from error
        except (ConnectionError, OSError, concurrent.futures.CancelledError) as error:
            raise SendInterrupted(index, on_line=True, stalled=False,
                                  why=str(error)) from error

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
