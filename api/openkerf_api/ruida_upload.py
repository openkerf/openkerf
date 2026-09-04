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

import threading
import time

from meerk40t.ruida.rdjob import parse_commands

from .commands import CommandRunner
from .edits import DesignError
from .machine import a_job_is_running

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
    """
    The upload conversation: the packets, and putting them on the line.

    The flow control is ours. The engine's is `_data_sender`
    (`ruida/controller.py:119`), a thread that pops its whole queue into
    `RuidaSession.write` and says "File Sent." when the queue is empty — and
    `write` (`ruida/ruidasession.py:186`) gives up after twelve tries at 0.25 s
    on a full queue and falls out of its own loop without raising, carrying the
    TODO "How to inform the calling method a timeout occurred?". Nothing between
    those two ever finds out that a packet did not go. On an engraving job that
    is hundreds of blocks. So: one block at a time, wait for the line to be
    free, and stop **with numbers** when it will not clear.

    What "free" means took a measurement to get right, because writing and
    arriving are two different moments on a real session. `RuidaSession.write`
    is `send_q.put` and nothing else (`ruida/ruidasession.py:188`); a separate
    handshaker thread pops the packet, hands it to the transport, and only then
    sets `_ack_pending` (`:349`) — the half of `is_busy` that our own blocks
    ever touch. Waiting on `is_busy` alone therefore waits on nothing: the line
    still looks free straight after our own write. Measured, six blocks and two
    headers against a session that acknowledges in 0.05 s: the whole upload
    returned in **0.019 s with 0 of 8 packets acknowledged and all eight still
    in the queue**. So `_line_is_busy` asks the queue as well, and
    `_wait_for_the_line` runs once more after the last block — see `upload`.

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
        #: One upload at a time down one connection.
        #:
        #: The server builds one of these and `machine_upload` is a plain `def`,
        #: so FastAPI runs it in the threadpool and two calls really do overlap —
        #: a double-click or a second tab is enough. Building is serialised by
        #: `claim_plan()`, the sending was not. Measured with two concurrent
        #: `upload()` calls and no lock: both returned a result, and the line saw
        #: `E8 02, E8 02, E7 01, E7 01, <block>, <block>` — two transfers begun,
        #: two names, and the two files' blocks after each other, which is one
        #: file in the machine's memory made out of two jobs.
        #:
        #: Refusing rather than queueing, and that is the choice worth stating.
        #: A blocking lock would hold a threadpool thread through the whole of
        #: somebody else's build and send, and then put a second file on the
        #: panel that nobody asked for twice — which is what a double-click is.
        #: A sentence costs the user one press.
        self._sending = threading.Lock()

    def frames(self, name: str, payload: bytes) -> list[bytes]:
        """The whole conversation as a list of packets, in order."""
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
        """The live session, or a refusal that says nothing has been sent.

        `RuidaSession.connected` (`ruida/ruidasession.py:154`) wants three things
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

    def _interrupted(
        self, sent: int, chunks: int, why: str, code: str, announced: bool
    ):
        """The refusal, saying what is actually on the machine.

        Four cases, and they are not four values of one counter — that is what
        made the last two versions of this wrong. `sent` counts blocks, so
        `sent == 0` holds at **three** moments: the wait before `E8 02`, the wait
        before `E7 01 <name>`, and the wait before the first block. At the third
        of those the name is out, and the receiver opens the file on the name
        rather than on the first block (`ruida/emulator.py:757`, an `open(...,
        "wb")` in the `E7 01` branch) — so the panel can be showing an empty file
        while a refusal branching on the count alone says there is nothing there.
        Hence `announced`, which is about what went down the line, not about how
        far a counter got.

        The code is passed by keyword at both call sites, and stays that way: the
        interface pairs a translation with a refusal by searching this package for
        `code="..."` (`frontend/tests/i18n.test.ts`), and a code handed over
        positionally is one no such search finds — a sentence in the reader's
        language that nothing ever reaches.

        `announced` travels in `values` as well, because the interface has to
        pick the same four sentences in the reader's language and `sent` and
        `chunks` cannot tell it which of the two zeroes this is. A translated
        sentence branching on the number alone would make this exact mistake
        again, one layer out.

        The other end had the same shape of error: `sent == chunks` is the
        closing wait, where every block including the one holding `SET_FILE_SUM`
        and `END_OF_FILE` has been written and only the acknowledgement is
        missing — not an incomplete file, and "after 5 of 6 blocks" there was
        simply a wrong number.
        """
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
        """Whether the line still holds anything — ours or not.

        Not "anything of ours": `send_q` is shared, and the engine's status
        monitor puts a `GET_SETTING` in it every 0.2 s (`controller.py:162`).
        There is no marker on a packet to tell them apart, so a poll of somebody
        else's makes this say busy. See `_wait_for_the_line` for what that costs
        and why the cost only ever falls on the safe side.

        Two questions, because a real session answers only half of it. The
        packet sits in `send_q` from `write` (`ruida/ruidasession.py:188`) until
        the handshaker thread takes it (`:330`), and `_ack_pending` is set only
        *after* that thread has handed it to the transport — and only on a `udp`
        interface (`:349`). So on `is_busy` alone there is a window after every
        write in which the line looks free while our packet has not moved.

        On `usb` no packet of ours ever sets it. The one other place that does
        is `connect()` (`:248`, cleared at `:256` and `:313`), which is not
        interface-specific but runs only while `connected` is false — and a
        session in that state is refused by `_session()` before any of this. The
        engine says why in its own comment a few lines above: "When comms is via
        USB there are no ACK responses" (`:240-241`). So on `usb` `is_busy`
        reports `_reply_pending`, which `0xDA` commands set: the status polls,
        never our blocks.

        Asking the queue first closes the `udp` window and gives `usb` an answer
        that is about our own packets at all: an empty queue means the
        handshaker has taken everything we handed it. On `udp` the
        acknowledgement sits on top of that; on `usb` "taken and written to the
        transport" is the most the engine can tell anybody, and this does not
        pretend otherwise.
        """
        pending = getattr(session, "send_q", None)
        if pending is not None and not pending.empty():
            return True
        return bool(getattr(session, "is_busy", False))

    def _wait_for_the_line(
        self, session, sent: int, chunks: int, announced: bool
    ) -> None:
        """Wait until the line is free again, or refuse saying how far it got.

        The connection is asked first, and not only for tidiness. On `udp` a
        machine that goes away leaves `_ack_pending` set for ever and the
        deadline below catches it. On `usb` there is no acknowledgement to be
        missing: the handshaker takes our last block, the transport write fails,
        and the queue is empty — so a wait that asks only "is anything still
        out?" sees a clear line. Measured, with the connection dropping on the
        eighth packet of eight: `upload()` returned `{'chunks': 6}` on the block
        that closes the file. What the engine does leave is `_responding`, one
        of the three things `connected` is made of (`ruidasession.py:154`), and
        that is asked first, because a session that is not answering is a more
        specific answer than "it is taking too long".

        What it is **not** is a diagnosis, which is why the refusal says the
        machine stopped answering rather than that the connection broke.
        `_responding` is cleared in seven places and only three are a broken
        link: a failed transport write (`:346`), a failed resend after a NAK
        (`:381`), and an `OSError` escaping the loop (`:418`). The others are
        silence: a purge that failed while connecting (`:281`), the handshaker
        starting up (`:314`), a reply that never arrived (`:409`) — and `:366`,
        the ACK read running out of tries, which at `normal_timeout()` is four
        reads of 0.25 s, about **one second**. The engine's own comment above it
        (`:359-360`) says when that happens: "This will occur while the
        controller is executing a physical home." After it the handshaker
        returns to `connect()` and can set the flag back to `True` (`:258`).

        So this can fire on a machine that is homing rather than gone. It is
        left that way deliberately, because nothing available here tells the two
        apart. `is_open` does not: a UDP socket stays open through both, and a
        failed write closes nothing. Neither do `sends`, `acks` or `enqs`: the
        handshaker probes with an ENQ in both stories. The one thing that would
        is waiting for `_responding` to come back — which is what the engine
        does, and which turns a ten-second refusal into a wait of unknown length
        with nothing to tell the user meanwhile. The app the engine's own
        `gross_timeout()` protects is only the one that started the home itself
        (`driver.py:392-403`, its single caller); a home somebody presses on the
        panel gets the one second. Whichever it was, an upload that was refused
        can simply be sent again, and what the machine is left holding is what
        `_interrupted` works out from `sent` and `announced` — which is why the
        advice is four sentences there and not one here.

        The shared queue costs one thing, and it is worth writing down where the
        refusal is raised. Because `_line_is_busy` cannot tell our packets from
        the status monitor's, any stretch in which the queue is not *seen* empty
        for `per_chunk_seconds` comes out as `upload.stalled` — naming a block
        number for a file that may well have arrived whole. One poll every 0.2 s
        answered in milliseconds makes ten seconds of that unlikely, but nothing
        rules it out: a spell of slow replies does it as readily as the 40-second
        `gross_timeout()` around a physical home (`controller.py:108`).

        The error only ever falls on the safe side, though, and that is why it is
        left standing. A packet that is not ours can only *add* to the queue, so
        the sharing can make this wait longer than it needs to, or refuse a
        transfer that was fine — never let one through that was not. And the
        advice survives being wrong about the cause: check the file on the panel
        before burning it is right whether the transfer really stalled or the
        queue was somebody else's.
        """
        deadline = time.monotonic() + self.per_chunk_seconds
        while True:
            if not getattr(session, "connected", True):
                raise self._interrupted(
                    sent, chunks, "stopped answering",
                    code="upload.interrupted", announced=announced,
                )
            if not self._line_is_busy(session):
                return
            if time.monotonic() > deadline:
                raise self._interrupted(
                    sent, chunks, "stopped taking the file",
                    code="upload.stalled", announced=announced,
                )
            time.sleep(self.poll_seconds)

    def upload(self, name: str) -> dict:
        """The file to the machine, and left standing there.

        Four things are checked before the first byte goes out. Two of them are
        about the connection and are in `_upload` at the top, ahead of the
        building: **a job that is burning**, because our blocks share its
        `send_q`, and **an upload already running**, because two of them
        interleave into one file made of two jobs (both measured; see
        `a_job_is_running` and `self._sending`).

        The other two are about the file, and both would otherwise leave
        something on the panel that the user has to find and delete:

        * **An empty payload.** `frames(name, b"")` is two headers and no
          blocks — a name announced with nothing behind it. `build_job_bytes`
          refuses an empty bed itself, so nothing reaches this today; that is a
          promise about another function, and this is what it costs if it ever
          stops holding.
        * **A block over `CHUNK`.** `_blocks` never cuts inside a command, so a
          single command longer than `CHUNK` gets an oversized block of its own.
          Measured: `_blocks(b"\\x88" + b"\\x11" * 1200)` gives **one** block,
          of 1201 bytes; put a second command behind it and the answer is
          `[1201, 2]`.

          What such a block costs is measured on one side and assumed on the
          other. Measured, on a pair of loopback UDP sockets: 996, 1000 and 1024
          bytes arrive whole, and 1201 and 1203 both arrive as **1024**, with no
          error on either side — the tail is simply gone. That is what happens
          to anything *the engine* receives, since every receiver in it reads
          with `recvfrom(1024)` (`ruida/udp_transport.py:62`,
          `udp_connection.py:174`, `network/udp_server.py:96`), the last of
          which is the emulator a `ruidacontrol` stand-in listens on.

          **Assumed**, because nobody here has measured a Ruida's firmware: that
          a real machine has the same 1024-byte ceiling, which with the two
          checksum bytes `_package` puts in front leaves 1022 for a block. It
          rests on the engine cutting its own jobs at 1000 bytes
          (`controller.py:83`), a limit reverse-engineered against real
          machines — not on anything measured here. `CHUNK` at 1000 sits under
          either reading, and the guard below only refuses what is over `CHUNK`
          anyway, so the assumption decides nothing; it is written down so the
          number is not read as a measurement.

          Truncating a command silently is the exact damage `_blocks` exists to
          avoid, so an oversized block is refused rather than sent; on this
          project's designs the longest command is 16 bytes, so it is a guard,
          not a case anybody meets.

        The engine's status monitor keeps polling the machine over this same
        session while we send, and its packets land between our blocks. That is
        left alone on purpose, and the emulator says why it can be: measured,
        the same six blocks with a `GET_SETTING` written between every pair give
        a job byte for byte identical to the clean one, 0 parse failures —
        the poll is answered as realtime (`emulator.py:157`) and never reaches
        the file. So there is nothing here to protect against.

        Which is the whole argument, because the alternative can hang the app.
        `pause_monitor()` is a bare `acquire()` with no timeout on a lock that
        four places release (`controller.py:98`, `:132`, `:183`, `:393`) — so it
        blocks for as long as `_data_sender` holds it, which is exactly the
        stalled case this method exists for, and forever if `resume_monitor`
        never ran (it has one caller, `ruida/device.py:415`).

        What comes out is a function of the drawing as it stands, and not of
        when it is sent: measured, ten builds of one drawing gave the same
        bytes ten times, with the runner kept and with a fresh one for every
        call. So pressing this twice on the same drawing, in the same session,
        puts the same file on the machine twice — the qualifier belongs in the
        sentence, because a server restarted in between has made the drawing
        again, and that is the case just below.

        What does move it is making the shapes again. Ten redraws of the same
        eight circles gave 5462 or 5463 bytes in no order — two different, both
        valid, polygon approximations of the same arc, with vertices up to about
        half a millimetre apart (measured separately: the cutcode is pointwise
        identical, so the difference appears in the encoding, not in the plan).
        Reopen a project, or run a generator again, and the file you send can
        differ from the one before it. Both are the right shape; what the bytes
        are not is a fingerprint of a design, so nothing should compare two
        uploads to decide whether anything changed.
        """
        if not self._sending.acquire(blocking=False):
            raise DesignError(
                "This machine is already being sent a file. Wait until that one "
                "is done and press again; nothing has been sent.",
                code="upload.busy",
            )
        try:
            return self._upload(name)
        finally:
            self._sending.release()

    def _upload(self, name: str) -> dict:
        """The whole of an upload, with `upload()` holding the lock around it.

        Split off so the `release()` is a `finally` around one call, rather than
        something to remember on each of the many ways out of here — every
        refusal below is one, and a lock left held would refuse every upload
        after it for the life of the server.
        """
        # Before anything else, and before the job is built. Our blocks go down
        # `controller.write` -> `active_session.write` -> the same `send_q` a
        # burning job is streaming through, so this is the rule
        # `MachineControl._idle()` states for moving the head, on the same
        # connection: the interface is advice, and a second tab or a curl command
        # goes straight through it. `_line_is_busy` does not stand in for it —
        # `_data_sender` empties that queue in one go while the machine burns on
        # for minutes, so a free line says nothing about a free machine.
        #
        # What the two streams do to each other was measured against the engine's
        # own `RuidaEmulator`, no socket and no hardware: a burning job of 1072
        # commands (5463 bytes) with the whole upload conversation of a rectangle
        # (433 bytes) dropped in halfway. They land in **one** `RDJob` — buffer
        # 5882 bytes against 5456 for the burn alone, the burn's own bytes no
        # longer contiguous, and `program_mode` already `False` straight after the
        # upload, in the middle of the burn, because the payload ends in `D7`
        # (END_OF_FILE) and carries its own `D8 00` (START_PROCESS). All of it
        # silently: **0** parse failures. Those bytes are not inert.
        #
        # What stays an assumption: the receiver the engine ships does not
        # separate storing from executing — it hangs everything on the same
        # `RDJob` and spools it (`ruida/emulator.py:157-159`) whatever `saving`
        # says. What a real Ruida's firmware makes of this seam has **not** been
        # measured here. Neither half changes the check: the fact is that the
        # receiver we have merges the two streams without a word, and the API is
        # where this is stopped either way.
        if a_job_is_running(self.kernel):
            raise DesignError(
                "A job is running. Wait until it is done, or stop it: the file "
                "would go down the same connection the machine is burning from. "
                "Nothing has been sent.",
                code="upload.whileBurning",
            )
        session = self._session()
        # Before the job is built, not after: building plans the whole design and
        # runs it through a driver, and the answer to a nameless upload was known
        # from the argument.
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
        for index, packet in enumerate(packets):
            sent = max(0, index - 2)
            # Whether the *name* is out, which is a different question from how
            # many blocks are: `packets[1]` is `E7 01 <name>`, and the receiver
            # opens the file there (`ruida/emulator.py:757`), so from index 2
            # onwards a refusal has to talk about a file that exists even while
            # `sent` is still 0. Counted off the packets already written rather
            # than derived from `sent`, because deriving it is what hid the case:
            # `sent == 0` is true at three different moments and only the first
            # two of them leave the panel clean.
            announced = index >= 2
            self._wait_for_the_line(session, sent, chunks, announced)
            try:
                self._write(packet)
            except (ConnectionError, OSError) as e:
                raise self._interrupted(
                    sent, chunks, "stopped answering",
                    code="upload.interrupted", announced=announced,
                ) from e
        # And once more after the last one, which is the block holding
        # `SET_FILE_SUM` and `END_OF_FILE`. Every other block is confirmed by the
        # wait in front of the block after it; this one has no block after it.
        #
        # What "confirmed" is worth differs by interface, and neither is a
        # promise about the material. On `udp` it is the machine's own
        # acknowledgement. On `usb` there is none to be had, so it is "the
        # engine took every block and none of them failed on the way out" — the
        # last one can still be at the transport when this returns. Measured on
        # a session that never acknowledges: 7 or 8 of 8 packets written through
        # at the moment `upload()` returns, run to run.
        #
        # `chunks` and not `chunks - 1`: every block has been handed to the line
        # by now, which is what these two numbers count. The one thing still
        # unknown here — the last block went out and nothing came back about it —
        # is what `_interrupted` says in its own sentence for this case, rather
        # than by quietly shaving one off a count called "blocks".
        self._wait_for_the_line(session, chunks, chunks, True)
        return {"name": short, "bytes": len(payload), "chunks": chunks}
