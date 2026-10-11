"""
One conversation with one Ruida: a worker that owns the line, and a Future per packet.

The semantics are the session patch's (`deploy/patches/ruida-session.patch`,
`ruida/ruidasession.py` once applied), rewritten without the engine's kernel,
channels or signals; `test_ruida_session_own.py` ports its thirty tests.

- **One worker owns every byte of transport I/O**, opening and closing
  included. Callers only queue and wait; `open()` from four threads at once still
  leaves one thread that ever touched the socket.
- **Every write returns a `concurrent.futures.Future`.** Over UDP it completes on
  the controller's ACK; a memory read (exactly DA 00 <address>) completes only
  when the matching nine-byte answer has also come in, and the answer is its
  result. Anything else completes with `None`.
- **A NAK is answered by sending the same packet again**, a bounded number of
  times, and only that packet.
- **A missing ACK is never answered by sending again.** No ACK does not mean the
  controller rejected the bytes, only that we do not know; a file block sent
  twice is a damaged file. So it fails that packet *and everything queued
  behind it*, bumps the generation and reconnects, and the caller decides.
- **An acknowledged read that is not answered fails only that read.** The ACK
  proves the line; the answer is a second datagram the controller may leave out.
  Measured on a KH-5030 (card id 0x0628414A10, over UDP): the first memory read on
  a fresh socket was acknowledged in 98–166 ms and never answered, every read after
  it was answered 29–33 ms after its ACK. Treating that silence as a dead line
  closed the socket, and the next read was a first read on a fresh socket again —
  12 probes and 11 unanswered reads in 20 s, not one status word. So it is a
  `TimeoutError` on that Future, no new generation, no reconnect.
- **The generation pins a transfer.** It moves on every close, shutdown and
  failure; a write that names an older one is refused, so a reconnect can never
  quietly carry on with the second half of a file.
- **`close()` stays closed** until somebody calls `open()`. Nothing in here
  reconnects on its own after an explicit close.
- **Two lanes.** `write(..., priority=True)` goes before every normal packet that
  has not gone out yet — a pause or stop must not wait behind the rest of a
  streamed file. The packet already on the line still finishes first: the
  protocol has one packet in flight at a time, and a Ruida ACK carries no
  transaction number to tell two apart.

What is *not* proved by any of this: exactly-once execution on a physical
controller. A very late duplicate ACK cannot be told from a fresh one. The worker
throws away what is already waiting before each new packet, which handles the
answer that arrives between two transactions, not one still on its way.
"""

import collections
import logging
import threading
import time
from concurrent.futures import Future, InvalidStateError
from typing import Callable

from . import framing
from .transport import TransportError, TransportTimeout

log = logging.getLogger(__name__)

#: The probe that proves somebody answers, as the engine sends it over UDP
#: (`ruida/ruidasession.py:298`).
PROBE = bytes([framing.ENQ])


class _Interrupted(ConnectionError):
    """The generation moved under the worker; whoever moved it failed the queue."""


class _Unanswered(Exception):
    """A read the controller acknowledged and did not answer; the line is fine."""


class RuidaSession:
    """The queue, the generation and the worker for one controller."""

    #: How long the worker waits for an ACK and, for a memory read, its answer,
    #: from the first send of a packet: the engine's 0.25 s × 4 tries
    #: (`ruida/ruidasession.py:59-60,228`). The engine stretches this to 40 s for
    #: a physical home (`ruida/controller.py:47`); here that is `reply_seconds`.
    REPLY_SECONDS = 1.0
    #: How long one wait on the socket lasts before the worker looks again at
    #: whether it was closed: the engine's 0.25 s, so `close()` waits that plus a
    #: second (`ruida/ruidasession.py:97-98`).
    RECEIVE_SECONDS = 0.25
    #: Sends after a NAK before the packet fails: the engine fails on the fourth
    #: NAK with its default four tries (`ruida/ruidasession.py:255-257`).
    NAK_RESENDS = 3
    #: The engine's queue bound (`ruida/ruidasession.py:53`, `2 ** 18`).
    QUEUE_SIZE = 2 ** 18
    #: Realtime commands are few; a separate small bound means a full file queue
    #: can never refuse a stop.
    PRIORITY_SIZE = 64
    #: The pause before reconnecting after a failure (`ruida/ruidasession.py:332`).
    RETRY_SECONDS = 0.5

    def __init__(self, transport_factory: Callable[[], object], *,
                 magic: int = framing.DEFAULT_MAGIC,
                 reply_seconds: float = REPLY_SECONDS,
                 receive_seconds: float = RECEIVE_SECONDS,
                 nak_resends: int = NAK_RESENDS,
                 queue_size: int = QUEUE_SIZE,
                 priority_size: int = PRIORITY_SIZE,
                 retry_seconds: float = RETRY_SECONDS,
                 on_state: Callable[[str, str], None] | None = None):
        self._factory = transport_factory
        self._swizzler = framing.Swizzler(magic)
        self.reply_seconds = reply_seconds
        self.receive_seconds = receive_seconds
        self.nak_resends = nak_resends
        self.queue_size = queue_size
        self.priority_size = priority_size
        self.retry_seconds = retry_seconds
        self._on_state = on_state

        self._cond = threading.Condition(threading.RLock())
        self._normal: collections.deque = collections.deque()
        self._priority: collections.deque = collections.deque()
        self._pending: set[Future] = set()
        self._transport = None
        self._worker: threading.Thread | None = None
        self._worker_done = False
        self._enabled = False
        self._shutdown = False
        self._responding = False
        self._generation = 0
        self._ack_pending = self._reply_pending = False
        self._reported: tuple[str, str] | None = None
        self.detail = ""
        self.sends = self.acks = self.naks = self.replies = self.probes = 0
        self.dropped = self.drained = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()

    # -- what callers see --------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._enabled and not self._shutdown and self._responding

    @property
    def connecting(self) -> bool:
        return self._enabled and not self._shutdown and not self._responding

    @property
    def state(self) -> str:
        """`'connected'`, `'connecting'` or `'closed'`."""
        with self._cond:
            if self.connected:
                return "connected"
            return "connecting" if self.connecting else "closed"

    @property
    def generation(self) -> int:
        with self._cond:
            return self._generation

    @property
    def busy(self) -> bool:
        """Anything queued or on the line, with no gap before its first send."""
        with self._cond:
            return bool(self._pending)

    @property
    def queued(self) -> int:
        """Packets waiting in either lane, not counting the one on the line."""
        with self._cond:
            return len(self._normal) + len(self._priority)

    def open(self) -> None:
        """Ask for a connection; the worker makes it. Returns at once."""
        with self._cond:
            if self._shutdown:
                raise ConnectionError("The Ruida session has shut down.")
            self._enabled = True
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="ruida-session", daemon=True)
                self._worker.start()
            self._cond.notify_all()

    def close(self) -> None:
        """Disconnect and stay disconnected; fails everything not yet confirmed."""
        with self._cond:
            self._enabled = False
            self._generation += 1
            self._responding = False
            self._fail_pending(ConnectionError("The connection to the Ruida was closed."))
            self._cond.notify_all()
            worker = self._worker
            if worker is not None and worker is not threading.current_thread():
                self._cond.wait_for(
                    lambda: self._transport is None or self._worker_done,
                    timeout=self.receive_seconds + 1)
        self._report()

    def shutdown(self) -> None:
        """Close for good and wait, bounded, for the worker to end."""
        with self._cond:
            self._shutdown = True
            self._enabled = False
            self._generation += 1
            self._responding = False
            self._fail_pending(ConnectionError("The Ruida session shut down."))
            self._cond.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(self.receive_seconds + 1)

    def write(self, data: bytes, *, generation: int | None = None,
              priority: bool = False) -> Future:
        """Queue one packet's payload and return its completion.

        Refused at once — `ConnectionError`, nothing queued — when the line is
        not up, when `generation` names an earlier connection, or when the lane
        is full. The payload goes out as one datagram; cut a file with
        `framing.split` first.
        """
        with self._cond:
            if not self.connected:
                raise ConnectionError("Not connected to the Ruida controller.")
            if generation is not None and generation != self._generation:
                raise ConnectionError(
                    "The connection to the Ruida changed during the transfer.")
            lane, room = ((self._priority, self.priority_size) if priority
                          else (self._normal, self.queue_size))
            if len(lane) >= room:
                raise ConnectionError("The Ruida send queue is full.")
            future: Future = Future()
            lane.append((bytes(data), future, self._generation))
            self._pending.add(future)
            self._cond.notify_all()
            return future

    def read_memory(self, address: bytes, *, priority: bool = False) -> Future:
        """A memory read; the Future's result is the nine-byte answer."""
        return self.write(framing.GET_SETTING + bytes(address), priority=priority)

    # -- the worker --------------------------------------------------------

    def _check(self, generation: int) -> None:
        if self._shutdown or not self._enabled or generation != self._generation:
            raise _Interrupted("The Ruida connection was interrupted.")

    def _fail_pending(self, error: Exception) -> None:
        # Called with _cond held, so no writer can slip in between.
        for future in tuple(self._pending):
            if not future.done():
                try:
                    future.set_exception(error)
                except InvalidStateError:
                    # cancel() may win between done() and set_exception().
                    if not future.cancelled():
                        raise
        self._pending.clear()
        self._normal.clear()
        self._priority.clear()

    def _report(self) -> None:
        with self._cond:
            now = (self.state, self.detail)
            if now == self._reported:
                return
            self._reported = now
        if self._on_state is not None:
            try:
                self._on_state(*now)
            except Exception:
                log.exception("Ruida state listener failed")

    def _close_transport(self) -> None:
        transport = self._transport
        if transport is not None:
            try:
                transport.close()
            except OSError:
                pass
        with self._cond:
            self._transport = None
            self._responding = False
            self._cond.notify_all()

    def _connect(self, generation: int) -> None:
        self._report()
        with self._cond:
            self._check(generation)
            if self._transport is None:
                self._transport = self._factory()
        self._transport.open()
        self._check(generation)
        self.probes += 1
        self._exchange(PROBE, generation)
        with self._cond:
            self._check(generation)
            self._responding = True
            self.detail = ""
            self._cond.notify_all()
        self._report()

    def _next(self):
        with self._cond:
            lane = self._priority or self._normal
            if not lane:
                self._cond.wait(self.receive_seconds)
                return None
            item = lane.popleft()
            if not item[1].set_running_or_notify_cancel():
                self._pending.discard(item[1])
                return None
            return item

    def _send(self, packet: bytes, generation: int) -> None:
        with self._cond:
            self._check(generation)
            self._transport.send(packet)
            self.sends += 1

    def _exchange(self, payload: bytes, generation: int) -> bytes | None:
        packet = framing.frame(payload, self._swizzler)
        address = framing.memory_address(payload)
        ack, nak = bytes([framing.ACK]), bytes([framing.NAK])
        self.drained += self._transport.drain()
        self._ack_pending = True
        self._reply_pending = address is not None
        deadline = time.monotonic() + self.reply_seconds
        naks = 0
        reply = None
        try:
            self._send(packet, generation)
            while self._ack_pending or self._reply_pending:
                self._check(generation)
                left = deadline - time.monotonic()
                if left <= 0:
                    if not self._ack_pending:
                        raise _Unanswered(
                            "The Ruida acknowledged the read but did not answer it.")
                    raise ConnectionError(
                        "The Ruida did not acknowledge or answer in time.")
                try:
                    raw = self._transport.receive(min(left, self.receive_seconds))
                except TransportTimeout:
                    continue
                self._check(generation)
                data = self._swizzler.unswizzle(raw)
                if data[:1] == ack:
                    if self._ack_pending:
                        self.acks += 1
                        self._ack_pending = False
                    data = data[1:]
                    if not data:
                        continue
                if data == nak:
                    self.naks += 1
                    naks += 1
                    if not self._ack_pending or naks > self.nak_resends:
                        raise ConnectionError("The Ruida rejected the packet.")
                    self._send(packet, generation)
                elif address is not None and framing.is_reply_to(data, address):
                    reply = data
                    self._reply_pending = False
                else:
                    self.dropped += 1
        finally:
            self._ack_pending = self._reply_pending = False
        if reply is not None:
            self.replies += 1
        return reply

    def _fail(self, error: Exception) -> None:
        with self._cond:
            self._responding = False
            self._generation += 1
            self.detail = str(error)
            self._fail_pending(ConnectionError(str(error)))
        self._close_transport()
        self._report()
        with self._cond:
            if self._enabled and not self._shutdown:
                self._cond.wait(self.retry_seconds)

    def _run(self) -> None:
        generation = None
        try:
            while True:
                with self._cond:
                    if self._shutdown:
                        break
                    reset = generation != self._generation
                    generation = self._generation
                    enabled = self._enabled
                if reset or not enabled:
                    self._close_transport()
                if not enabled:
                    with self._cond:
                        if not self._enabled and not self._shutdown:
                            self._cond.wait()
                    continue
                try:
                    if not self._responding:
                        self._connect(generation)
                        continue
                    item = self._next()
                    if item is None:
                        continue
                    payload, future, queued = item
                    reply = self._exchange(payload, queued)
                    with self._cond:
                        self._check(queued)
                        self._pending.discard(future)
                        if not future.done():
                            future.set_result(reply)
                        self._cond.notify_all()
                except _Interrupted:
                    continue
                except _Unanswered as error:
                    with self._cond:
                        self._pending.discard(future)
                        if not future.done():
                            future.set_exception(TimeoutError(str(error)))
                        self._cond.notify_all()
                except (TransportError, OSError, ConnectionError) as error:
                    self._fail(error)
        finally:
            self._close_transport()
            with self._cond:
                self._worker_done = True
                self._cond.notify_all()
