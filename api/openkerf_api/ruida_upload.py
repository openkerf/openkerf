"""
A job as a file in the Ruida's memory.

What LightBurn calls "send". The opcodes are in the engine (`ruida/rdjob.py`)
but have no caller there at all — `document_file_upload` (`rdjob.py:2030`) is
dead code, see CLAUDE.md. The conversation *is* written down on the receiving
side, in `ruida/emulator.py`, and that is where this module has it from:

    E8 02              the transfer begins
    E7 01 <name> 00    the name — eight characters, capitals
    <payload>          the job bytes, exactly the contents of a .rd
                       (the tail with SET_FILE_SUM and END_OF_FILE is in there)

What does *not* happen here: starting. That you do on the machine's own panel.
The app stays outside the one handling that burns; there is deliberately no
route in this module that begins a job.
"""

import time

from meerk40t.ruida.rdjob import parse_commands

from .commands import CommandRunner
from .edits import DesignError

#: The way the engine chops its own jobs (`ruida/controller.py:83`,
#: `divide_data_into_queue`, which fills a block up to 1000 bytes and always cuts
#: between two commands, never inside one).
CHUNK = 1000

#: What the machine keeps of a name. The emulator reads characters until the NUL
#: (`ruida/emulator.py:749-753`) and hands back eight capitals when asked for a
#: document's name (`:791`, `name.upper()[:8]`) — that is what a panel shows. We
#: cut and upper-case here, before it goes out, so the screen says the same.
NAME_LENGTH = 8

FILE_TRANSFER = b"\xe8\x02"
SET_FILENAME = b"\xe7\x01"


def machine_name(name: str) -> str:
    """The name as the machine keeps it: printable ASCII, capitals, eight long.

    The space goes too, and not only at the ends: eight characters is little
    enough without spending them on gaps, and a name is already silently cut to
    fit — `MY BOX` becomes `MYBOX`. One sentence about what is left over reads
    better than two about what is left out, and the screen (task 5) shows what
    will actually stand on the panel.
    """
    kept = "".join(c for c in (name or "") if 32 < ord(c) < 127)
    return kept.upper()[:NAME_LENGTH]


def _blocks(payload: bytes) -> list[bytes]:
    """The payload in blocks of at most `CHUNK` bytes, cut between commands.

    Never inside one. A Ruida command starts at a byte >= 0x80 and runs until the
    next such byte (`ruida/rdjob.py:419`, `parse_commands`), and the receiving
    side parses each packet it gets on its own — so a command split across two
    packets is two broken commands, not one whole one. Measured against the
    engine's own emulator with a design of 5462 bytes: cut into six raw
    1000-byte slices it reports 5 `Process Failure`s, one per seam; cut here, 0,
    and the job it builds is identical to the one it builds from the whole
    payload in a single piece. Every real job is over 1000 bytes, so raw slicing
    would have damaged one command per seam in all of them.

    The block is closed *before* the limit rather than on it, so "at most
    `CHUNK` bytes" stays literally true — the engine lets its own block run just
    past 1000 instead (`controller.py:83`), which would work as well, but then
    nothing bounds a packet and the tests could not say what a block is.

    The single exception: a command longer than `CHUNK` all by itself comes out
    whole, in an oversized block. Cutting it is the exact damage this function
    exists to avoid — so it is `upload()` that refuses to *send* such a block,
    before the first byte goes out; see its docstring for what the line does
    with an oversized datagram. Measured on this project's designs the longest
    command is 16 bytes, so this is a guard, not a case anybody meets.
    """
    out: list[bytes] = []
    block = b""
    for command in parse_commands(payload):
        command = bytes(command)
        if block and len(block) + len(command) > CHUNK:
            out.append(block)
            block = b""
        block += command
    if block:
        out.append(block)
    return out


class RuidaUpload:
    """
    The upload conversation: the packets, and putting them on the line.

    The flow control is ours. The engine's is `_data_sender`
    (`ruida/controller.py:118`), a thread that pops its whole queue into
    `RuidaSession.write` and says "File Sent." when the queue is empty — and
    `write` (`ruida/ruidasession.py:167`) gives up after twelve tries at 0.25 s
    on a full queue and falls out of its own loop without raising, carrying the
    TODO "How to inform the calling method a timeout occurred?". Nothing between
    those two ever finds out that a packet did not go. On an engraving job that
    is hundreds of blocks. So: one block at a time, wait for the line to be
    free, and stop **with numbers** when it will not clear.

    What it deliberately does not do is start anything. That happens on the
    machine's own panel.
    """

    #: How long one block may take before we give up on it. Well above the four
    #: seconds at which the engine's own write quietly stops trying, well below
    #: the time in which a person decides the app has hung.
    per_chunk_seconds = 10.0

    #: How often the line is asked whether it is free again while we wait.
    poll_seconds = 0.02

    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    def frames(self, name: str, payload: bytes) -> list[bytes]:
        """The whole conversation as a list of packets, in order."""
        short = machine_name(name)
        if not short:
            raise DesignError(
                "Give the file a name of up to eight letters or digits; that is "
                "what the machine's panel shows.",
                code="upload.needsName",
            )
        out = [FILE_TRANSFER, SET_FILENAME + short.encode("ascii") + b"\x00"]
        out.extend(_blocks(payload))
        return out

    def _device(self):
        device = getattr(self.kernel, "device", None)
        if device is None:
            raise DesignError(
                "There is no active machine to send the file to.",
                code="upload.noMachine",
            )
        return device

    def _session(self):
        """The live session, or a refusal that says nothing has been sent.

        `RuidaSession.connected` (`ruida/ruidasession.py:150`) wants three things
        at once: not shut down, the controller answering, and the transport open.
        Anything less and the very first `write` raises `ConnectionError` — so it
        is asked here, before a file is announced on the panel, rather than found
        out halfway through one.
        """
        session = getattr(self._device(), "active_session", None)
        if session is None or not getattr(session, "connected", False):
            raise DesignError(
                "There is no connection to the machine, so the file cannot be "
                "sent. Connect first; nothing has been sent.",
                code="upload.notConnected",
            )
        return session

    def _write(self, data: bytes) -> None:
        """Out along the way the engine uses itself: `controller.write`.

        Which is `active_session.write` — `RuidaDevice.interface_update` binds
        the one to the other (`ruida/device.py:410`). Going through the
        controller rather than the session directly means we open no second
        channel to the machine and hold no object the engine does not already
        hold.
        """
        self._device().driver.controller.write(data)

    def _interrupted(self, sent: int, chunks: int, why: str, code: str):
        return DesignError(
            f"The machine {why} after {sent} of {chunks} blocks. What is on it "
            f"now is incomplete: delete the file on the panel before you burn "
            f"anything.",
            code=code,
            values={"sent": sent, "chunks": chunks},
        )

    def upload(self, name: str) -> dict:
        """The file to the machine, and left standing there.

        Two things are checked before the first byte goes out, because both
        leave a file on the panel that the user then has to find and delete:

        * **An empty payload.** `frames(name, b"")` is two headers and no
          blocks — a name announced with nothing behind it. `build_job_bytes`
          refuses an empty bed itself, so nothing reaches this today; that is a
          promise about another function, and this is what it costs if it ever
          stops holding.
        * **A block over `CHUNK`.** `_blocks` never cuts inside a command, so a
          single command longer than `CHUNK` gets an oversized block of its own
          (measured: `\x88` plus 1200 bytes gives 1201 and 1). Measured on a
          pair of loopback UDP sockets: a 1201-byte datagram read by a receiver
          calling `recvfrom(1024)` — which is every receiver in the engine,
          `ruida/udp_transport.py:62` among them — arrives as 1024 bytes, with
          no error on either side. With the two checksum bytes UDP packaging
          adds in front (`ruidasession.py:_package`) the real ceiling is 1022,
          so `CHUNK` at 1000 sits under it. Truncating a command silently is the
          exact damage `_blocks` exists to avoid, so an oversized block is
          refused rather than sent; on this project's designs the longest
          command is 16 bytes, so it is a guard, not a case anybody meets.

        The engine's status monitor keeps polling the machine over this same
        session while we send, and its packets land between our blocks. That is
        left alone on purpose: measured against the engine's own emulator, the
        same six blocks with a `GET_SETTING` written between every pair give a
        job of 5455 bytes, byte for byte identical to the clean one, 0 parse
        failures — the poll is answered as realtime and never reaches the file.
        Pausing the monitor would mean taking `_job_lock`, which is released in
        exactly one place in the engine (`ruida/device.py:415`), and that has two
        ways to hang the app for the rest of the session.
        """
        session = self._session()
        payload = self.runner.build_job_bytes()
        if not payload:
            raise DesignError(
                "The job came out empty, so there is nothing to send. Nothing "
                "has been sent.",
                code="upload.emptyFile",
            )
        packets = self.frames(name, payload)
        chunks = len(packets) - 2
        oversized = next((len(p) for p in packets[2:] if len(p) > CHUNK), None)
        if oversized is not None:
            raise DesignError(
                f"This job holds a single command of {oversized} bytes, and a "
                f"block may be at most {CHUNK}. The machine would silently keep "
                f"only the first part of it, so nothing has been sent.",
                code="upload.commandTooLong",
                values={"block": oversized, "limit": CHUNK},
            )
        for index, packet in enumerate(packets):
            sent = max(0, index - 2)
            deadline = time.monotonic() + self.per_chunk_seconds
            while getattr(session, "is_busy", False):
                if time.monotonic() > deadline:
                    raise self._interrupted(
                        sent, chunks, "stopped taking the file", "upload.stalled"
                    )
                time.sleep(self.poll_seconds)
            try:
                self._write(packet)
            except (ConnectionError, OSError) as e:
                raise self._interrupted(
                    sent, chunks, "broke the connection", "upload.interrupted"
                ) from e
        return {"name": machine_name(name), "bytes": len(payload), "chunks": chunks}
