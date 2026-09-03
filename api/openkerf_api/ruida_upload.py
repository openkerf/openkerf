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

from .commands import CommandRunner
from .edits import DesignError

#: The way the engine chops its own jobs (`ruida/controller.py:83`,
#: `divide_data_into_queue`, which cuts at the first command past 1000 bytes).
CHUNK = 1000

#: What the machine keeps of a name. The emulator reads characters until the NUL
#: (`ruida/emulator.py:749-753`) and a Ruida's panel shows eight; we cut and
#: upper-case here, before it goes out, so the screen says what the panel says.
NAME_LENGTH = 8

FILE_TRANSFER = b"\xe8\x02"
SET_FILENAME = b"\xe7\x01"


def machine_name(name: str) -> str:
    """The name as the machine keeps it: printable ASCII, capitals, eight long."""
    kept = "".join(c for c in (name or "").strip() if 32 <= ord(c) < 127)
    return kept.upper()[:NAME_LENGTH]


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
        for start in range(0, len(payload), CHUNK):
            out.append(payload[start : start + CHUNK])
        return out
