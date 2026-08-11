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
    # De engine meldt een onleesbaar bestand alleen op het console-kanaal en
    # geeft daarna netjes terug. Zonder deze marker kwam er HTTP 200 {"ok":true}
    # uit een bestand dat nooit is ingelezen — de gebruiker ziet een leeg bed en
    # geen enkele reden waarom.
    "File is Malformed",
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
    def __init__(self, kernel, document=None):
        self.kernel = kernel
        self._lock = threading.Lock()
        # Gezet door de server; elke schrijvende opdracht maakt het ontwerp vuil.
        self.document = document

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

        if self.document is not None:
            self.document.touch(command)
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
        """
        Een bestand inlezen, en eerlijk zijn als dat niet lukt.

        De console meldt een mislukking als tekst op het kanaal en geeft daarna
        gewoon terug, dus zonder deze controle kwam er "gelukt" uit een bestand
        dat nooit is ingelezen. Twee dingen kunnen misgaan: het bestand is
        onleesbaar (de engine roept "File is Malformed"), of het is leesbaar
        maar leeg — een SVG zonder vormen laadt zonder klacht en levert een
        leeg bed op. Allebei krijgen ze hier hun eigen zin, in de taal van
        iemand die een tekening wilde openen.
        """
        naam = path.rsplit("/", 1)[-1]
        voor = self._element_count()
        try:
            output = self.run(f'load "{path}"')
        except CommandError as e:
            raise CommandError(
                "load",
                [
                    f"“{naam}” is niet in te lezen. Het bestand is beschadigd of "
                    "het is geen tekening — controleer of je de juiste export "
                    "hebt (SVG, DXF, PNG of een RD-bestand).",
                ],
            ) from e
        if self._element_count() <= voor:
            raise CommandError(
                "load",
                [
                    f"In “{naam}” zit geen tekening. Het bestand is gelezen maar "
                    "bevat geen vormen — bij een SVG uit een tekenprogramma komt "
                    "dat meestal doordat alles op een verborgen laag staat.",
                ],
            )
        return output

    def _element_count(self) -> int:
        """Hoeveel vormen er in de boom staan; 0 als de engine niet meewerkt."""
        try:
            return sum(1 for _ in self.kernel.elements.elems())
        except Exception:
            return 0

    def start_job(self) -> list[str]:
        """
        Het plan bouwen en naar de spooler sturen.

        Eerst kijken óf er iets te branden valt. Een leeg ontwerp liep hier
        vrolijk doorheen en meldde "gelukt": de gebruiker drukt op starten, de
        app zegt ja, en er gebeurt niets bij de machine. Dat is de vervelendste
        soort fout — je gaat ernaast staan wachten.
        """
        elements = self.kernel.elements
        burnable = 0
        for operation in elements.ops():
            if not str(operation.type).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            burnable += sum(1 for child in operation.children)
        if not burnable:
            raise CommandError(
                "start",
                [
                    "Er staat niets klaar om te branden. Teken of laad iets, en "
                    "zet het in een laag die meebrandt — een laag met "
                    "'meebranden' uit wordt overgeslagen."
                ],
            )
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
