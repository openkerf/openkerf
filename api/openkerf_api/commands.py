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
#
# `clear` staat er niet voor de sier. `plan copy` *voegt toe* aan het plan dat er
# al ligt (planner.py:593, `data.append`), en het plan is kernel-globaal en
# blijft na het spoolen staan. Zonder clear droeg de tweede start dus twee keer
# hetzelfde werk, de derde drie keer, en groeide de tijdschatting met een factor
# per druk op de knop — gemeten: 1701 s, 3364 s, 5027 s voor hetzelfde ontwerp.
# Dat is de bron van "150:40:23 voor hetzelfde werk" uit gat B1: niet één foute
# formule maar elf keer dezelfde job in één plan. Erger dan het getal is wat er
# gebrand zou zijn: de machine snijdt elke vorm net zo vaak over.
PLAN_AND_SPOOL = "plan clear copy preprocess validate blob preopt optimize spool"

# Dezelfde pijplijn, maar in tweeën geknipt zodat er tussen `copy` en de rest
# iets in het plan gezet kan worden. Alleen gebruikt als een laag een Z-stap
# draagt; zonder dat blijft de regel hierboven letterlijk wat hij was.
PLAN_COPY = "plan clear copy"
PLAN_REST = "plan preprocess validate blob preopt optimize spool"


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

    def start_job(self, name: str | None = None, mutators=()) -> list[str]:
        """
        Het plan bouwen en naar de spooler sturen.

        Eerst kijken óf er iets te branden valt. Een leeg ontwerp liep hier
        vrolijk doorheen en meldde "gelukt": de gebruiker drukt op starten, de
        app zegt ja, en er gebeurt niets bij de machine. Dat is de vervelendste
        soort fout — je gaat ernaast staan wachten.

        `mutators` zijn bewerkingen op het gekopieerde plan (tegels, Z-stappen).
        Zie `_plan_and_spool`.
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
        output = self._plan_and_spool(mutators)
        self._name_job(name, burnable)
        return output

    # ------------------------------------------------------ zakken per pass

    def _plan_and_spool(self, mutators=()) -> list[str]:
        """
        Het plan bouwen. Met bewerkers in twee stappen, anders in één.

        Een bewerker is een callable die de planstappen krijgt en teruggeeft.
        De volgorde telt: tegels eerst (klippen en verplaatsen), Z-stappen
        daarna (de passes uitvouwen) — andersom klip je hetzelfde werk zes keer.

        De gewone weg blijft letterlijk één regel: dat pad wordt bij elke job
        gelopen en verdient geen extra bochten.
        """
        alle = list(mutators)
        if self._z_stepped_layers():
            from meerk40t.core.node.util_console import ConsoleOperation

            alle.append(lambda steps: self._with_z_moves(steps, ConsoleOperation))
        if not alle:
            return self.run(PLAN_AND_SPOOL)
        return self._plan_with_mutators(alle)

    def _plan_with_mutators(self, mutators) -> list[str]:
        """
        Het plan opbouwen, bewerken, en dan pas afmaken.

        `opt_merge_ops`/`opt_merge_passes` gaan uit zolang wij aan het plan
        zitten. Met die vlaggen aan plakt de optimalisatie stukken tot één
        cutcode en schuift consolestappen naar achteren — dan zakt een Z pas
        als er al gebrand is, en dat merk je aan het werkstuk in plaats van aan
        het scherm. Het zijn instellingen van de gebruiker, dus ze gaan in een
        `finally` terug.

        Het plan is een kopie van de boom: `plan copy` roept
        `copy_children_as_real` aan, dat de ReferenceNodes dereferentieert en de
        vormen zelf kopieert. Wat hier bewerkt wordt, raakt het ontwerp van de
        gebruiker dus niet.
        """
        root = self.kernel.root
        root.setting(bool, "opt_merge_ops", True)
        root.setting(bool, "opt_merge_passes", True)
        eerder = (root.opt_merge_ops, root.opt_merge_passes)
        root.opt_merge_ops = False
        root.opt_merge_passes = False
        try:
            output = self.run(PLAN_COPY)
            self._apply_mutators(mutators)
            output += self.run(PLAN_REST)
            return output
        finally:
            root.opt_merge_ops, root.opt_merge_passes = eerder

    def _apply_mutators(self, mutators) -> list:
        """De bewerkers over het gekopieerde plan. Geeft de nieuwe stappen terug."""
        plan = self.kernel.planner.get_or_make_plan("0")
        steps = list(plan.plan)
        for mutator in mutators:
            steps = list(mutator(steps))
        plan.plan[:] = steps
        return steps

    def build_plan(self, mutators=()) -> list:
        """
        Het gekopieerde en bewerkte plan, zonder het af te maken.

        Bestaat omdat je er anders niet naar kunt kijken: `blob` vervangt de
        bewerkingen door één `CutCode`, dus na een volledige `plan`-regel is er
        geen laag met kinderen meer om iets over vast te stellen. Wat de
        bewerkers doen is precies wat hier getest hoort te worden, en dit is de
        enige plek waar dat nog zichtbaar is.

        Draait bewust niet de spooler: dit is de haak voor tests, niet een
        tweede manier om een job te starten.
        """
        self.run(PLAN_COPY)
        return self._apply_mutators(mutators)

    def _z_stepped_layers(self) -> list:
        """
        Lagen die meebranden, meer dan één pass doen én een Z-stap dragen.

        De machine wordt eerst gevraagd of ze een Z-as heeft. Dat is niet
        dubbelop met de weigering bij het instellen: een laag houdt zijn stap
        als je naar een andere machine wisselt, en zonder deze vraag zou een
        ontwerp dat op een diode-laser gemaakt is op de Ruida een `z_move`
        sturen die daar niet bestaat — middenin de job, met de kop op het werk.
        """
        gevonden = []
        device = getattr(self.kernel, "device", None)
        if device is None or not getattr(device, "supports_z_axis", False):
            return gevonden
        if not self.kernel.find("command", "None", "z_move$"):
            return gevonden
        try:
            operations = list(self.kernel.elements.ops())
        except Exception:  # pragma: no cover - een boom zonder ops-tak
            return gevonden
        for operation in operations:
            if not str(getattr(operation, "type", "")).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            if not getattr(operation, "z_step_mm", None):
                continue
            if int(getattr(operation, "passes", 1) or 1) < 2:
                continue
            gevonden.append(operation)
        return gevonden

    @staticmethod
    def _with_z_moves(steps, console_operation) -> list:
        """De planstappen met de Z-bewegingen erin. Puur rekenwerk, dus testbaar."""
        uitgebreid = []
        for step in steps:
            z_step = getattr(step, "z_step_mm", None)
            passes = int(getattr(step, "passes", 1) or 1)
            if not z_step or passes < 2:
                uitgebreid.append(step)
                continue
            # De teller op de bewerking gaat naar één: het herhalen doen wij nu.
            step.passes = 1
            step.passes_custom = True
            for index in range(passes):
                uitgebreid.append(step)
                if index < passes - 1:
                    uitgebreid.append(
                        console_operation(command=f"z_move {z_step:.3f}mm")
                    )
            uitgebreid.append(
                console_operation(command=f"z_move {-z_step * (passes - 1):.3f}mm")
            )
        return uitgebreid

    def _name_job(self, name, burnable: int) -> None:
        """
        De verse job een naam geven die een mens herkent (gat P4).

        De engine noemt hem `Spooler:3 items` zodra er geen bestandsnaam is:
        de klassenaam plus de lengte van de opdrachtenlijst (spoolers.py:612).
        Het `spool`-commando haalt zijn label uit `elements.basename` en kent
        geen optie om er iets anders in te zetten, dus we hernoemen de job
        nadat hij in de wachtrij staat. Alleen als de engine zelf niets wist:
        heb je een bestand geladen, dan is die naam beter dan de onze.
        """
        titel = (name or "").strip()
        if not titel:
            titel = f"{burnable} bewerking" + ("" if burnable == 1 else "en")
        try:
            queue = list(self.kernel.device.spooler.queue)
        except Exception:
            return
        if not queue:
            return
        job = queue[-1]
        huidig = str(getattr(job, "label", "") or "")
        if huidig and not re.fullmatch(r"\w+:\d+ items?", huidig):
            return
        try:
            job.label = titel
        except Exception:  # pragma: no cover - de engine mag ons niet breken
            pass

    def _driver_paused(self):
        """`driver.paused` van het actieve apparaat, of None als niemand het zegt."""
        try:
            flag = self.kernel.device.driver.paused
        except Exception:
            return None
        return flag if isinstance(flag, bool) else None

    def pause(self) -> list[str]:
        """
        Pauzeren, en niet iets anders.

        `pause` is bij lihuiyu, ruida én grbl een *toggle*: staat de driver al
        op pauze, dan hervat hetzelfde commando (lihuiyu/device.py:844,
        ruida/device.py:425, grbl/device.py:982). Twee keer op Pauze drukken
        zet de machine dus weer aan het branden, en dat is precies het
        tegenovergestelde van wat er op de knop staat.
        """
        if self._driver_paused() is True:
            return ["already paused"]
        return self.run("pause")

    def resume(self) -> list[str]:
        """
        Hervatten, en controleren dat het ook gebeurd is.

        Gemeten op een lihuiyu-apparaat: `resume` meldt "Lihuiyu Channel
        Resumed." en de machine blijft staan. Oorzaak zit in de engine — het
        apparaat registreert `resume` twee keer, eerst als realtime-hervat
        (device.py:855) en later nog eens als "Resume Controller"
        (device.py:1045). De tweede wint, en die start de controller in plaats
        van de driver: `driver.paused` blijft True en `hold_work()` houdt het
        werk vast. Op een K40 kwam een gepauzeerde job daardoor nooit meer op
        gang — de hervatknop deed niets, elke keer opnieuw.

        Wij kunnen dat niet in `meerk40t/` repareren, dus controleren we het
        resultaat: staat de driver na afloop nog op pauze, dan halen we hem er
        met de toggle af. Voor ruida en grbl verandert er niets; daar is de
        vlag na de eerste poging al weg.
        """
        if self._driver_paused() is False:
            return ["not paused"]
        output = self.run("resume")
        if self._driver_paused() is True:
            output = output + self.run("pause")
        return output

    def stop(self) -> list[str]:
        """Abort the running job. estop is realtime; abort is the fallback."""
        if self.supports("estop"):
            return self.run("estop")
        return self.run("abort")

    def clear_queue(self) -> list[str]:
        return self.run("spool clear")
