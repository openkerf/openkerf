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

from concurrent.futures import Future, TimeoutError as ReceiptTimeout
import time
from contextlib import contextmanager

from meerk40t.ruida.rdjob import parse_commands
from meerk40t.ruida.ruidatransport import TransportError, TransportTimeout

from .busy import sending_a_file, the_line_is_in_use
from .commands import CommandRunner
from .edits import DesignError
from .status import _attr

#: The way the engine chops its own jobs (`ruida/controller.py:83`,
#: `divide_data_into_queue`, which fills a block up to 1000 bytes and always cuts
#: between two commands, never inside one).
CHUNK = 1000

#: What the machine keeps of a name. The emulator reads characters until the NUL
#: (`ruida/emulator.py:749-753`) and hands back eight capitals when asked for a
#: document's name (`:791`, `name.upper()[:8]`) — that is what a panel shows. We
#: cut and upper-case here, before it goes out, so the screen says the same.
NAME_LENGTH = 8

#: The characters a name may be made of. Written out rather than asked of
#: `str.isalnum()`, which is true of é, of 日 and of the Arabic-Indic ٣ — none of
#: which a panel has a glyph for.
NAME_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)

FILE_TRANSFER = b"\xe8\x02"
SET_FILENAME = b"\xe7\x01"


def machine_name(name: str) -> str:
    """The name as the machine keeps it: letters and digits, capitals, eight long.

    Letters and digits and nothing else, because that is what the refusal beside
    this promises — "a name of up to eight letters or digits" — and a filter that
    let `---` through made that sentence untrue: the name went to the panel as
    `---`. A hyphen that falls away while you are typing it is visible and one
    keystroke to undo; a sentence that is wrong is neither.

    The space goes with it, and not only at the ends: eight characters is little
    enough without spending them on gaps, and a name is already silently cut to
    fit — `MY BOX` becomes `MYBOX`. One sentence about what is left over reads
    better than two about what is left out, and the screen shows what will
    actually stand on the panel (`machineName` in `frontend/src/lib/api.ts`, run
    against this function in `frontend/tests/upload-name.test.ts`).
    """
    kept = "".join(c for c in (name or "") if c in NAME_CHARACTERS)
    return kept.upper()[:NAME_LENGTH]


def _checked_name(name: str) -> str:
    """`machine_name`, and a refusal when nothing is left of it.

    Here rather than inside `frames()` because both `frames()` and `upload()`
    need the answer, and `upload()` needs it *first*: a name of nothing but
    spaces on a design that builds no bytes used to come back as
    `upload.emptyFile`, since the payload was built before anything looked at
    the name. Both are true, but the name is the one the caller can fix on the
    spot.
    """
    short = machine_name(name)
    if not short:
        raise DesignError(
            "Give the file a name of up to eight letters or digits; that is "
            "what the machine's panel shows.",
            code="upload.needsName",
        )
    return short


def _blocks(payload: bytes) -> list[bytes]:
    """The payload in blocks of at most `CHUNK` bytes, cut between commands.

    Never inside one. A Ruida command starts at a byte >= 0x80 and runs until the
    next such byte (`ruida/rdjob.py:419`, `parse_commands`), and the receiving
    side parses each packet it gets on its own — so a command split across two
    packets is two broken commands, not one whole one. Measured against the
    engine's own emulator with a design of 5462 bytes (that design does not
    always build to the same length — see `a_design_over_one_block` in the
    tests): cut into six raw
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
    """Send one file without starting it; wait for each packet's own completion."""

    per_chunk_seconds = 10.0
    poll_seconds = 0.02
    # A bounded wait for the worker to reconnect before any upload begins.
    line_gap_seconds = 8.0
    line_claim_seconds = 2.0

    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    def frames(self, name: str, payload: bytes) -> list[bytes]:
        short = _checked_name(name)
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
        device = self._device()
        deadline = time.monotonic() + self.line_gap_seconds
        while True:
            session = getattr(device, "active_session", None)
            if session is None:
                break
            if getattr(session, "connected", False):
                return session
            if time.monotonic() > deadline:
                break
            time.sleep(self.poll_seconds)
        raise DesignError(
            "There is no connection to the machine, so the file cannot be "
            "sent. Connect first; nothing has been sent.",
            code="upload.notConnected",
        )

    def _write(self, data: bytes, *, session, generation) -> Future:
        return session.write(data, expected_generation=generation)

    def _interrupted(
        self, sent: int, chunks: int, why: str, code: str, announced: bool
    ):
        if sent == 0 and not announced:
            what = (
                "Nothing had gone out, so there is no file on the panel to "
                "clean up; send it again."
            )
        elif sent == 0:
            what = (
                "The name went out but no part of the job followed it, so the "
                "panel may be showing an empty file under that name: delete it "
                "there if it is. None of the job itself was sent."
            )
        elif sent < chunks:
            what = (
                "What is on it now is incomplete: delete the file on the panel "
                "before you burn anything."
            )
        else:
            what = (
                "Every block went out, including the one that closes the file, "
                "but the last one was not acknowledged. The file on the panel "
                "may be whole and may be missing its end: look at it there, and "
                "send it again if you are in any doubt."
            )
        return DesignError(
            f"The machine {why} after {sent} of {chunks} blocks. {what}",
            code=code,
            values={"sent": sent, "chunks": chunks, "announced": announced},
        )

    def _line_is_busy(self, session) -> bool:
        # Admission only. Completion is proved by the Future, never this snapshot.
        pending = getattr(session, "send_q", None)
        return (pending is not None and not pending.empty()) or bool(session.is_busy)

    @contextmanager
    def _the_line_to_ourselves(self, session):
        """Pause new status polls; let existing commands finish without deleting them."""
        controller = _attr(_attr(self._device(), "driver"), "controller")
        lock = _attr(controller, "_job_lock")
        if lock is None:
            yield
            return
        if not lock.acquire(timeout=self.line_claim_seconds):
            raise DesignError(
                "This machine is already being sent something on this line. Wait "
                "until that is done and press again; nothing has been sent.",
                code="upload.lineInUse",
            )
        try:
            yield
        finally:
            lock.release()

    def _wait_for_the_line(
        self, session, sent: int, chunks: int, announced: bool
    ) -> None:
        deadline = time.monotonic() + self.per_chunk_seconds
        gap_started = None
        while True:
            now = time.monotonic()
            if not getattr(session, "connected", True):
                if sent or announced or now > deadline:
                    raise self._interrupted(
                        sent, chunks, "stopped answering",
                        code="upload.interrupted", announced=announced,
                    )
                if gap_started is None:
                    gap_started = now
                elif now - gap_started > self.line_gap_seconds:
                    raise self._interrupted(
                        sent, chunks, "stopped answering",
                        code="upload.interrupted", announced=announced,
                    )
                time.sleep(self.poll_seconds)
                continue
            if gap_started is not None:
                gap_started = None
            if not self._line_is_busy(session):
                return
            if now > deadline:
                raise self._interrupted(
                    sent, chunks, "stopped taking the file",
                    code="upload.stalled", announced=announced,
                )
            time.sleep(self.poll_seconds)

    def upload(self, name: str) -> dict:
        with sending_a_file(self.kernel) as claimed:
            if not claimed:
                raise DesignError(
                    "This machine is already being sent a file. Wait until that "
                    "one is done and press again; nothing has been sent.",
                    code="upload.busy",
                )
            return self._upload(name)

    def _upload(self, name: str) -> dict:
        if the_line_is_in_use(self.kernel) in ("burning", "queued"):
            raise DesignError(
                "A job is on this machine — burning, or waiting in the queue to "
                "start. Wait until it is done, or stop it: the file would go down "
                "the same connection that job uses. Nothing has been sent.",
                code="upload.whileBurning",
            )
        session = self._session()
        if not getattr(session, "supports_write_completion", False):
            raise DesignError(
                "This engine cannot confirm packet delivery. Install the Ruida session "
                "update before sending files; nothing has been sent.",
                code="upload.engineUpgrade",
            )
        short = _checked_name(name)
        payload = self.runner.build_job_bytes()
        if not payload:
            raise DesignError(
                "The job came out empty, so there is nothing to send. Nothing "
                "has been sent.",
                code="upload.emptyFile",
            )
        packets = self.frames(short, payload)
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
        with self._the_line_to_ourselves(session):
            return self._send(session, packets, chunks, short, payload)

    def _send(self, session, packets, chunks, short, payload) -> dict:
        generation = session.generation
        for index, packet in enumerate(packets):
            sent = max(0, index - 2)
            announced = index >= 2
            self._wait_for_the_line(session, sent, chunks, announced)
            try:
                receipt = self._write(packet, session=session, generation=generation)
            except (ConnectionError, OSError, TransportError, TransportTimeout) as exc:
                raise self._interrupted(
                    sent, chunks, "stopped answering",
                    code="upload.interrupted", announced=announced,
                ) from exc
            if not isinstance(receipt, Future):
                raise self._interrupted(
                    max(0, index - 1), chunks, "did not confirm delivery",
                    code="upload.interrupted", announced=index >= 1,
                )
            try:
                receipt.result(timeout=self.per_chunk_seconds)
            except ReceiptTimeout as exc:
                # Cancel an unsent packet; never replay one whose ACK may be lost.
                cancelled = receipt.cancel()
                raise self._interrupted(
                    sent if cancelled else max(0, index - 1), chunks,
                    "stopped taking the file", code="upload.stalled",
                    announced=announced if cancelled else index >= 1,
                ) from exc
            except (ConnectionError, OSError, TransportError, TransportTimeout) as exc:
                raise self._interrupted(
                    max(0, index - 1), chunks, "stopped answering",
                    code="upload.interrupted", announced=index >= 1,
                ) from exc
        return {"name": short, "bytes": len(payload), "chunks": chunks}
