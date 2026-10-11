"""
A Ruida controller on 127.0.0.1, for tests: MeerK40t's own `RuidaEmulator` behind a
real UDP socket.

What a client sees is what the engine's UDP transport expects from a KH-5030:

- **Packet in.** Two bytes of checksum, big-endian, then the swizzled payload. The
  checksum is `sum(swizzled payload) & 0xFFFF` — the engine writes it that way in
  `RuidaSession._package` (`ruida/ruidasession.py:170-172`) and the emulator checks it
  that way in `checksum_write` (`ruida/emulator.py:102-130`). Swizzling is
  `swizzle_byte` with magic 0x88 by default (`ruida/rdjob.py:434-449`; the device's
  default, `ruida/device.py`, choice "magic").
- **Packet out.** Every answer is swizzled, nothing is checksummed. A good checksum is
  answered with ACK `0xCC`, a bad one with NAK `0xCF` (`ruida/rdjob.py:126-129`;
  `ruida/emulator.py:119-126`) — both one byte before swizzling. A memory read
  (`DA 00 <mem:2>`) is answered with a *second* datagram after the ACK: `DA 01 <mem:2>
  <value:5>`, nine bytes (`ruida/emulator.py:661-685`), which is exactly the length and
  prefix the engine's session waits for (`ruida/ruidasession.py:242,262-263`).
- **Size.** The emulator reads at most 1470 payload bytes (`sent_data[2:1472]`,
  `ruida/emulator.py:112`); a longer packet is checksummed over the truncated part and
  so is NAKed. The engine cuts files into chunks of a little over 1000 bytes
  (`ruida/controller.py:84-95`) and reads answers with `recvfrom(1024)`
  (`ruida/udp_transport.py:67`).
- **Ports.** The engine sends to 50200 and listens on 40200, both fixed
  (`ruida/udp_transport.py:18-19`), and it *drops* any datagram that does not come from
  `(controller address, 50200)` (`:68`). So this peer answers from the very socket it
  listens on. Where it answers *to* is `reply_port`: `None` (the default) answers to the
  source address of the packet — for the engine, whose socket is bound to 40200, that is
  40200 — and a number answers to that port on the sender's host instead. Which of the
  two a real controller does is not something the engine's code can tell us; the packet
  capture of phase 0 can.

The peer records every datagram it receives (`received`) and every answer it sends
(`replies`), and can be told to misbehave once: `nak_next()` rejects the next packet
without processing it, `drop_ack_next()` processes the next packet but loses its ACK
(any reply data still goes out), and `ignore_next()` loses the next packet altogether.
`swallow_replies(pattern)` stands in for a second program on the controller: memory
reads are acknowledged as ever, and for each read whose turn in the cycled `pattern` is
`True` the answer after the ACK is lost (recorded with `sent=False`).

Nothing the emulator decodes reaches a machine: it is given a stand-in device whose
driver records calls and whose spooler takes jobs and runs none. `status()` on that
driver is what the emulator answers a status or position read from
(`ruida/emulator.py:1361-1431`), so `state` and `position_um` set what a poll sees, and
`memory` overrides any address outright.

    with ruida_peer() as peer:
        sock.sendto(packet, ("127.0.0.1", peer.send_port))
"""

from __future__ import annotations

import contextlib
import socket
import threading
from dataclasses import dataclass, field

from meerk40t.core.units import UNITS_PER_uM
from meerk40t.ruida.emulator import RuidaEmulator
from meerk40t.ruida.rdjob import ACK, NAK, parse_commands, parse_mem
from meerk40t.svgelements import Matrix

#: The ports a real controller uses (`ruida/udp_transport.py:18-19`). Tests use
#: ephemeral ones; a transport under test defaults to these.
RUIDA_SEND_PORT = 50200
RUIDA_REPLY_PORT = 40200


@dataclass
class Received:
    """One datagram as it arrived, and what the peer did with it."""

    source: tuple
    packet: bytes
    #: "ack", "nak" (bad checksum), "nak-injected", "ack-dropped", "ignored", "short".
    action: str
    checksum_ok: bool | None = None
    #: The payload unswizzled with the magic in force when it arrived.
    payload: bytes = b""
    commands: list = field(default_factory=list)


@dataclass
class Reply:
    """One answer the peer put on the wire (or dropped), unswizzled."""

    destination: tuple
    data: bytes
    sent: bool = True


class _StandInDriver:
    """Answers to anything and does nothing; `status()` is what a poll reads."""

    def __init__(self, peer):
        self._peer = peer
        self.calls = []

    def status(self):
        # The emulator turns this back into micrometres with `int(units / scale)`
        # (`ruida/emulator.py:1417-1431`), which truncates: 123000 um came back as
        # 122999. Half a micrometre away from zero makes the truncation land on it.
        x, y = (v + (0.5 if v >= 0 else -0.5) for v in self._peer.position_um)
        return (x * UNITS_PER_uM, y * UNITS_PER_uM), self._peer.state, self._peer.state

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))

        return record


class _InertSpooler:
    """Takes the jobs the emulator hands on (`ruida/emulator.py:158-159`) and runs none."""

    def __init__(self):
        self.jobs = 0

    def send(self, job, prevent_duplicate=False):
        self.jobs += 1


class _StandInDevice:
    def __init__(self, peer):
        self.driver = _StandInDriver(peer)
        self.spooler = _InertSpooler()

    @property
    def current(self):
        return self.driver.status()[0]


class RuidaPeer:
    """The emulator behind a UDP socket. Use `ruida_peer()` rather than this directly."""

    def __init__(self, host="127.0.0.1", send_port=0, reply_port=None, magic=0x88):
        self.host = host
        self.reply_port = reply_port
        #: What the stand-in driver reports: "idle" (22), "busy" (21) or "hold" (23)
        #: in the emulator's own mapping (`ruida/emulator.py:1361-1369`).
        self.state = "idle"
        self.position_um = (0, 0)
        #: Overrides, by the engine's 2-byte address constant (`MEM_MACHINE_STATUS`,
        #: ...), checked before the emulator's own `mem_lookup`.
        self.memory: dict[bytes, int] = {}
        self.received: list[Received] = []
        self.replies: list[Reply] = []

        self._nak = self._drop_ack = self._ignore = 0
        self._swallow: tuple[bool, ...] = ()
        self._reads = 0
        self._changed = threading.Condition()
        self._current = None

        self.device = _StandInDevice(self)
        self.emulator = RuidaEmulator(self.device, Matrix())
        if magic != self.emulator.magic:
            self.emulator._set_magic(magic)
        self.emulator.reply = self._send_reply
        original = self.emulator.mem_lookup

        def mem_lookup(mem):
            for address, value in self.memory.items():
                if parse_mem(address) == mem:
                    return "Override", value
            return original(mem)

        self.emulator.mem_lookup = mem_lookup

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((host, send_port))
        self._socket.settimeout(0.02)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="ruida-peer", daemon=True)

    # ------------------------------------------------------------------ control

    @property
    def send_port(self) -> int:
        """The port the peer listens on — 50200 on a real controller."""
        return self._socket.getsockname()[1]

    @property
    def thread(self):
        return self._thread

    def nak_next(self, count=1):
        """Answer the next `count` packets with NAK and do not process them."""
        with self._changed:
            self._nak += count

    def drop_ack_next(self, count=1):
        """Process the next `count` packets but do not send their ACK."""
        with self._changed:
            self._drop_ack += count

    def ignore_next(self, count=1):
        """Lose the next `count` packets: no processing, no answer."""
        with self._changed:
            self._ignore += count

    def swallow_replies(self, pattern=()):
        """ACK every memory read but lose the answer where the cycled `pattern` says
        `True`; `()` answers everything again."""
        with self._changed:
            self._swallow = tuple(bool(p) for p in pattern)
            self._reads = 0

    def wait_for(self, count, timeout=2.0) -> list[Received]:
        """Block until at least `count` datagrams have arrived; return them."""
        with self._changed:
            if not self._changed.wait_for(lambda: len(self.received) >= count, timeout):
                raise TimeoutError(f"{len(self.received)} of {count} packets arrived")
            return list(self.received)

    def start(self):
        self._thread.start()
        return self

    def close(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(2.0)
        self._socket.close()

    # ------------------------------------------------------------------ the wire

    def _serve(self):
        while not self._stop.is_set():
            try:
                packet, source = self._socket.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                continue
            except OSError:
                return
            self._handle(packet, source)

    def _handle(self, packet, source):
        destination = source if self.reply_port is None else (source[0], self.reply_port)
        with self._changed:
            if self._ignore:
                self._ignore -= 1
                self._record(Received(source, packet, "ignored"))
                return
            injected_nak = bool(self._nak)
            if injected_nak:
                self._nak -= 1
            drop_ack = not injected_nak and bool(self._drop_ack)
            if drop_ack:
                self._drop_ack -= 1
        if len(packet) < 2:
            self._record(Received(source, packet, "short"))
            return
        body = packet[2:1472]
        checksum_ok = int.from_bytes(packet[:2], "big") == sum(body) & 0xFFFF
        payload = self.emulator.unswizzle(body)
        entry = Received(source, packet, "ack" if checksum_ok else "nak", checksum_ok,
                         payload, list(parse_commands(payload)))
        if injected_nak:
            entry.action = "nak-injected"
            self._record(entry)
            self._send_reply(self.emulator.swizzle(NAK), destination=destination)
            return
        if drop_ack and checksum_ok:
            entry.action = "ack-dropped"
        swallow = False
        if checksum_ok and payload[:2] == bytes([0xDA, 0x00]):
            with self._changed:
                if self._swallow:
                    swallow = self._swallow[self._reads % len(self._swallow)]
                    self._reads += 1
        self._record(entry)
        self._current = {"destination": destination, "drop_ack": drop_ack, "first": True,
                         "swallow": swallow}
        try:
            self.emulator.checksum_write(packet)
        finally:
            self._current = None

    def _send_reply(self, swizzled, destination=None):
        current = self._current
        if destination is None:
            destination = current["destination"]
        data = self.emulator.unswizzle(swizzled)
        sent = True
        if current is not None:
            if current["first"] and current["drop_ack"] and data == ACK:
                sent = False
            if not current["first"] and current.get("swallow"):
                sent = False
            current["first"] = False
        if sent:
            self._socket.sendto(swizzled, destination)
        with self._changed:
            self.replies.append(Reply(destination, data, sent))
            self._changed.notify_all()

    def _record(self, entry):
        with self._changed:
            self.received.append(entry)
            self._changed.notify_all()


@contextlib.contextmanager
def ruida_peer(host="127.0.0.1", send_port=0, reply_port=None, magic=0x88):
    """
    A running `RuidaPeer`; closed, thread joined and socket shut, on the way out.

    `send_port=0` picks a free port (read it back from `peer.send_port`); pass 50200 to
    stand where a real controller stands. `reply_port=None` answers to the sender's own
    address and port; a number answers to that port on the sender's host.
    """
    peer = RuidaPeer(host=host, send_port=send_port, reply_port=reply_port, magic=magic)
    peer.start()
    try:
        yield peer
    finally:
        peer.close()
