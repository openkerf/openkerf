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
- **A second program on the same controller** is said in `connection()["warning"]`
  (code `ruida.secondClient`) while the state stays "connected": the line works, our
  answers are being lost. The rule is `monitor.SecondClient`'s; it clears itself.
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

Phase 5, burning, streams a whole RD file (`CommandRunner.build_job_bytes()`) the way
the engine did: no start opcode, no file name, no upload command — the file is the
job. `RuidaDriver.plot_start` writes the header (with its `D8 00` start-process,
`rdjob.py:1414`) and tail into an `RDJob` buffer and ends on
`controller.stop_record()` (`driver.py:300-301`), which is `start_sending()`
(`controller.py:327-328`): `divide_data_into_queue` cuts the buffer into blocks
(`:84-95`, `framing.job_blocks`) and `_data_sender` writes them one by one, each
waiting for its ACK, with the status monitor held off by `_job_lock` (`:116-135`).
The controller burns as the blocks come in. What `start_record` sends first
(`:323-325`) is only a card-id read, which our monitor does anyway.

- **`start_job` takes the file lock** and holds it until the job has ended (done,
  stopped or failed), so an upload, a move or a second job cannot weave into it or
  run under a burning head; each refuses at once with its own sentence.
- **One generation** for the whole stream, as `send_file`: a reconnect fails the job
  ("failed", "N of M" in the detail) and nothing is ever resumed. A missing ACK fails
  it the same way; the session never resends that block.
- **The monitor is paused while blocks go out** (as the engine's `_job_lock` did) and
  runs again after the last one: completion is read from the status word, never from
  the last ACK — an acknowledged block is not a burned one. See `_watch` for the rule.
- **`stop()`** cuts the stream as for `send_file`, sends `D8 01` ahead of everything,
  and ends the job "stopped" with a sentence that says the machine's own stop is the
  sure one: on the KH-5030 `D8 01` did not stop a rapid move, and nobody has measured
  yet what it does to a running job. `pause()` and `resume()` go in the priority lane
  during a job as at any other time.
"""

import concurrent.futures
import threading
import time

import logging

from meerk40t.ruida.rdjob import MEM_CURRENT_X, MEM_CURRENT_Y, MEM_MACHINE_STATUS

from ..link import BurnClock, LineTaken, SendInterrupted
from . import encode, framing
from .monitor import Monitor, machine_state
from .session import RuidaSession
from .transport import LISTEN_PORT, SEND_PORT, UdpTransport

log = logging.getLogger(__name__)

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

# -- phase 5: the refusals of `start_job`, and what the others say during a job --------

#: `start_job` while another job holds the line.
JOB_ON_LINE = ("The Ruida is already burning a job; another cannot start until it is "
               "done or stopped. Nothing was sent.")
#: `start_job` while `send_file` holds the line.
FILE_BEFORE_JOB = ("A file is being sent to the Ruida; a job cannot start until it has "
                   "gone out. Nothing was sent.")
#: `start_job` while a motion verb holds the line.
MOTION_BEFORE_JOB = ("The head is being moved; a job cannot start until the move has "
                     "been sent. Nothing was sent.")
#: A motion verb while a job holds the line.
BURNING = ("The Ruida is burning a job; the head is not moved until it is done or "
           "stopped. Nothing was sent.")
#: `send_file` while a job holds the line (as `LineTaken`).
JOB_HOLDS_LINE = "The Ruida is burning a job on this line."
EMPTY_JOB = "The job file is empty. Nothing was sent."
OVERSIZED_JOB = ("A command in the job file is too long for one packet to the Ruida. "
                 "Nothing was sent.")
#: "done" without the controller ever having been seen at work (see `_watch`).
NEVER_SEEN_RUNNING = ("The Ruida took the whole job but was never seen running; whether "
                      "it burned is not known from here.")
#: "failed" when `close()` lets go of a job the controller has.
LET_GO = ("OpenKerf let go of the line while the Ruida had the job; what the machine "
          "did after that is not known from here.")

_ACTIVE = ("sending", "running", "paused")
_FINAL = ("done", "stopped", "failed")


def _broke_off(sent: int, total: int, why: str) -> str:
    why = why.strip() or "The line to the Ruida failed."
    if not why.endswith("."):
        why += "."
    return (f"The job broke off after {sent} of {total} packets: {why} Nothing after "
            "that was sent and nothing was sent twice. The machine may burn the part "
            "it received; if the head keeps moving, the machine's own stop is the sure "
            "stop.")


def _stopped(job, error: Exception | None) -> str:
    if error is not None:
        why = str(error).strip()
        if why and not why.endswith("."):
            why += "."
        cut = ("The rest of the job was not sent, but" if job.sent < job.total
               else "The")
        return (f"{cut} the stop command did not reach the Ruida: {why} Use the "
                "machine's own stop.")
    if job.sent < job.total:
        return (f"Stopped after {job.sent} of {job.total} packets; the rest of the job "
                "was not sent. The Ruida acknowledged the stop command, but if the head "
                "keeps moving, the machine's own stop is the sure stop.")
    return ("Stopped; the Ruida acknowledged the stop command and ends the job where "
            "the head is. If the head keeps moving, use the machine's own stop.")


class _Job:
    """One streamed job; every field is read and written under `RuidaLink._lock`."""

    def __init__(self, name: str | None, total: int, estimate: float | None = None):
        self.name = name
        self.phase = "sending"
        #: The cut plan's estimate of the burn, as `start_job` was given it.
        self.estimate = estimate
        #: Seconds spent in "running"; moved by every phase change below.
        self.clock = BurnClock()
        self.sent = 0
        self.total = total
        self.detail: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        #: `time.monotonic()` when the last block was confirmed.
        self.acked_at: float | None = None
        #: Set by `stop()` before it sends; nothing else may end the job after that.
        self.stopping = False
        #: The worker has left the stream (all confirmed, or broken off).
        self.streamed = threading.Event()
        #: A final phase has been set.
        self.ended = threading.Event()

    def snapshot(self) -> dict:
        return {"name": self.name, "phase": self.phase, "sent": self.sent,
                "total": self.total, "detail": self.detail, "started": self.started,
                "finished": self.finished, "estimate_seconds": self.estimate,
                "running_seconds": self.clock.seconds()}


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
        #: The last job started, kept until the next; and the thread that carries it.
        self._job: _Job | None = None
        self._job_thread: threading.Thread | None = None

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
                    reading = {"state": "connected", "detail": None}
                elif state == "connecting":
                    reading = {"state": "connecting",
                               "detail": session.detail
                               or f"Connecting to the Ruida at {self._settings[0]}."}
                else:
                    return {"state": "disconnected", "detail": self._detail or CLOSED}
                # Only while it stands, so a reading without one keeps its old shape.
                monitor = self._monitor
                warning = monitor.second_client.warning() if monitor is not None else None
                if warning is not None:
                    reading["warning"] = warning
                return reading
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
        job = self._job
        if job is not None and job.phase in _ACTIVE:
            return "burning"
        return "uploading" if self._uploading else None

    def _job_active(self) -> bool:
        job = self._job
        return job is not None and job.phase in _ACTIVE

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
        if self._job_active():
            raise LineTaken(JOB_HOLDS_LINE)
        if not self._file.acquire(timeout=claim_seconds):
            if self._job_active():
                raise LineTaken(JOB_HOLDS_LINE)
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
    #: Close enough to the last move's target to count as there, in controller units
    #: (µm). The engine compared whole millimetres, so a target on a half millimetre
    #: could be missed by a reading a few µm either side and cost the full wait.
    ARRIVE_TOLERANCE_UM = 500
    #: A head that stands still somewhere else has arrived as far as the next move is
    #: concerned: the status word not moving, read at least this long after the send,
    #: and the position unchanged for as long. Measured on the KH-5030: the moving word
    #: came 0.17–0.22 s after a move was sent, so 0.5 s does not mistake a move that
    #: has not started yet for one that ended.
    STILL_SECONDS = 0.5
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
        a move waiting for the head gives up; the remembered target is dropped. A job
        ends "stopped": the rest of its stream is not sent, and its detail says the
        machine's own stop is the sure one — or, when the stop itself could not be
        sent, that it did not reach the Ruida (and this raises, as for any verb).

        What it does *not* do, measured on the KH-5030 (RDC6442S): stop a rapid move that
        is already under way. A move from (20, 20) to (200, 100) mm with this stop sent
        0.3 s in — acknowledged in 7 ms — ran on to (200.0, 100.0) and arrived 1.2 s
        after the move was sent. For a move, the machine's own stop is the stop.

        What it does do, measured on the same machine burning a 40 × 40 mm square at
        50 mm/s and 15 %: stop sent 1.55 s in, acknowledged in 6 ms; the wood shows the
        first side whole and the second side just begun, and the controller then took
        the head to (0, 0) as it does at the end of a job. Ruida Bridge uses the same
        `D8 01` as its "stop job".
        """
        with self._lock:
            self._stops += 1
            self._target = None
            stopping, receipt = self._file_stop, self._receipt
            if stopping is not None:
                stopping.set()
            if receipt is not None:
                receipt.cancel()
            job = self._job
            if job is not None and job.phase in _ACTIVE and not job.stopping:
                job.stopping = True
            else:
                job = None
        error = None
        try:
            self._send(encode.stop(), priority=True)
        except (ConnectionError, TimeoutError) as failure:
            error = failure
        if job is not None:
            # The block on the line finishes first (one in flight); after the stop's
            # own ACK the stream has normally left already, so `sent` is final.
            job.streamed.wait(self.reply_seconds + 1)
            with self._lock:
                detail = _stopped(job, error)
            self._end(job, "stopped", detail)
        if error is not None:
            raise error

    # -- phase 5: burning -----------------------------------------------------------

    carries_jobs = True

    #: The bound on one block's confirmation, as `send_file`'s default.
    JOB_PACKET_SECONDS = 10.0
    #: Fresh idle status words in a row, after the controller has been seen at work,
    #: that make a job "done"; two, so one odd word cannot end a job. Measured on the
    #: KH-5030 over three burns: the words went running (66561, 66565; 66563 paused;
    #: 8455169 just after a resume) straight to idle (67072) with no idle word in
    #: between, and two idle readings put "done" 0.4–0.7 s after the head stood still.
    IDLE_READINGS = 2
    #: How long after the last block a controller that was never seen at work may
    #: read idle before the job is called done anyway (with `NEVER_SEEN_RUNNING`).
    #: Measured on the KH-5030: the first running word came 0.17–0.22 s after the
    #: start, so 10 s is far beyond what that machine needs.
    START_SECONDS = 10.0
    #: How often the watcher looks at the monitor's newest status word.
    WATCH_SECONDS = 0.05

    def start_job(self, rd: bytes, name: str | None = None,
                  estimate_seconds: float | None = None) -> None:
        """
        The `MachineLink` contract: stream `rd` on a worker of our own and return as
        soon as it has started. Refused with `ConnectionError` — nothing sent — when
        the line is not up, when a job, a file or a move holds it, or when the file
        is empty or has a command too long for one datagram.
        """
        blocks = framing.job_blocks(bytes(rd))
        if not blocks:
            raise ConnectionError(EMPTY_JOB)
        if any(len(block) > framing.DATAGRAM_LIMIT - 2 for block in blocks):
            raise ConnectionError(OVERSIZED_JOB)
        self._refuse_unless_connected()
        if not self._file.acquire(blocking=False):
            raise ConnectionError(self._taken())
        try:
            with self._lock:
                session, monitor = self._session, self._monitor
                if session is None or not self._wanted or not session.connected:
                    raise ConnectionError(self.connection()["detail"]
                                          or "Not connected to the Ruida controller.")
                generation = session.generation
                stopped = threading.Event()
                self._file_stop = stopped
                job = _Job(name, len(blocks), estimate_seconds)
                self._job = job
                # A job moves the head and ends where the controller puts it (this
                # one goes to (0, 0)); the last move's target says nothing any more.
                self._target = None
                thread = threading.Thread(
                    target=self._carry, name="ruida-job", daemon=True,
                    args=(job, session, monitor, generation, blocks, stopped))
                self._job_thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                if self._file_stop is not None and self._job_thread is None:
                    self._file_stop = None
            self._file.release()
            raise

    def job(self) -> dict | None:
        try:
            with self._lock:
                job = self._job
                return None if job is None else job.snapshot()
        except Exception:  # never raises, by the Protocol
            return None

    def _taken(self) -> str:
        if self._job_active():
            return JOB_ON_LINE
        return FILE_BEFORE_JOB if self._uploading else MOTION_BEFORE_JOB

    def _end(self, job: _Job, phase: str, detail: str | None) -> bool:
        """The job's final phase; the first caller wins, later ones change nothing."""
        with self._lock:
            if job.phase in _FINAL:
                return False
            job.phase = phase
            job.clock.phase(phase)
            job.detail = detail
            job.finished = time.time()
            self._target = None
        job.ended.set()
        return True

    def _phase(self, job: _Job, phase: str) -> None:
        with self._lock:
            if job.phase in _ACTIVE and not job.stopping:
                job.phase = phase
                job.clock.phase(phase)

    def _carry(self, job, session, monitor, generation, blocks, stopped) -> None:
        """The worker: the stream, then the watch; the file lock goes with it."""
        try:
            if self._stream(job, session, monitor, generation, blocks, stopped):
                self._watch(job)
        except Exception as error:
            log.exception("Ruida job worker failed")
            with self._lock:
                stopping, sent = job.stopping, job.sent
            if not stopping:
                self._end(job, "failed", _broke_off(sent, job.total, str(error)))
        finally:
            job.streamed.set()
            with self._lock:
                if self._job_thread is threading.current_thread():
                    self._job_thread = None
            self._file.release()

    def _stream(self, job, session, monitor, generation, blocks, stopped) -> bool:
        """Every block in order, each confirmed before the next; True when all were."""
        if monitor is not None:
            monitor.pause()
        try:
            for index, block in enumerate(blocks):
                if stopped.is_set():
                    raise SendInterrupted(index, on_line=False, stalled=False,
                                          why=FILE_STOPPED)
                self._until_clear(session, index, self.JOB_PACKET_SECONDS, stopped)
                self._send_one(session, index, block, generation,
                               self.JOB_PACKET_SECONDS, stopped)
                with self._lock:
                    job.sent = index + 1
        except SendInterrupted as error:
            with self._lock:
                stopping, sent = job.stopping or stopped.is_set(), job.sent
            if not stopping:
                self._end(job, "failed", _broke_off(sent, job.total, str(error)))
            return False
        finally:
            with self._lock:
                if self._file_stop is stopped:
                    self._file_stop = None
                self._receipt = None
                if job.sent == job.total:
                    job.acked_at = time.monotonic()
            if monitor is not None:
                monitor.resume()
            job.streamed.set()
        self._phase(job, "running")
        return True

    def _watch(self, job: _Job) -> None:
        """
        From the last ACK to the end of the job, on the status word alone.

        The rule, built to contradict none of the words we know (`monitor.machine_state`;
        KH-5030 idle 0 and 67072, moving 16975360; the emulator 22/21/23; Ruida Bridge
        1025 running and 1027 paused) and to survive what we do not know yet:

        - **Only fresh words count**: read after the last block was confirmed (the
          monitor was paused during the stream, so every word after it is new), and
          each word once, by the time it was read.
        - **"running" or "moving" → phase "running"; "paused" → "paused"**, and either
          means the controller has been seen at work.
        - **"done" takes `IDLE_READINGS` idle words in a row after it was seen at
          work.** An idle word before that is not the end — a controller may read idle
          for a moment before it begins — and one odd idle word does not end it.
        - **Never seen at work**: a job shorter than the time between two status reads
          could finish unseen. After `START_SECONDS` from the last ACK, with at least
          `IDLE_READINGS` idle words, it is "done" with `NEVER_SEEN_RUNNING` as the
          detail rather than a line held forever.
        - **No words, no verdict.** A silent controller or a closed line leaves the
          phase where it is; `stop()` and `close()` end it.
        """
        busy_seen = False
        idle = 0
        with self._lock:
            since = job.acked_at or time.monotonic()
        last = since
        while not job.ended.wait(self.WATCH_SECONDS):
            monitor = self._monitor
            reading = None if monitor is None else monitor.reading(MEM_MACHINE_STATUS)
            if reading is None or reading.at <= last:
                continue
            last = reading.at
            state = machine_state(reading.value)
            if state in ("running", "moving", "paused"):
                busy_seen = True
                idle = 0
                self._phase(job, "paused" if state == "paused" else "running")
            elif state == "idle":
                idle += 1
                waited = time.monotonic() - since >= self.START_SECONDS
                if idle >= self.IDLE_READINGS and (busy_seen or waited):
                    with self._lock:
                        if job.stopping:
                            continue
                    self._end(job, "done", None if busy_seen else NEVER_SEEN_RUNNING)

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
            raise ConnectionError(BURNING if self._job_active() else FILE_GOING_OUT)
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
        arrive — within `ARRIVE_TOLERANCE_UM` of its target, or standing still
        somewhere else (`_standing_still`) — or `ARRIVE_SECONDS` have gone by, the
        engine's `wait_for_move`. Readings older than that move do not count.

        Why "somewhere else" counts: the target used to outlive whatever moved the head
        next. After a frame, then a job (which ends at (0, 0) on the KH-5030), the next
        frame waited the full 10 s for the head to reach the old frame's last corner —
        the delay the user saw before a frame on a new sheet started.
        """
        with self._lock:
            target, since = self._target, self._target_at
        if target is not None:
            deadline = time.monotonic() + self.ARRIVE_SECONDS
            still = {"at": None, "where": None}
            while time.monotonic() < deadline:
                if self._stops != stops:
                    raise ConnectionError(MOTION_STOPPED)
                seen = self._fresh_position(since)
                if seen is not None:
                    if (abs(seen[0] - target[0]) <= self.ARRIVE_TOLERANCE_UM
                            and abs(seen[1] - target[1]) <= self.ARRIVE_TOLERANCE_UM):
                        break
                    if self._standing_still(since, seen, still):
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

    def _standing_still(self, since: float, seen, still: dict) -> bool:
        """
        The head is not going anywhere: a status word read `STILL_SECONDS` or more after
        the send says it is not moving, and the position has not changed for as long.
        """
        now = time.monotonic()
        if still["where"] != seen:
            still["where"], still["at"] = seen, now
            return False
        if now - still["at"] < self.STILL_SECONDS:
            return False
        monitor = self._monitor
        word = monitor.reading(MEM_MACHINE_STATUS) if monitor is not None else None
        if word is None or word.at < since + self.STILL_SECONDS:
            return False
        return machine_state(word.value) not in ("moving", "running")

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
            job, thread = self._job, self._job_thread
            if job is not None and job.phase in _ACTIVE and not job.stopping:
                detail = (_broke_off(job.sent, job.total,
                                     "The line to the Ruida was closed.")
                          if job.phase == "sending" else LET_GO)
            else:
                detail = None
        if detail is not None:
            self._end(job, "failed", detail)
        with self._lock:
            self._wanted = False
            self._detail = None
            self._release()
        if thread is not None and thread is not threading.current_thread():
            thread.join(self.reply_seconds + 2)
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
