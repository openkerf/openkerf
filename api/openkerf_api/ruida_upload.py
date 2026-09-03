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

    The single exception: a command longer than `CHUNK` all by itself goes out
    whole, in an oversized block. Cutting it is the exact damage this function
    exists to avoid. Measured on this project's designs the longest command is
    16 bytes, so this is a guard, not a case anybody meets.
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
    The upload conversation. Building the packets is all this does today;
    sending them, with the flow control that says how far it got, is added to
    this same class in the next step.
    """

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
