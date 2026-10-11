"""
What the controller says it is doing, read through the session every 0.2 s.

The engine polls from `RuidaController._status_monitor` (`ruida/controller.py:168-190`):
one memory read every `_status_thread_sleep` = 0.2 s (`:45`), only while the device is
connected and not busy sending, rotating through `STATUS_ADDRESSES` (`:148-166`). We
read the three that a status bar needs — the status word, X and Y — and the card id
once; the bed size the engine also reads is a setting here, not a reading.

- **It never opens anything.** A read goes through `RuidaSession.read_memory`, which
  refuses at once when the line is not up and never reopens a closed session
  (`test_write_on_a_closed_session_does_not_reopen_it`). Opening, closing and
  reconnecting belong to the session and whoever owns it.
- **One read on the line at a time.** The engine fires a read every 0.2 s without
  waiting for the last; we wait for each answer, then pause `poll_seconds`, so a
  silent controller can never pile reads up behind each other.
- **A silence is the session's business.** What our session does when nothing
  answers, measured against `ruida_peer` with everything ignored for 5 s
  (reply_seconds 1.0, retry 0.5, the defaults; `test_ruida_link.py`,
  `test_a_five_second_silence_ends_connected_without_asking`): the read on the line
  fails after 1.0 s with "The Ruida did not acknowledge or answer in time.", the
  session goes from "connected" to "connecting", moves its generation on, closes its
  socket and after 0.5 s probes with ENQ again — and on, every 1.5 s, for as long as
  it stays open: four packets lost in the 5 s, generation 0 → 4. When the peer
  answers again the next probe makes it "connected" (1.21–1.23 s later in three
  runs, never "disconnected" in between), and the monitor, which only ever looked
  at `session.connected`, simply goes on reading. Nothing here has to undo anything; nothing here may reconnect.
- **Values are decoded by the engine's own functions.** `decode35` for the status
  word and the position, `decodeu35` for the card id, exactly as
  `RDJob.decode_reply` does (`ruida/rdjob.py:1332-1359`); the position is kept raw,
  as `update_x`/`update_y` store it in `driver.native_x`/`native_y`
  (`ruida/controller.py:258-276`).
- **`pause()` holds it off a file.** While a file goes down the line (`RuidaLink.send_file`)
  no read is queued; one already queued is cancelled, one already on the line is let
  finish. `resume()` lets it read again. The thread keeps running throughout, so a
  `start()` from a `connect()` in between changes nothing.
"""

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass

from meerk40t.ruida.rdjob import (
    CID_LUT,
    MACHINE_STATUS_JOB_RUNNING,
    MACHINE_STATUS_MOVING,
    MEM_CARD_ID,
    MEM_CURRENT_X,
    MEM_CURRENT_Y,
    MEM_MACHINE_STATUS,
    decode35,
    decodeu35,
)

log = logging.getLogger(__name__)

#: What is read over and over, in this order.
CYCLE = (MEM_MACHINE_STATUS, MEM_CURRENT_X, MEM_CURRENT_Y)


def decode(reply: bytes):
    """The value in a nine-byte answer, as `RDJob.decode_reply` makes it."""
    address = bytes(reply[2:4])
    if address == MEM_CARD_ID:
        return decodeu35(reply[4:9])
    return decode35(reply[4:9])


#: Bit 1 of the status word, beside JOB_RUNNING (bit 0): set together they are a
#: paused job. The engine calls 0x02 PART_END (`ruida/rdjob.py:233`).
_HELD = 0x02


def machine_state(word: int | None) -> str:
    """
    "running", "paused", "moving" or "idle" from a status word; "unknown" for none.

    Three sources, none of them complete, and this is the rule that contradicts none:

    - **A KH-5030 (RDC6442S)**, measured on 11 October: 0 when idle.
    - **Ruida Bridge** (github.com/MrkyWtrs/ruida_bridge, `ruida_bridge/app.py`,
      `decode_status_text`) reads the same address (`DA 00 04 00`) and looks only at
      the last two bytes of the unswizzled answer, i.e. the low 14 bits of this word
      as (bits 7-13, bits 0-6): (0, 0) and (12, 0) idle, (8, 1) running, (8, 3)
      paused — 0, 1536, 1025 and 1027 here.
    - **The engine's emulator** answers 22 (0x16) idle, 21 (0x15) running and 23
      (0x17) paused (`ruida/emulator.py:1361-1369`, its own comment "22 ok, 23
      paused. 21 running").

    So: JOB_RUNNING (0x01) with 0x02 is "paused", JOB_RUNNING alone "running"; the seven
    words above all fit that. The
    engine's MOVING bit (0x01000000, `controller.py:209`) is "moving" when no job bit
    is set: it lies outside Bridge's two bytes, so a job word that also has it stays
    a job. Everything else is "idle".

    Where we part from the engine's labels (`controller.py:209-217`): it names 0x02
    "Part end" and never idle, so the emulator's 22 and Bridge's (8, 3) would be
    neither idle nor paused there; and it tests MOVING before the job bits.
    """
    if word is None:
        return "unknown"
    if word & MACHINE_STATUS_JOB_RUNNING:
        return "paused" if word & _HELD else "running"
    if word & MACHINE_STATUS_MOVING:
        return "moving"
    return "idle"


def card_label(card_id: int) -> str:
    """As the engine names it (`ruida/rdjob.py:1342-1347`)."""
    return f"{CID_LUT.get(card_id, 'Unknown card.')}: (0x{card_id:08X})"


@dataclass(frozen=True)
class Reading:
    value: int
    #: `time.monotonic()` when the answer came in.
    at: float


class Monitor:
    """One polling thread over one session; started and stopped by its owner."""

    #: The engine's `_status_thread_sleep` (`ruida/controller.py:45`).
    POLL_SECONDS = 0.2
    #: How often a wait for an answer looks again at whether it was stopped.
    SLICE_SECONDS = 0.05

    def __init__(self, session, *, poll_seconds: float = POLL_SECONDS):
        self.session = session
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._readings: dict[bytes, Reading] = {}
        self._stop = threading.Event()
        self._paused = threading.Event()
        #: Held from "not paused?" to "read queued", and by `pause()`: once `pause()`
        #: returns, no read can still be on its way into the session's queue.
        self._gate = threading.Lock()
        self._thread: threading.Thread | None = None
        self._next = 0
        self._card_due = True
        self.polls = self.answers = self.failures = 0

    # -- what the owner sees -----------------------------------------------

    def reading(self, address: bytes) -> Reading | None:
        with self._lock:
            return self._readings.get(bytes(address))

    @property
    def status_word(self) -> int | None:
        reading = self.reading(MEM_MACHINE_STATUS)
        return None if reading is None else reading.value

    @property
    def position(self) -> tuple[int, int] | None:
        """Raw controller micrometres, once both X and Y have been read."""
        x, y = self.reading(MEM_CURRENT_X), self.reading(MEM_CURRENT_Y)
        if x is None or y is None:
            return None
        return (x.value, y.value)

    @property
    def card_id(self) -> int | None:
        reading = self.reading(MEM_CARD_ID)
        return None if reading is None else reading.value

    @property
    def last_answer(self) -> float | None:
        """`time.monotonic()` of the newest answer, or None."""
        with self._lock:
            return max((r.at for r in self._readings.values()), default=None)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.running and self._stop.is_set():
            # A stop that has not finished yet; it ends within one slice.
            self._thread.join(self.SLICE_SECONDS + self.poll_seconds + 1)
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ruida-monitor",
                                        daemon=True)
        self._thread.start()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def pause(self) -> None:
        """Queue no more reads until `resume()`. Returns at once.

        A read already waiting in the session's queue is cancelled by `_wait` within
        `SLICE_SECONDS`; one already on the line finishes in the session, which is why
        `RuidaLink.send_file` waits for `session.busy` to clear before its first packet.
        """
        with self._gate:
            self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def stop(self, timeout: float = 1.0) -> None:
        """Stop polling and wait, bounded, for the thread to end."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        if thread is not None and not thread.is_alive():
            self._thread = None

    # -- the thread --------------------------------------------------------

    def _address(self) -> bytes:
        # The card id before the first round, and before every next round for as
        # long as none has come back; after that only the cycle.
        if self._card_due:
            self._card_due = False
            return MEM_CARD_ID
        address = CYCLE[self._next]
        self._next = (self._next + 1) % len(CYCLE)
        if self._next == 0 and self.card_id is None:
            self._card_due = True
        return address

    def _wait(self, future) -> bytes | None:
        while not (self._stop.is_set() or self._paused.is_set()):
            done, _ = concurrent.futures.wait([future], timeout=self.SLICE_SECONDS)
            if done:
                try:
                    return future.result()
                except (ConnectionError, OSError, concurrent.futures.CancelledError):
                    return None
        future.cancel()
        return None

    def _poll(self) -> None:
        session = self.session
        with self._gate:
            # The engine's rule: only while connected and nothing else is on the line.
            if self._paused.is_set() or not session.connected or session.busy:
                return
            address = self._address()
            try:
                future = session.read_memory(address)
            except ConnectionError:
                return
        self.polls += 1
        reply = self._wait(future)
        if reply is None:
            self.failures += 1
            return
        try:
            value = decode(reply)
        except (IndexError, TypeError):
            self.failures += 1
            return
        with self._lock:
            self._readings[bytes(reply[2:4])] = Reading(value, time.monotonic())
        self.answers += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception:
                log.exception("Ruida status poll failed")
            self._stop.wait(self.poll_seconds)
