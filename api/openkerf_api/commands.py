"""
Serialised console execution and device capability detection.

Every write action goes through here. Console commands mutate shared kernel
state, so they are executed one at a time under a lock — HTTP requests arrive
on uvicorn worker threads and must not interleave mid-pipeline.
"""

import re
import threading

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# The console reports failures as plain text on the channel rather than raising,
# so these are the markers that tell us a command did not take effect.
ERROR_MARKERS = (
    "is not a registered command",
    "Syntax Error",
    "Bad provider",
    "did not exist",
)

# The full job pipeline in one line: console commands chain through their
# input/output types only within a single line (verified against the engine).
PLAN_AND_SPOOL = "plan copy preprocess validate blob preopt optimize spool"


class CommandError(RuntimeError):
    def __init__(self, command, output):
        super().__init__(f"Command failed: {command}")
        self.command = command
        self.output = output


class CommandRunner:
    def __init__(self, kernel):
        self.kernel = kernel
        self._lock = threading.Lock()

    def run(self, command: str) -> list[str]:
        """Execute one console line and return its output. Raises CommandError."""
        captured: list[str] = []
        channel = self.kernel.channel("console")

        with self._lock:
            channel.watch(captured.append)
            try:
                self.kernel.console(command + "\n")
            finally:
                channel.unwatch(captured.append)

        output = [ANSI.sub("", str(line)).strip() for line in captured]
        output = [line for line in output if line]
        for line in output:
            if any(marker in line for marker in ERROR_MARKERS):
                raise CommandError(command, output)
        return output

    def supports(self, name: str, input_type: str = "None") -> bool:
        """
        Whether the active device provides this console command.

        `find` searches the active services first and then the kernel — exactly
        what the console parser does — so this reflects the device that is
        actually selected. pause/resume/estop are registered by device services
        (Ruida and Lihuiyu both do), not by the kernel, so availability changes
        when the user switches device; the dummy device has none of them.
        """
        return any(True for _ in self.kernel.find("command", input_type, f"{name}$"))

    def capabilities(self) -> dict:
        return {
            "start": self.supports("plan") and self.supports("spool"),
            "pause": self.supports("pause"),
            "resume": self.supports("resume"),
            "stop": self.supports("estop") or self.supports("abort"),
            "clear_queue": self.supports("spool"),
            "load": self.supports("load"),
        }

    # --------------------------------------------------------------- actions

    def load_file(self, path: str) -> list[str]:
        return self.run(f'load "{path}"')

    def start_job(self) -> list[str]:
        return self.run(PLAN_AND_SPOOL)

    def pause(self) -> list[str]:
        return self.run("pause")

    def resume(self) -> list[str]:
        return self.run("resume")

    def stop(self) -> list[str]:
        """Abort the running job. estop is realtime; abort is the fallback."""
        if self.supports("estop"):
            return self.run("estop")
        return self.run("abort")

    def clear_queue(self) -> list[str]:
        return self.run("spool clear")
