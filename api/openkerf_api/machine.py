"""
De machine bewegen: homen, jogpen, ontgrendelen.

Deze opdrachten zetten de kop in beweging. Anders dan pauzeren en stoppen zijn
ze niet device-specifiek: `core/spoolers.py` registreert ze op de kernel, dus
ze bestaan altijd en gaan via de spooler van het actieve apparaat. We melden de
beschikbaarheid alsnog, zodat de UI niet hoeft aan te nemen dat dat zo blijft.
"""

import json

from .commands import CommandRunner
from .edits import DesignError, _finite

MOVES = ("home", "physical_home", "unlock", "lock")

# Waar bewaarde posities staan (gat J6).
#
# Op de device-service, niet in onze bibliotheek: een positie is een eigenschap
# van déze machine met déze mal erop, en de settings van een service zijn
# precies daarvoor gemaakt — ze verhuizen mee als de machine van profiel
# wisselt, en ze overleven een herstart zonder dat wij een tabel hoeven te
# migreren. De bibliotheek is van iemand anders en gaat over materiaal.
POSITIES_KEY = "openkerf_positions"
MAX_POSITIES = 12
MAX_NAAM = 40

# De gebruikersoorsprong (gat J12).
#
# Naast de bewaarde posities en om dezelfde reden: een nulpunt hoort bij déze
# machine met dít stuk restplank erop, niet bij de browser waar je toevallig
# achter zit. Eén per machine — twee nulpunten tegelijk is geen nulpunt meer.
OORSPRONG_KEY = "openkerf_origin"

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

    def frame(self, x_mm, y_mm, width_mm, height_mm) -> dict:
        """
        De kop langs de vier hoeken van het werk sturen.

        Dit is de laatste controle vóór je brandt: past het op het materiaal,
        ligt het recht, zit de klem in de weg. De laser blijft uit — er wordt
        alleen bewogen, met dezelfde bewaking als bij een jog.
        """
        self._require("move_absolute")
        self._idle()
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        breedte = _finite(width_mm, "width_mm")
        hoogte = _finite(height_mm, "height_mm")
        if breedte <= 0 or hoogte <= 0:
            raise DesignError("Er is niets om een kader omheen te trekken.")

        bed = self._bed_mm()
        if bed and (x < 0 or y < 0 or x + breedte > bed[0] or y + hoogte > bed[1]):
            raise DesignError(
                f"Het kader ({breedte:.0f}x{hoogte:.0f} mm vanaf {x:.0f},{y:.0f}) "
                f"valt buiten het bed van {bed[0]:.0f}x{bed[1]:.0f} mm."
            )

        # Terug naar de eerste hoek, zodat je de ronde ook echt ziet sluiten.
        hoeken = [
            (x, y),
            (x + breedte, y),
            (x + breedte, y + hoogte),
            (x, y + hoogte),
            (x, y),
        ]
        uitvoer = []
        for hx, hy in hoeken:
            resultaat = self.runner.run(f"move_absolute {_mm(hx)} {_mm(hy)}")
            uitvoer.extend(resultaat if isinstance(resultaat, list) else [resultaat])

        # De kop kan nog van de vorige hoek onderweg zijn; sommige drivers
        # weigeren dan de volgende opdracht. Dat stilzwijgend inslikken zou
        # betekenen dat je denkt het kader gezien te hebben terwijl er een hoek
        # ontbrak.
        bezet = [r for r in uitvoer if "busy" in str(r).lower() or "error" in str(r).lower()]
        return {
            "output": uitvoer,
            "corners": len(hoeken),
            "notice": (
                "De machine meldde dat hij bezig was; het kader is mogelijk niet "
                "helemaal gelopen. Probeer het opnieuw als de kop stilstaat."
                if bezet
                else None
            ),
        }

    def _bed_mm(self):
        """Het werkgebied in millimeters, of None als het apparaat het niet zegt."""
        device = getattr(self.kernel, "device", None)
        try:
            from meerk40t.core.units import Length

            return (Length(device.bedwidth).mm, Length(device.bedheight).mm)
        except Exception:
            return None

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

    # ------------------------------------------------- bewaarde posities (J6)

    def _device(self):
        device = getattr(self.kernel, "device", None)
        if device is None:
            raise DesignError("Er is geen actieve machine.")
        return device

    def positions(self) -> list[dict]:
        """
        De posities die deze machine onthoudt.

        LightBurn's Move-venster heeft ze en wij niet: wie een mal op het bed
        heeft liggen, wil "linkerbovenhoek van de mal" één keer vastleggen in
        plaats van hem elke sessie opnieuw bij elkaar te joggen.
        """
        device = self._device()
        try:
            device.setting(str, POSITIES_KEY, "[]")
            ruw = json.loads(getattr(device, POSITIES_KEY, "[]") or "[]")
        except Exception:
            return []
        if not isinstance(ruw, list):
            return []
        schoon = []
        for item in ruw:
            if not isinstance(item, dict):
                continue
            naam = str(item.get("name", "")).strip()
            x, y = item.get("x_mm"), item.get("y_mm")
            if not naam or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            schoon.append({"name": naam, "x_mm": float(x), "y_mm": float(y)})
        return schoon

    def _write_positions(self, posities: list[dict]) -> list[dict]:
        device = self._device()
        device.setting(str, POSITIES_KEY, "[]")
        setattr(device, POSITIES_KEY, json.dumps(posities))
        # Anders staat hij er alleen tot de volgende herstart, en dan is het
        # geen geheugen maar een grap.
        try:
            self.kernel.write_configuration()
        except Exception:  # pragma: no cover - de engine mag ons niet breken
            pass
        return posities

    def save_position(self, name, x_mm=None, y_mm=None) -> dict:
        """
        Bewaar een positie. Zonder coördinaten: waar de kop nu staat.

        Dat laatste is de normale manier — je jogt naar de hoek van je mal en
        legt hem daar vast; getallen intypen kan ook, maar dan wist je ze al.
        """
        naam = str(name or "").strip()[:MAX_NAAM]
        if not naam:
            raise DesignError("Een bewaarde positie heeft een naam nodig.")

        if x_mm is None or y_mm is None:
            huidig = self._current_mm()
            if huidig is None:
                raise DesignError(
                    "Deze machine meldt geen positie, dus er valt niets te "
                    "bewaren. Vul de coördinaten met de hand in."
                )
            x_mm, y_mm = huidig
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")

        posities = [p for p in self.positions() if p["name"].lower() != naam.lower()]
        posities.append({"name": naam, "x_mm": round(x, 2), "y_mm": round(y, 2)})
        if len(posities) > MAX_POSITIES:
            raise DesignError(
                f"Meer dan {MAX_POSITIES} bewaarde posities wordt een lijst waar "
                "je in moet zoeken. Gooi er eerst een weg."
            )
        self._write_positions(posities)
        return {"name": naam, "x_mm": round(x, 2), "y_mm": round(y, 2)}

    def delete_position(self, name) -> dict:
        naam = str(name or "").strip()
        posities = [p for p in self.positions() if p["name"].lower() != naam.lower()]
        self._write_positions(posities)
        return {"deleted": naam}

    def _current_mm(self):
        """Waar de kop nu staat, in millimeters — of None als hij het niet zegt."""
        from .status import StatusReader

        positie = StatusReader(self.kernel).position(self._device())
        mm = positie.get("mm")
        if not mm or len(mm) < 2:
            return None
        return (float(mm[0]), float(mm[1]))

    # ------------------------------------------- gebruikersoorsprong (J12)
    #
    # LightBurn heeft Set Origin / Clear Origin / Go to Origin: je legt een
    # nulpunt op je werkstuk en het werk brandt daarvandaan. Dat is de handeling
    # bij het uitlijnen op een restplank — de plank ligt scheef in het bed, en
    # je wil niet je hele tekening verslepen om hem erop te krijgen.
    #
    # De engine kent het niet (grep over `core` en `ruida` op `user_origin` en
    # `set_origin`: geen treffers), dus dit is onze laag. Bewust géén wijziging
    # aan de `View` van het apparaat: die draagt ook homing en de canvasmaat, en
    # een nulpunt dat stilletjes het bed verschuift is een val. Het is een
    # verschuiving die één keer wordt toegepast, op het moment dat het werk de
    # machine in gaat — zie `Drawing.verschoven`.

    def origin(self) -> dict | None:
        """Het nulpunt van deze machine, of None als er geen gezet is."""
        try:
            device = self._device()
        except DesignError:
            return None
        try:
            device.setting(str, OORSPRONG_KEY, "")
            ruw = getattr(device, OORSPRONG_KEY, "") or ""
            if not ruw:
                return None
            waarde = json.loads(ruw)
        except Exception:
            return None
        if not isinstance(waarde, dict):
            return None
        x, y = waarde.get("x_mm"), waarde.get("y_mm")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return {"x_mm": float(x), "y_mm": float(y)}

    def set_origin(self, x_mm=None, y_mm=None) -> dict:
        """
        Leg het nulpunt vast. Zonder coördinaten: waar de kop nu staat.

        Dat laatste is de normale manier — je jogt naar de hoek van je plank en
        drukt op de knop. Getallen intypen kan, maar dan wist je ze al.
        """
        if x_mm is None or y_mm is None:
            huidig = self._current_mm()
            if huidig is None:
                raise DesignError(
                    "Deze machine meldt geen positie, dus er valt geen nulpunt "
                    "vast te leggen. Vul de coördinaten met de hand in."
                )
            x_mm, y_mm = huidig
        x = round(_finite(x_mm, "x_mm"), 2)
        y = round(_finite(y_mm, "y_mm"), 2)

        bed = self._bed_mm()
        if bed and not (0 <= x <= bed[0] and 0 <= y <= bed[1]):
            raise DesignError(
                f"Dat punt ({x:.0f},{y:.0f} mm) ligt buiten het bed van "
                f"{bed[0]:.0f}x{bed[1]:.0f} mm. Daar komt de kop niet."
            )

        device = self._device()
        device.setting(str, OORSPRONG_KEY, "")
        setattr(device, OORSPRONG_KEY, json.dumps({"x_mm": x, "y_mm": y}))
        self._bewaar()
        return {"x_mm": x, "y_mm": y}

    def clear_origin(self) -> dict:
        """Terug naar het nulpunt van de machine zelf."""
        device = self._device()
        device.setting(str, OORSPRONG_KEY, "")
        setattr(device, OORSPRONG_KEY, "")
        self._bewaar()
        return {"cleared": True}

    def _bewaar(self) -> None:
        # Anders staat het er tot de volgende herstart, en dan is het geen
        # nulpunt maar een grap.
        try:
            self.kernel.write_configuration()
        except Exception:  # pragma: no cover - de engine mag ons niet breken
            pass

    # ------------------------------------------ bijstellen tijdens een job (J11)
    #
    # LightBurn heeft in zijn Move-venster twee kolommen "Adjust Speed" en
    # "Adjust Power" waarmee je een lopende job redt in plaats van hem opnieuw
    # doet. De engine kan dit, maar niet overal: alleen de grbl-driver heeft
    # `set_power_scale`/`set_speed_scale` (realtime overrides 0x90/0x99), en hij
    # is ook de enige die `has_adjustable_power`/`has_adjustable_speed` op True
    # zet. De Ruida-driver zet snelheid en vermogen per cut-segment uit de
    # settings en heeft geen realtime kanaal ervoor.
    #
    # Dus: dezelfde regel als bij air assist en de Z-as — wat de machine kán,
    # bepaalt wat je ziet. Op een Ruida bestaan deze knoppen niet.

    ADJUST_MIN = 0.1
    ADJUST_MAX = 2.0

    def _driver(self):
        return getattr(getattr(self.kernel, "device", None), "driver", None)

    def _kan(self, wat: str) -> bool:
        driver = self._driver()
        vraag = getattr(driver, f"has_adjustable_{wat}", None)
        if vraag is None:
            return False
        try:
            return bool(vraag())
        except Exception:  # pragma: no cover - een driver die niet meewerkt
            return False

    def adjust_capabilities(self) -> dict:
        return {"power": self._kan("power"), "speed": self._kan("speed")}

    def adjustment(self) -> dict:
        """Wat er nu bijgesteld staat, als factor (1.0 = zoals ontworpen)."""
        driver = self._driver()
        caps = self.adjust_capabilities()
        return {
            "power": float(getattr(driver, "power_scale", 1.0) or 1.0)
            if caps["power"]
            else None,
            "speed": float(getattr(driver, "speed_scale", 1.0) or 1.0)
            if caps["speed"]
            else None,
            "supported": caps,
        }

    def adjust(self, power=None, speed=None) -> dict:
        """
        Snelheid en vermogen bijstellen, ook terwijl de job loopt.

        De factor is een vermenigvuldiging op wat de laag zegt, niet een nieuwe
        waarde: de laag houdt zijn instelling, want die is bewijs (hij kan uit
        een preset komen). Dit is een correctie op één brandsessie.
        """
        driver = self._driver()
        if driver is None:
            raise DesignError("Er is geen actieve machine.")
        gedaan = {}
        for naam, waarde in (("power", power), ("speed", speed)):
            if waarde is None:
                continue
            if not self._kan(naam):
                raise DesignError(
                    "Deze machine kan snelheid en vermogen niet tijdens een job "
                    "bijstellen. De driver heeft er geen realtime kanaal voor; "
                    "stop de job, wijzig de laag en start opnieuw."
                )
            factor = _finite(waarde, naam)
            if not self.ADJUST_MIN <= factor <= self.ADJUST_MAX:
                raise DesignError(
                    f"Een factor van {factor:.2f} valt buiten wat de machine "
                    f"aanneemt ({self.ADJUST_MIN:g}–{self.ADJUST_MAX:g})."
                )
            getattr(driver, f"set_{naam}_scale")(factor)
            gedaan[naam] = factor
        if not gedaan:
            raise DesignError("Geef een factor voor snelheid of vermogen op.")
        return {**self.adjustment(), "applied": gedaan}

    def unlock(self) -> dict:
        """Motoren vrijgeven, zodat je de kop met de hand kunt verzetten."""
        self._require("unlock")
        return {"output": self.runner.run("unlock")}

    def lock(self) -> dict:
        self._require("lock")
        return {"output": self.runner.run("lock")}
