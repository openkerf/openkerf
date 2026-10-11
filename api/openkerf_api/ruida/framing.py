"""
What goes on the wire between us and a Ruida, as pure functions.

Nothing here opens a socket or starts a thread. The bytes are the engine's: the
swizzle table is `rdjob.swizzles_lut` itself, and the packet is the one
`RuidaSession._package` builds (`ruida/ruidasession.py:170-172` with the
session patch applied): the swizzled payload behind a two-byte big-endian sum of
those swizzled bytes, modulo 0x10000. `test_ruida_session_own.py` runs the
engine's own code on the same payloads and compares byte for byte.

Everything the controller says back is swizzled too, the one-byte answers
included. With the engine's default magic 0x88 (`ruida/device.py:274`) an ACK
(0xCC) arrives as 0xC6 and a NAK (0xCF) as 0x48 — measured by feeding packets to
the engine's emulator, which answers a valid checksum with 0xCC and a broken one
with 0xCF (`ruida/emulator.py:119-126`).
"""

import struct

from meerk40t.ruida.rdjob import parse_commands, swizzles_lut

#: The engine's default for a Ruida (`ruida/device.py:274`). `rdjob.RDJob` itself
#: defaults to 0x11 ("for the 634XG"), but the driver overwrites that with the
#: device's setting (`ruida/driver.py:45`).
DEFAULT_MAGIC = 0x88

#: The one-byte answers, unswizzled (`ruida/rdjob.py:126-129`).
ACK = 0xCC
NAK = 0xCF
ERR = 0xCD
ENQ = 0xCE

#: A memory read and its answer (`ruida/rdjob.py:169`): we send DA 00 <address>
#: and the controller answers DA 01 <address> <five value bytes>, nine in all —
#: measured on the emulator for the status word, `da0104000000000016`.
GET_SETTING = b"\xda\x00"
SETTING_REPLY = b"\xda\x01"
REPLY_LENGTH = 9

#: The largest block we cut a payload into. The engine's own job sender fills a
#: block until it passes 1000 bytes (`ruida/controller.py:84-95`), so its blocks
#: run a command past that; `ruida_upload.CHUNK` closes the block before the limit
#: instead, and so do we. The hard ceiling is higher: the emulator reads at most
#: 1470 bytes after the checksum (`ruida/emulator.py:112`, `sent_data[2:1472]`),
#: which is a 1500-byte Ethernet frame less the IP and UDP headers.
MAX_PAYLOAD = 1000
DATAGRAM_LIMIT = 1472


class Swizzler:
    """Both directions of one magic number, as `bytes.translate` tables."""

    def __init__(self, magic: int = DEFAULT_MAGIC):
        forward, backward = swizzles_lut(magic)
        self.magic = magic
        self._forward = bytes(forward)
        self._backward = bytes(backward)

    def swizzle(self, data: bytes) -> bytes:
        return bytes(data).translate(self._forward)

    def unswizzle(self, data: bytes) -> bytes:
        return bytes(data).translate(self._backward)


def checksum(swizzled: bytes) -> int:
    """The sum the controller checks: of the swizzled bytes, not of the payload."""
    return sum(swizzled) & 0xFFFF


def frame(payload: bytes, swizzler: Swizzler) -> bytes:
    """One UDP datagram for `payload`."""
    data = swizzler.swizzle(payload)
    return struct.pack(">H", checksum(data)) + data


def unframe(packet: bytes, swizzler: Swizzler) -> bytes | None:
    """The payload of a datagram, or None when its checksum does not hold.

    The receiving side of `frame`, for test peers; the controller does this.
    """
    if len(packet) < 2:
        return None
    data = packet[2:]
    if struct.unpack(">H", packet[:2])[0] != checksum(data):
        return None
    return swizzler.unswizzle(data)


def split(payload: bytes, limit: int = MAX_PAYLOAD) -> list[bytes]:
    """The payload in blocks of at most `limit` bytes, cut between commands.

    The same rule as `ruida_upload._blocks`, and for the same reason: a command
    starts at a byte >= 0x80 (`ruida/rdjob.py:419`), the controller parses each
    packet on its own, and a command cut in two is two broken commands. A single
    command longer than `limit` comes out whole, in an oversized block; whoever
    sends it decides whether to refuse it.
    """
    out: list[bytes] = []
    block = b""
    for command in parse_commands(payload):
        command = bytes(command)
        if block and len(block) + len(command) > limit:
            out.append(block)
            block = b""
        block += command
    if block:
        out.append(block)
    return out


#: The engine's threshold for a job block (`ruida/controller.py:88`, `total > 1000`).
JOB_THRESHOLD = 1000


def job_blocks(payload: bytes) -> list[bytes]:
    """A job file in the blocks the engine streams it in, byte for byte.

    `RuidaController.divide_data_into_queue` (`ruida/controller.py:84-95`), on the
    commands `parse_commands` cuts — which, measured on the four golden files, are
    exactly the entries of the engine's `RDJob.buffer` (171, 850, 70 and 59 of them,
    one `write_command` per command). Its rule, reproduced with its quirk: it adds
    each command's length to a running total; when the total passes 1000 the block
    closes *before* that command, which opens the next block — and the total restarts
    at 0, not at that command's length. So the first block is at most 1000 bytes and
    every later one may run over by the length of its first command: the golden
    raster file goes out as 1000, 1003, 1003 and 619 bytes, where `split` would make
    1000, 1000, 995 and 630.

    `split` keeps `ruida_upload`'s own rule for uploads; a job goes out as the engine
    sent it. The one place we part from the engine: a first command over 1000 bytes
    would make it queue an empty block (`get_contents(0, 0)`), which we leave out.
    """
    commands = [bytes(command) for command in parse_commands(payload)]
    out: list[bytes] = []
    last = total = 0
    for index, command in enumerate(commands):
        total += len(command)
        if total > JOB_THRESHOLD:
            out.append(b"".join(commands[last:index]))
            last, total = index, 0
    if last != len(commands):
        out.append(b"".join(commands[last:]))
    return [block for block in out if block]


def memory_address(payload: bytes) -> bytes | None:
    """The two-byte address when `payload` is a memory read, else None.

    Only an exact four-byte DA 00 <address> counts, as in the engine
    (`ruida/ruidasession.py:225`); a read glued to other commands is just data.
    """
    if len(payload) == 4 and payload.startswith(GET_SETTING):
        return payload[2:4]
    return None


def is_reply_to(data: bytes, address: bytes) -> bool:
    """Whether an unswizzled datagram is the answer to a read of `address`."""
    return len(data) == REPLY_LENGTH and data[:4] == SETTING_REPLY + address
