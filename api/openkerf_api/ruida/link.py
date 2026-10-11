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

Phase 4, moving and the realtime verbs, sends the packets the engine's `RuidaDriver`
wrote for the same console command (`encode.py`, compared in
`test_ruida_link_motion.py`), converting the design's millimetres through the engine
device's own `view`:

- **Motion verbs** (`home`, `move_to`, `move_by`, `trace`, `focus`) take the file lock
  without waiting and refuse with `FILE_GOING_OUT` when a file holds it; they run one
  at a time. A move is worked out from the head's last reading, so the next one first
  waits — up to `ARRIVE_SECONDS`, as the engine's `wait_for_move` — for the head to be
  read where the last one sent it; before any reading at all they refuse (`NO_POSITION`).
- **`pause`, `resume`, `stop`** go in the session's priority lane and never wait for
  the file lock. `stop()` also ends a file going out at the packet on the line and
  cuts short a move waiting for the head.
- **A line that is not up** refuses at once with `ConnectionError` and the link's own
  sentence (`connection()["detail"]`); nothing is queued for later.
"""

import concurrent.futures
import threading
import time

from meerk40t.ruida.rdjob import MEM_CURRENT_X, MEM_CURRENT_Y

from ..link import LineTaken, SendInterrupted
from . import encode, framing
from .monitor import Monitor, machine_state
from .session import RuidaSession
from .transport import LISTEN_PORT, SEND_PORT, UdpTransport

#: Before the first `connect()`, and after a `close()`.
NOT_OPENED = "The line to the Ruida is not open."
#: After `disconnect()`.
CLOSED = "The connection to the Ruida was closed."
#: A move while `send_file` holds the line.
FILE_GOING_OUT = ("A file is being sent to the Ruida; the head is not moved while it "
                  "goes out. Nothing was sent.")
#: A move before the monitor has read X and Y once.
NO_POSITION = ("The Ruida has not reported where the head is yet, and a move is "
               "worked out from there. Nothing was sent.")
#: `lock` / `unlock`.
NO_RAIL_LOCK = ("A Ruida has no command to lock or release the motors. Nothing was "
                "sent.")
#: How `send_file` ends when `stop()` comes in during it.
FILE_STOPPED = "The file was stopped; nothing after this packet was sent."
#: A frame or a move waiting for the head that `stop()` cut short.
MOTION_STOPPED = "Stopped; the rest of the movement was not sent."


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
        #: One file on the line at a time; held for the whole of `send_file`, and by
        #: a motion verb for as long as it sends, so neither weaves into the other.
        self._file = threading.Lock()
        self._uploading = False
        #: Set by `stop()` while a file goes out; `send_file` ends at the next packet.
        self._file_stop: threading.Event | None = None
        #: The file packet waiting for its ACK, so `stop()` can take it back.
        self._receipt = None
        #: Motion verbs one at a time, as the engine's spooler ran them.
        self._motion = threading.Lock()
        #: Where the last move sent the head (controller units) and when, until it is
        #: seen there; the next move waits for that, as `wait_for_move` made it.
        self._target: tuple[float, float] | None = None
        self._target_at = 0.0
        #: Counts `stop()` calls; a wait that sees it change gives up.
        self._stops = 0

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
        - **`stop()` ends it.** The packet on the line finishes (the session has one
          in flight at a time); one still in the queue is taken back; nothing after it
          is written. It raises `SendInterrupted` at that packet with `FILE_STOPPED`,
          `on_line` saying whether that packet went out. The stop itself goes ahead in
          the session's priority lane, so it is the next thing on the wire. A file in
          the controller's memory cut off like this is incomplete; what the controller
          does with it is a question for the hardware.
        - **Before the first packet the line must be clear**: a read that was already
          on it is let finish, within `packet_seconds`; otherwise the file stalls at
          packet 0 with nothing sent.
        """
        if not self._file.acquire(timeout=claim_seconds):
            raise LineTaken("Another file is being sent on this line.")
        stopped = threading.Event()
        try:
            with self._lock:
                session, monitor = self._session, self._monitor
                if session is None or not self._wanted or not session.connected:
                    raise SendInterrupted(
                        0, on_line=False, stalled=False,
                        why="Not connected to the Ruida controller.")
                generation = session.generation
                self._uploading = True
                self._file_stop = stopped
            if monitor is not None:
                monitor.pause()
            try:
                for index, packet in enumerate(packets):
                    if stopped.is_set():
                        raise SendInterrupted(index, on_line=False, stalled=False,
                                              why=FILE_STOPPED)
                    self._until_clear(session, index, packet_seconds, stopped)
                    self._send_one(session, index, packet, generation, packet_seconds,
                                   stopped)
            finally:
                if monitor is not None:
                    monitor.resume()
        finally:
            with self._lock:
                self._uploading = False
                self._file_stop = None
                self._receipt = None
            self._file.release()

    def _until_clear(self, session, index: int, seconds: float,
                     stopped: threading.Event) -> None:
        deadline = time.monotonic() + seconds
        while session.busy:
            if stopped.is_set():
                raise SendInterrupted(index, on_line=False, stalled=False,
                                      why=FILE_STOPPED)
            if not session.connected:
                raise SendInterrupted(index, on_line=False, stalled=False,
                                      why="The Ruida stopped answering.")
            if time.monotonic() > deadline:
                raise SendInterrupted(index, on_line=False, stalled=True,
                                      why="The line to the Ruida did not come free.")
            time.sleep(self.CLEAR_POLL_SECONDS)

    def _send_one(self, session, index: int, packet: bytes, generation: int,
                  seconds: float, stopped: threading.Event) -> None:
        with self._lock:
            if stopped.is_set():
                raise SendInterrupted(index, on_line=False, stalled=False,
                                      why=FILE_STOPPED)
            try:
                receipt = session.write(packet, generation=generation)
            except (ConnectionError, OSError) as error:
                raise SendInterrupted(index, on_line=False, stalled=False,
                                      why=str(error)) from error
            self._receipt = receipt
        try:
            receipt.result(timeout=seconds)
        except concurrent.futures.CancelledError as error:
            # Only `stop()` cancels a file packet, and only one still in the queue.
            raise SendInterrupted(index, on_line=False, stalled=False,
                                  why=FILE_STOPPED) from error
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
        except (ConnectionError, OSError) as error:
            raise SendInterrupted(index, on_line=True, stalled=False,
                                  why=str(error)) from error
        finally:
            with self._lock:
                if self._receipt is receipt:
                    self._receipt = None

    # -- phase 4: moving the head, and the realtime verbs ----------------------------

    #: How long a move waits for the head to be seen where the last one sent it: the
    #: engine's `wait_for_move`, 50 tries of 0.2 s (`ruida/controller.py:404-420`).
    #: After that it goes on from the last reading, as the engine did.
    ARRIVE_SECONDS = 10.0
    #: How often that wait looks at the monitor's readings.
    ARRIVE_POLL_SECONDS = 0.02
    #: `machine.py`'s jog ran `move_relative` without `-f`: the driver's clamp applied.
    CONFINED = True

    def motion_capabilities(self) -> dict:
        """
        What a Ruida can be asked, as the engine answered it: everything but the rail.
        `lock`/`unlock` wrote 0 bytes through the engine (`encode.py`).
        """
        return {"home": True, "physical_home": True, "move": True, "jog": True,
                "frame": True, "focus": True, "lock": False, "unlock": False,
                "pause": True, "resume": True, "stop": True}

    def home(self, physical: bool = False) -> None:
        """
        `home` is a move to the design's (0, 0); `physical_home` is `D8 2A`, to the
        end stops. The engine then held its spooler until the controller said idle
        and reopened its session (`RuidaController.sync`); here the next move is not
        held back — the controller's answers during the run to the end stops are
        what the hardware test has to show.
        """
        if not physical:
            self.move_to(0.0, 0.0, _home=True)
            return
        with self._motion:
            self._claim_line()
            try:
                self._send(encode.home_xy())
                self._target = None
            finally:
                self._file.release()

    def move_to(self, x_mm: float, y_mm: float, *, _home: bool = False) -> None:
        # `home` is `move_abs(0, 0)` with plain numbers (`driver.py:390`); a console
        # `move_absolute` passed `Length`s. Both reach `View.position` the same way.
        x = 0 if _home else encode.millimetres(x_mm)
        y = 0 if _home else encode.millimetres(y_mm)
        with self._motion:
            self._claim_line()
            try:
                stops = self._stops
                native = self._settle(stops)
                packets, target = encode.move_to(self._view(), x, y, *native)
                self._send(packets)
                self._aim(target)
            finally:
                self._file.release()

    def move_by(self, dx_mm: float, dy_mm: float) -> None:
        with self._motion:
            self._claim_line()
            try:
                native = self._settle(self._stops)
                packets, target = encode.move_by(
                    self._view(), encode.millimetres(dx_mm), encode.millimetres(dy_mm),
                    *native, confined=self.CONFINED)
                self._send(packets)
                self._aim(target)
            finally:
                self._file.release()

    def trace(self, corners: list[tuple[float, float]]) -> None:
        """
        One `move_absolute -f` per corner, as `machine.py`'s frame ran them; each waits
        for the head to be seen at the corner before (the engine's `wait_for_move`), so
        every corner is worked out from where the head is. `stop()` ends it between
        corners with `MOTION_STOPPED`.
        """
        points = [(encode.millimetres(x), encode.millimetres(y)) for x, y in corners]
        with self._motion:
            self._claim_line()
            try:
                stops = self._stops
                view = self._view()
                for x, y in points:
                    native = self._settle(stops)
                    packets, target = encode.move_to(view, x, y, *native)
                    self._send(packets)
                    self._aim(target)
            finally:
                self._file.release()

    def focus(self, dz_mm: float) -> None:
        """`D8 2E`, as the engine's `focusz` sent it: the distance is not encoded."""
        with self._motion:
            self._claim_line()
            try:
                self._send(encode.focus_z())
            finally:
                self._file.release()

    def lock(self) -> None:
        raise ConnectionError(NO_RAIL_LOCK)

    def unlock(self) -> None:
        raise ConnectionError(NO_RAIL_LOCK)

    def pause(self) -> None:
        """`D8 02` in the priority lane; also while a file goes out."""
        self._send(encode.pause(), priority=True)

    def resume(self) -> None:
        """
        `D8 03`, also in the priority lane: a paused job's file must not hold its own
        resume behind it. Sent whether or not we paused — the panel can pause too, and
        the engine's own `resume` only skipped it on its local flag.
        """
        self._send(encode.resume(), priority=True)

    def stop(self) -> None:
        """
        `D8 01` ahead of everything queued, without waiting for the file lock.

        A file going out ends at the packet on the line (see `send_file`); a frame or
        a move waiting for the head gives up; the remembered target is dropped.

        What it does *not* do, measured on the KH-5030 (RDC6442S): stop a rapid move that
        is already under way. A move from (20, 20) to (200, 100) mm with this stop sent
        0.3 s in — acknowledged in 7 ms — ran on to (200.0, 100.0) and arrived 1.2 s
        after the move was sent. Ruida Bridge uses the same `D8 01` as its "stop job"
        for a job run from the controller's memory; whether it halts a running job here
        is for the first burn to measure. Until then the machine's own stop is the stop.
        """
        with self._lock:
            self._stops += 1
            self._target = None
            stopping, receipt = self._file_stop, self._receipt
            if stopping is not None:
                stopping.set()
            if receipt is not None:
                receipt.cancel()
        self._send(encode.stop(), priority=True)

    # -- motion, inside ------------------------------------------------------------

    def _view(self):
        return self.device.view

    def _refuse_unless_connected(self):
        with self._lock:
            session = self._session
            if session is not None and self._wanted and session.connected:
                return session
        detail = self.connection()["detail"]
        raise ConnectionError(detail or "Not connected to the Ruida controller.")

    def _claim_line(self) -> None:
        """The file lock without waiting, or the refusal; then a connected line."""
        if not self._file.acquire(blocking=False):
            raise ConnectionError(FILE_GOING_OUT)
        try:
            self._refuse_unless_connected()
        except BaseException:
            self._file.release()
            raise

    def _send(self, packets: list[bytes], *, priority: bool = False) -> None:
        """
        Queue every packet of one verb together and wait for each ACK.

        Together, so nothing of the monitor's comes between a speed and its move. A
        packet the session fails (no ACK, NAK after the resends, the line gone) fails
        the ones behind it in the session too, and this raises `ConnectionError`; a
        receipt that does not complete within the bound raises `TimeoutError`.
        """
        session = self._refuse_unless_connected()
        receipts = []
        try:
            for packet in packets:
                receipts.append(session.write(packet, priority=priority))
        except ConnectionError:
            for receipt in receipts:
                receipt.cancel()
            raise
        bound = self.reply_seconds * (len(packets) + 2)
        deadline = time.monotonic() + bound
        for index, receipt in enumerate(receipts):
            try:
                receipt.result(timeout=max(0.0, deadline - time.monotonic()))
            except concurrent.futures.CancelledError as error:
                raise ConnectionError("The command was withdrawn before it was sent.") from error
            except concurrent.futures.TimeoutError as error:
                if receipt.done():  # the session's own: acknowledged, not answered
                    raise TimeoutError(str(error)) from error
                for rest in receipts[index:]:
                    rest.cancel()
                raise TimeoutError(
                    f"The Ruida did not confirm the command within {bound:g} seconds."
                ) from error
            except OSError as error:
                raise ConnectionError(str(error)) from error

    def _aim(self, target) -> None:
        with self._lock:
            self._target = target
            self._target_at = time.monotonic()

    def _settle(self, stops: int) -> tuple[float, float]:
        """
        Where the head is, in controller units, once the last move has been seen to
        arrive or `ARRIVE_SECONDS` have gone by — the engine's `wait_for_move`, which
        compares in whole millimetres. Readings older than that move do not count.
        """
        with self._lock:
            target, since = self._target, self._target_at
        if target is not None:
            deadline = time.monotonic() + self.ARRIVE_SECONDS
            want = (round(target[0] / 1000), round(target[1] / 1000))
            while time.monotonic() < deadline:
                if self._stops != stops:
                    raise ConnectionError(MOTION_STOPPED)
                seen = self._fresh_position(since)
                if seen is not None and (round(seen[0] / 1000),
                                         round(seen[1] / 1000)) == want:
                    break
                time.sleep(self.ARRIVE_POLL_SECONDS)
            with self._lock:
                if self._target is target:
                    self._target = None
        if self._stops != stops:
            raise ConnectionError(MOTION_STOPPED)
        position = self.position()
        if position is None:
            raise ConnectionError(NO_POSITION)
        return position

    def _fresh_position(self, since: float):
        monitor = self._monitor
        if monitor is None:
            return None
        x, y = monitor.reading(MEM_CURRENT_X), monitor.reading(MEM_CURRENT_Y)
        if x is None or y is None or x.at <= since or y.at <= since:
            return None
        return (x.value, y.value)

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
