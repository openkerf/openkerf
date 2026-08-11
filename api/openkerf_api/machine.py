"""
De machine bewegen: homen, jogpen, ontgrendelen.

Deze opdrachten zetten de kop in beweging. Anders dan pauzeren en stoppen zijn
ze niet device-specifiek: `core/spoolers.py` registreert ze op de kernel, dus
ze bestaan altijd en gaan via de spooler van het actieve apparaat. We melden de
beschikbaarheid alsnog, zodat de UI niet hoeft aan te nemen dat dat zo blijft.
"""

from .commands import CommandRunner
from .edits import DesignError, _finite

MOVES = ("home", "physical_home", "unlock", "lock")

# Scherpstellen zit op de Ruida (`focusz`), niet op elk apparaat. Zelfde aanpak
# als bij pauzeren en stoppen: vragen wat dit apparaat kent, niet aannemen.
FOCUS = "focusz"


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


class MachineControl:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    def capabilities(self) -> dict:
        caps = {name: self.runner.supports(name) for name in MOVES}
        caps["move"] = self.runner.supports("move_absolute")
        caps["jog"] = self.runner.supports("move_relative")
        caps["focus"] = self.runner.supports(FOCUS)
        return caps

    def _idle(self) -> None:
        """
        Niet bewegen terwijl er gebrand wordt.

        De UI zet de knoppen uit, maar de UI is een advies: een tweede tabblad,
        een telefoon of een curl-opdracht kan er dwars doorheen. De kop
        verzetten tijdens een job verpest hem op zijn best.
        """
        device = getattr(self.kernel, "device", None)
        spooler = getattr(device, "spooler", None)
        if spooler is None:
            return
        try:
            # Kijken naar een *lopende* job, niet naar de wachtrij: onze eigen
            # home en jog gaan óók door de spooler, en die zouden elkaar dan
            # blokkeren.
            running = any(job.is_running() for job in list(spooler.queue))
        except Exception:  # pragma: no cover - de spooler mag ons niet breken
            return
        if running:
            raise DesignError(
                "Er loopt een job. Stop hem eerst; bewegen tijdens het branden "
                "verpest de job."
            )

    def _require(self, command: str):
        if not self.runner.supports(command):
            raise DesignError(
                f"Dit apparaat kent '{command}' niet; beweging wordt door de "
                "device-service geleverd."
            )

    def home(self, physical: bool = False) -> dict:
        command = "physical_home" if physical else "home"
        self._require(command)
        self._idle()
        return {"output": self.runner.run(command)}

    def move_to(self, x_mm, y_mm) -> dict:
        """Absolute positie. De kop beweegt; dit is geen tekenopdracht."""
        self._require("move_absolute")
        self._idle()
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        return {"output": self.runner.run(f"move_absolute {_mm(x)} {_mm(y)}")}

    def jog(self, dx_mm, dy_mm) -> dict:
        self._require("move_relative")
        self._idle()
        dx = _finite(dx_mm, "dx_mm")
        dy = _finite(dy_mm, "dy_mm")
        if dx == 0 and dy == 0:
            raise DesignError("Een jog van nul doet niets.")
        return {"output": self.runner.run(f"move_relative {_mm(dx)} {_mm(dy)}")}

    def focus(self, distance_mm) -> dict:
        """
        De kop hoger of lager zetten. Scherpstellen is dagelijks werk: nieuwe
        materiaaldikte, nieuwe hoogte.
        """
        self._require(FOCUS)
        self._idle()
        distance = _finite(distance_mm, "distance_mm")
        if distance == 0:
            raise DesignError("Een verplaatsing van nul doet niets.")
        if abs(distance) > 100:
            raise DesignError("Meer dan 100 mm in één keer is geen scherpstellen.")
        return {"output": self.runner.run(f"{FOCUS} {_mm(distance)}")}

    def unlock(self) -> dict:
        """Motoren vrijgeven, zodat je de kop met de hand kunt verzetten."""
        self._require("unlock")
        return {"output": self.runner.run("unlock")}

    def lock(self) -> dict:
        self._require("lock")
        return {"output": self.runner.run("lock")}
