"""
Machine catalogue, creation and settings.

MeerK40t already ships a curated catalogue of machine types under the
`dev_info/*` registry — friendly names, families and prefilled defaults — and
every device service describes its own settings through `choices/*` sheets.
Both are read here rather than hardcoded, so new upstream devices and settings
show up in our setup flow without a code change on our side.
"""

import ipaddress
import socket
import time

from .commands import CommandRunner

# Settings a first-time setup actually needs. Everything else stays available
# through the full sheet listing, but the wizard leads with these.
ESSENTIAL_ATTRS = (
    "bedwidth",
    "bedheight",
    "interface",
    "address",
    "port",
    "serial_port",
    "baud_rate",
    "home_corner",
    "flip_x",
    "flip_y",
    "swap_xy",
)

TYPE_NAMES = {bool: "bool", int: "int", float: "float", str: "str"}

# ------------------------------------------------- machineprofiel uitwisselen
#
# Gat E5: LightBurn heeft `.lbdev`, zodat een fabrikant een kant-en-klaar
# profiel kan meeleveren en je op een tweede computer niets overtypt. Zelfde
# vorm als de bibliotheek van B7 — `format`, `version`, en de inhoud eronder —
# maar zonder zip: er hangen geen foto's aan een machine, dus één leesbaar
# JSON-bestand is eerlijker dan een archief met één bestand erin.
PROFILE_FORMAT = "openkerf-machine"
PROFILE_VERSION = 1
PROFILE_SUFFIX = ".openkerf-machine"

# Instellingen die over déze opstelling gaan en niet over het machinetype: het
# IP-adres van de controller, de seriële poort van deze computer. Ze gaan wél
# mee — twee computers naast dezelfde laser hebben er hetzelfde aan — maar het
# voorbeeld bij het importeren noemt ze apart, want ze zijn het eerste dat
# elders niet klopt.
LOCAL_ATTRS = ("address", "serial_port", "port")


def _type_name(value_type) -> str:
    """
    UI-facing type. Anything exotic — Ruida registers bedwidth as `Length` —
    is edited as text, because the engine accepts unit strings like "500mm".
    """
    return TYPE_NAMES.get(value_type, "str")


def _plain(value):
    """Values must survive JSON. A Length object would dump its internals."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _coerce(value, value_type):
    if value_type is bool:
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "off")
        return bool(value)
    if value_type is int:
        return int(value)
    if value_type is float:
        return float(value)
    return str(value)


class MachineError(RuntimeError):
    pass


class MachineManager:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    # --------------------------------------------------------------- catalog

    def catalog(self) -> list[dict]:
        """The dev_info catalogue, grouped by family and ordered by priority."""
        entries = []
        for info, path, key in self.kernel.find("dev_info"):
            if not isinstance(info, dict):
                continue
            entries.append(
                {
                    "key": key,
                    "family": info.get("family") or "Overig",
                    "friendly_name": info.get("friendly_name") or key,
                    "extended_info": info.get("extended_info"),
                    "priority": info.get("priority", 0),
                    "provider": info.get("provider"),
                    "defaults": {
                        c["attr"]: c["default"]
                        for c in info.get("choices", [])
                        if isinstance(c, dict) and "attr" in c and "default" in c
                    },
                }
            )

        families: dict[str, list] = {}
        for entry in entries:
            families.setdefault(entry["family"], []).append(entry)

        result = []
        for family, machines in families.items():
            machines.sort(key=lambda m: (-m["priority"], m["friendly_name"]))
            result.append(
                {
                    "family": family,
                    "priority": max(m["priority"] for m in machines),
                    "machines": machines,
                }
            )
        result.sort(key=lambda f: (-f["priority"], f["family"]))
        return result

    # -------------------------------------------------------------- machines

    def list(self) -> list[dict]:
        active = getattr(self.kernel.device, "path", None)
        return [
            {
                "path": device.path,
                "label": getattr(device, "label", device.path),
                "provider": getattr(device, "registered_path", None),
                "active": device.path == active,
                "configured": self._configured(device),
            }
            for device in self.kernel.services("device")
        ]

    def _configured(self, device) -> bool:
        """
        Did a human set this machine up, or did the engine invent it?

        MeerK40t boots with a default lhystudios device so that the kernel
        always has something to talk to. A first-time user never chose it, and
        presenting it as "your machine, connected and ready" is a lie with
        consequences — you would be spooling K40 codes at whatever is really on
        the other end. We therefore stamp every machine that came out of our
        own wizard, and treat the rest as the engine's placeholder.
        """
        device.setting(bool, "openkerf_configured", False)
        return bool(device.openkerf_configured)

    def _mark_configured(self, device) -> None:
        device.setting(bool, "openkerf_configured", False)
        device.openkerf_configured = True

    def _find(self, path):
        for device in self.kernel.services("device"):
            if device.path == path:
                return device
        raise MachineError(f"Onbekende machine: {path}")

    def create(self, info_key: str, label: str | None = None) -> dict:
        """
        Add a machine from the catalogue and make it active.

        `device add -l <label>` is broken upstream (basedevice.py does
        `dict(choices)` on a *list* of dicts, which mangles it into
        {"attr": "default"} and then crashes), so we add without a label and
        set it afterwards. Reported as an upstream issue; remove the second
        step once that is fixed.
        """
        known = {entry["key"] for family in self.catalog() for entry in family["machines"]}
        if info_key not in known:
            raise MachineError(f"Onbekend machinetype: {info_key}")

        before = {device.path for device in self.kernel.services("device")}
        self.runner.run(f"device add {info_key}")
        created = [
            device
            for device in self.kernel.services("device")
            if device.path not in before
        ]
        if not created:
            raise MachineError("De engine heeft geen machine aangemaakt.")

        device = created[0]
        if label:
            device.label = label
            self.kernel.signal("device;renamed", device.path, label)
        # Uit welke catalogusregel hij komt. De engine bewaart dat zelf niet —
        # `registered_path` wijst naar de driver, en tientallen merken delen er
        # één. Zonder dit is een profiel (E5) elders niet terug te maken.
        device.setting(str, "openkerf_info_key", "")
        device.openkerf_info_key = info_key
        self._mark_configured(device)
        # `device add` maakt hem meteen actief; die keuze hoort de herstart te
        # overleven. Zie `_remember_active`.
        if getattr(self.kernel.device, "path", None) == device.path:
            self._remember_active(device)
        self.flush()
        return {
            "path": device.path,
            "label": getattr(device, "label", device.path),
            "active": self.kernel.device.path == device.path,
        }

    def activate(self, path: str) -> dict:
        device = self._find(path)
        self.kernel.activate_service_path("device", device.path)
        self._remember_active(device)
        return {"path": device.path, "active": True}

    def _remember_active(self, device) -> None:
        """
        Vastleggen welke machine actief is, meteen.

        MeerK40t schrijft `activated_device` pas bij `preshutdown`
        (`device/basedevice.py:322`) en valt bij het opstarten anders terug op
        `preferred_device`, en dat is standaard `lhystudios` — de
        plaatsvervanger die de kernel zelf aanmaakt. Een headless engine die
        gestopt of omgevallen wordt zonder nette afsluiting draait dus na de
        herstart op een K40-driver in plaats van op de laser die je koos, en de
        bovenbalk zegt dan "lihuiyu-device". Gemeten: server herstarten, en het
        actieve apparaat is de plaatsvervanger.

        Dezelfde sleutel als de engine gebruikt, alleen eerder geschreven; er
        verandert niets in `meerk40t/`.
        """
        try:
            setattr(self.kernel.root, "activated_device", device.path)
            self.kernel.write_persistent("/", "activated_device", device.path)
            # En meteen naar schijf: `write_persistent` vult alleen de
            # instellingen in het geheugen, en die worden pas bij een nette
            # afsluiting weggeschreven — precies wat hier niet gebeurt.
            self.flush()
        except Exception:  # pragma: no cover - de engine mag ons niet breken
            pass

    def rename(self, path: str, label: str) -> dict:
        device = self._find(path)
        device.label = label
        self.kernel.signal("device;renamed", device.path, label)
        # Naming the engine's default device is how you adopt it: from here on
        # it is a machine someone chose, not a placeholder.
        self._mark_configured(device)
        self.flush()
        return {"path": device.path, "label": label}

    def remove(self, path: str) -> dict:
        device = self._find(path)
        if self.kernel.device is device:
            # Destroying the active service leaves the kernel without a device.
            raise MachineError("De actieve machine kan niet verwijderd worden.")
        device.destroy()
        self.flush()
        return {"removed": path}

    # -------------------------------------------------------------- settings

    def settings(self, path: str, essential_only: bool = False) -> list[dict]:
        """
        The device's own settings sheets, as the engine describes them:
        label, tip, type and current value per attribute.
        """
        device = self._find(path)
        sheets = []
        described: set[str] = set()
        for sheet_path in sorted(device.match("choices")):
            entries = device.lookup(sheet_path)
            if not isinstance(entries, (list, tuple)):
                continue
            fields = []
            for choice in entries:
                if not isinstance(choice, dict) or "attr" not in choice:
                    continue
                attr = choice["attr"]
                if essential_only and attr not in ESSENTIAL_ATTRS:
                    continue
                if not hasattr(device, attr):
                    continue
                value_type = choice.get("type", str)
                fields.append(
                    {
                        "attr": attr,
                        "label": choice.get("label") or attr,
                        "tip": choice.get("tip"),
                        "type": _type_name(value_type),
                        "value": _plain(getattr(device, attr)),
                        "options": choice.get("choices"),
                        "section": choice.get("section"),
                    }
                )
                described.add(attr)
            if fields:
                sheets.append({"sheet": sheet_path.split("/")[-1], "fields": fields})

        extra = self._undeclared_essentials(device, described)
        if extra:
            sheets.append({"sheet": "verbinding", "fields": extra})
        return sheets

    def _undeclared_essentials(self, device, described: set) -> list[dict]:
        """
        Settings that exist on the device but are in no choices sheet.

        Ruida creates `interface` and `address` with a plain `setting()` call,
        so the GUI's sheet mechanism never sees them — yet picking USB or UDP
        is exactly what first-time setup is about. We surface those by name,
        inferring the type from the current value.
        """
        fields = []
        for attr in ESSENTIAL_ATTRS:
            if attr in described or not hasattr(device, attr):
                continue
            value = getattr(device, attr)
            if not isinstance(value, (str, int, float, bool)):
                continue
            fields.append(
                {
                    "attr": attr,
                    "label": attr.replace("_", " ").capitalize(),
                    "tip": None,
                    "type": _type_name(type(value)),
                    "value": value,
                    "options": ["usb", "udp"] if attr == "interface" else None,
                    "section": None,
                }
            )
        return fields

    def update_settings(self, path: str, values: dict) -> dict:
        device = self._find(path)
        types = self._setting_types(device)
        extra = self._setting_signals(device)
        applied = {}
        for attr, value in values.items():
            if attr not in types:
                raise MachineError(f"Onbekende instelling: {attr}")
            try:
                coerced = _coerce(value, types[attr])
            except (TypeError, ValueError) as e:
                raise MachineError(f"Ongeldige waarde voor {attr}: {value}") from e
            setattr(device, attr, coerced)
            applied[attr] = coerced
            # The device listens for these to re-realize its view and pipes.
            device.signal(attr, coerced)
            # En de signalen die de instelling zélf opgeeft. Zie
            # `_setting_signals`: zonder deze regel wordt een instelling wel
            # opgeslagen maar doet er niemand iets mee.
            for code in extra.get(attr, ()):
                device.signal(code)
        # Same reasoning as in rename(): setting a bed size on the engine's
        # default device is an act of adoption.
        self._mark_configured(device)
        if "device_coolant" in applied:
            self._claim_coolant(device)
        self.flush()
        return applied

    def _claim_coolant(self, device) -> None:
        """
        De air-assistmethode meteen laten aanhaken (besluit B11).

        De engine claimt de methode alleen bij het opstarten van de
        device-service. Zonder dit staat de instelling wel op de machine maar
        kent de coolant-registratie het apparaat nog niet, en dan meldt
        `/api/design/capabilities` "geen air assist" terwijl de gebruiker hem
        net heeft ingesteld — of erger: de schakelaar staat er wel en de blazer
        doet niets. Dezelfde aanroep als de drivers zelf doen.
        """
        coolant = getattr(getattr(self.kernel, "root", None), "coolant", None)
        if coolant is None:
            return
        try:
            coolant.claim_coolant(device, getattr(device, "device_coolant", ""))
        except Exception:  # pragma: no cover - een driver die niet meewerkt
            pass

    def _setting_signals(self, device) -> dict:
        """
        Welke extra signalen bij een instelling horen, volgens de instelling zelf.

        De engine kent hier een afspraak voor die wij misten: een keuze mag een
        `signals`-sleutel dragen met de codes die bij een wijziging horen, naast
        de naam van de instelling. De wxPython-GUI honoreert dat
        (`gui/choicepropertypanel.py:_get_additional_signals`); wij seinden
        alleen de naam, en dat is precies één signaal te weinig.

        Wat dat kostte: de grbl-controller bouwt zijn verbinding opnieuw op bij
        `update_interface` (`grbl/controller.py:523`), niet bij `interface`. Wie
        in OpenKerf de interface op `mock` zette, kreeg zijn instelling
        opgeslagen en bleef op de oude verbinding zitten tot een herstart. Er
        staan zevenendertig van die declaraties in de engine, in elke driver —
        `coolant_changed`, `pwm_mode_changed`, `newly_autoplay`, `restart` — en
        ze vielen allemaal stil.

        Zelfde semantiek als de GUI: een string of een lijst, en de extra
        signalen gaan zonder argumenten de deur uit.
        """
        signals = {}
        for sheet_path in device.match("choices"):
            entries = device.lookup(sheet_path)
            if not isinstance(entries, (list, tuple)):
                continue
            for choice in entries:
                if not isinstance(choice, dict) or "attr" not in choice:
                    continue
                declared = choice.get("signals")
                if isinstance(declared, str):
                    signals[choice["attr"]] = (declared,)
                elif isinstance(declared, (list, tuple)):
                    signals[choice["attr"]] = tuple(declared)
        return signals

    def _setting_types(self, device) -> dict:
        types = {}
        for sheet_path in device.match("choices"):
            entries = device.lookup(sheet_path)
            if not isinstance(entries, (list, tuple)):
                continue
            for choice in entries:
                if isinstance(choice, dict) and "attr" in choice:
                    types[choice["attr"]] = choice.get("type", str)
        # Settings created with a bare setting() call carry no sheet entry; they
        # are still editable, with the type taken from the current value.
        for attr in ESSENTIAL_ATTRS:
            if attr not in types and hasattr(device, attr):
                value = getattr(device, attr)
                if isinstance(value, (str, int, float, bool)):
                    types[attr] = type(value)
        return types

    def flush(self):
        """Persist settings so a machine survives a restart of the engine."""
        self.runner.run("flush")

    # --------------------------------------------- profiel uitwisselen (E5)

    def _info_key(self, device) -> str | None:
        """
        Uit welke catalogusregel deze machine gemaakt is.

        Sinds E5 stempelen we hem bij het aanmaken op het apparaat. Machines van
        vóór die versie dragen hem niet; dan is de provider het beste dat we
        hebben, en die wijst bij Ruida naar tientallen merken die op dezelfde
        driver draaien. Het profiel meldt dat dan als schatting.
        """
        device.setting(str, "openkerf_info_key", "")
        if device.openkerf_info_key:
            return device.openkerf_info_key
        provider = getattr(device, "registered_path", None)
        kandidaten = [
            entry
            for familie in self.catalog()
            for entry in familie["machines"]
            if entry["provider"] == provider
        ]
        return kandidaten[0]["key"] if kandidaten else None

    def export_profile(self, path: str) -> dict:
        """Het hele profiel van één machine, als één leesbaar bestand."""
        from datetime import datetime, timezone

        device = self._find(path)
        waarden = {}
        for blad in self.settings(path):
            for veld in blad["fields"]:
                # De naam staat bij sommige drivers óók in een instellingenblad.
                # Hij hoort één keer in het bestand te staan — hierboven, waar
                # het importeren hem kan overschrijven met een eigen naam.
                if veld["attr"] == "label":
                    continue
                waarden[veld["attr"]] = veld["value"]
        sleutel = self._info_key(device)
        if sleutel is None:
            raise MachineError(
                "Van deze machine is niet te achterhalen uit welk type hij komt; "
                "een profiel eruit zou elders niet aan te maken zijn."
            )
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": {
                "info": sleutel,
                "provider": getattr(device, "registered_path", None),
                "label": getattr(device, "label", device.path),
                "settings": waarden,
            },
        }

    def read_profile(self, data) -> dict:
        """Inlezen en meteen afwijzen wat geen machineprofiel is."""
        import json
        from pathlib import Path

        if isinstance(data, (str, Path)):
            bron = Path(data)
            if not bron.exists():
                raise MachineError("Dat bestand is er niet (meer).")
            try:
                data = json.loads(bron.read_text())
            except ValueError as e:
                raise MachineError("Dit bestand is geen leesbaar profiel.") from e
        if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
            raise MachineError(
                "Dit bestand komt niet uit OpenKerf. Een machineprofiel eindigt "
                f"op {PROFILE_SUFFIX}."
            )
        if int(data.get("version") or 0) > PROFILE_VERSION:
            raise MachineError(
                "Dit profiel komt uit een nieuwere versie van OpenKerf. Werk eerst bij."
            )
        machine = data.get("machine")
        if not isinstance(machine, dict) or not machine.get("info"):
            raise MachineError("Dit profiel zegt niet om welk machinetype het gaat.")
        return data

    def preview_profile(self, data) -> dict:
        """
        Wat er gaat gebeuren, vóórdat het gebeurt.

        Een machineprofiel bepaalt waar de kop heen gaat. Blind inladen wat
        iemand je mailde is precies één stap van een kop die tegen zijn
        eindaanslag loopt, dus dit vertelt eerst wat erin zit.
        """
        data = self.read_profile(data)
        machine = data["machine"]
        bekend = {
            entry["key"]: entry
            for familie in self.catalog()
            for entry in familie["machines"]
        }
        regel = bekend.get(machine["info"])
        waarden = machine.get("settings") or {}
        # Alleen wat écht ingevuld is. De engine zet niet-gebruikte velden op
        # "UNCONFIGURED"; die als "controleer dit" tonen bij een USB-machine is
        # een waarschuwing over niets, en daar leer je waarschuwingen van negeren.
        lokaal = {
            k: v
            for k, v in waarden.items()
            if k in LOCAL_ATTRS and str(v).strip() not in ("", "UNCONFIGURED", "None")
        }
        kern = {
            k: waarden[k]
            for k in ("bedwidth", "bedheight", "interface")
            if k in waarden
        }
        return {
            "label": machine.get("label") or machine["info"],
            "info": machine["info"],
            "known": regel is not None,
            "friendly_name": regel["friendly_name"] if regel else None,
            "family": regel["family"] if regel else None,
            "settings": len(waarden),
            "essential": kern,
            # Wat elders als eerste niet klopt: het adres van déze controller.
            "local": lokaal,
            "exported_at": data.get("exported_at"),
        }

    def import_profile(self, data, label: str | None = None) -> dict:
        """Het profiel als nieuwe machine aanmaken, met zijn instellingen erop."""
        data = self.read_profile(data)
        machine = data["machine"]
        naam = (label or machine.get("label") or "").strip() or None
        gemaakt = self.create(machine["info"], naam)

        waarden = machine.get("settings") or {}
        types = self._setting_types(self._find(gemaakt["path"]))
        # Wat deze engine niet kent, laten we liggen in plaats van het profiel af
        # te wijzen: een profiel uit een nieuwere MeerK40t hoort niet je hele
        # inrichting te blokkeren om één instelling die hier niet bestaat.
        # `label` staat bij sommige drivers óók in een instellingenblad. Hem
        # meenemen zou de naam die je bij het importeren koos meteen weer
        # overschrijven met die van de bron — twee machines met dezelfde naam,
        # en dat is precies wat je bij een tweede profiel niet wilt.
        bruikbaar = {
            k: v for k, v in waarden.items() if k in types and k != "label"
        }
        overgeslagen = sorted(set(waarden) - set(bruikbaar))
        if bruikbaar:
            self.update_settings(gemaakt["path"], bruikbaar)
        return {
            **gemaakt,
            "applied": len(bruikbaar),
            "skipped": overgeslagen,
        }

    # ------------------------------------------------------------------ scan

    def scan(self, network: bool = True, seconds: float = 2.0) -> dict:
        """
        Look for machines. Reads only — see MachineScanner.

        The catalogue is passed in so suggestions carry the engine's own
        friendly names, and so a suggestion for a plugin that is not loaded
        quietly disappears instead of producing a key that `create` refuses.
        """
        return MachineScanner(self.catalog()).scan(network=network, seconds=seconds)


# ============================================================== detection ===
#
# Searching is reading (BESLISSINGEN.md, B6). Nothing in this section creates a
# device, activates a service, writes a setting or opens a session with a
# machine: it enumerates USB and serial devices, and asks the network one
# question. What is found is a *proposal*; only the user's confirmation turns it
# into a machine, through the ordinary create/settings routes.

# The Ruida listens on 50200 and answers from 40200. Not configurable — see
# meerk40t/ruida/udp_transport.py.
RUIDA_SEND_PORT = 50200
RUIDA_LISTEN_PORT = 40200
RUIDA_MAGIC = 0x88  # The device default (ruida/device.py, choices "magic").

# Chips and boards we can recognise, with the catalogue keys they point at.
# Vendor/product come from the drivers themselves (ch341/libusb.py,
# newly/usb_connection.py, balormk/usb_connection.py, ruida/usb_transport.py),
# so this table stays true to what the engine would actually try to talk to.
USB_SIGNATURES = (
    {
        "vid": 0x1A86,
        "pid": 0x5512,
        "title": "K40-bord (CH341)",
        "kind": "co2-k40",
        "keys": ("m2-nano", "m3-nano"),
        "confidence": "waarschijnlijk",
        "why": "Dit is de CH341-chip die op de M2- en M3-Nano-borden van een K40 zit.",
        "settings": {},
    },
    {
        "vid": 0x0471,
        "pid": 0x0999,
        "title": "Newly-besturing",
        "kind": "co2-ruida",
        "keys": ("g3v8-raylaser",),
        "confidence": "waarschijnlijk",
        "why": "Deze USB-identiteit hoort bij de Newly JCZ-besturing.",
        "settings": {},
    },
    {
        "vid": 0x9588,
        "pid": 0x9899,
        "title": "Galvo-besturing (BJJCZ / Balor)",
        "kind": "galvo",
        "keys": ("balor-fiber", "balor-fiber-mopa", "balor-co2", "balor-uv"),
        "confidence": "waarschijnlijk",
        "why": "De LMC-controller van een fiber- of UV-galvo meldt zich zo aan.",
        "settings": {},
    },
    {
        "vid": 0x9588,
        "pid": 0x9980,
        "title": "Galvo-besturing (BJJCZ / Balor)",
        "kind": "galvo",
        "keys": ("balor-fiber", "balor-fiber-mopa", "balor-co2", "balor-uv"),
        "confidence": "waarschijnlijk",
        "why": "De LMC-controller van een fiber- of UV-galvo meldt zich zo aan.",
        "settings": {},
    },
)

# Serial adapters. These chips zeggen niets over de laser erachter — een CH340
# zit op een diodeframe én op tien andere apparaten — dus de zekerheid is hier
# bewust lager en er staan meerdere voorstellen bij.
SERIAL_SIGNATURES = (
    {
        "vid": 0x0403,
        "pid": 0x6001,
        "title": "FTDI-seriële poort",
        "kind": "co2-ruida",
        "keys": ("ruida-beta", "grbl-generic"),
        "confidence": "onzeker",
        "why": "Een Ruida RDC6442 hangt via deze FTDI-chip aan USB, maar hij is niet exclusief.",
        "settings": {"interface": "usb"},
    },
    {
        "vid": 0x1A86,
        "pid": 0x7523,
        "title": "CH340-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "De CH340 zit op vrijwel elk GRBL-diodeframe, en op veel andere apparaten.",
        "settings": {},
    },
    {
        "vid": 0x1A86,
        "pid": 0x55D4,
        "title": "CH9102-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "De CH9102 is de opvolger van de CH340 op nieuwere GRBL-borden.",
        "settings": {},
    },
    {
        "vid": 0x10C4,
        "pid": 0xEA60,
        "title": "CP210x-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "De CP2102 zit op ESP32-borden, waaronder FluidNC.",
        "settings": {},
    },
    {
        "vid": 0x2341,
        "pid": None,
        "title": "Arduino-bord",
        "kind": "diode",
        "keys": ("grbl-generic",),
        "confidence": "onzeker",
        "why": "GRBL draait van oudsher op een Arduino Uno met een schild.",
        "settings": {},
    },
)


def ruida_probe_packet(magic: int = RUIDA_MAGIC) -> bytes:
    """
    The packet MeerK40t itself uses to ask a Ruida whether it is there.

    `ENQ` is an enquiry: the controller answers with an ACK and does not move,
    fire or change anything. We build it with the engine's own swizzle and
    checksum so the bytes on the wire are identical to a normal handshake —
    this is the same question the driver asks on every connect, no more.
    """
    from meerk40t.ruida.rdjob import ENQ, encode_bytes

    swizzled = encode_bytes(ENQ, magic=magic)
    return (sum(swizzled) & 0xFFFF).to_bytes(2, "big") + swizzled


class MachineScanner:
    """
    Finds candidate machines on USB, serial and the local network.

    Never touches the kernel: it takes the catalogue as data and returns
    proposals. That is what makes "searching is reading" checkable rather than
    a promise in a comment.
    """

    #: Hard ceiling on the network scan, whatever the caller asks for. A scan
    #: that hangs for minutes is worse than one that finds nothing.
    MAX_SECONDS = 6.0

    def __init__(self, catalog: list[dict] | None = None):
        self.by_key = {
            machine["key"]: machine
            for family in (catalog or [])
            for machine in family["machines"]
        }

    # ------------------------------------------------------------- entry point

    def scan(self, network: bool = True, seconds: float = 2.0) -> dict:
        started = time.monotonic()
        notes: list[str] = []
        candidates: list[dict] = []
        searched: list[str] = []

        candidates += self._scan_usb(notes, searched)
        candidates += self._scan_serial(notes, searched)
        if network:
            candidates += self._scan_network(notes, searched, seconds)

        return {
            "candidates": candidates,
            "searched": searched,
            "notes": notes,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    # -------------------------------------------------------------------- usb

    def _scan_usb(self, notes: list, searched: list) -> list[dict]:
        try:
            import usb.core
        except ImportError:
            notes.append("USB niet doorzocht: pyusb is niet geïnstalleerd.")
            return []

        try:
            devices = list(usb.core.find(find_all=True))
        except Exception as e:  # noqa: BLE001 — libusb throws a whole zoo
            notes.append(
                "USB niet doorzocht: het besturingssysteem gaf geen toegang "
                f"tot de USB-bus ({type(e).__name__})."
            )
            return []

        searched.append("USB")
        found = []
        for device in devices:
            signature = self._match(
                USB_SIGNATURES, getattr(device, "idVendor", None), getattr(device, "idProduct", None)
            )
            if signature is None:
                continue
            found.append(
                self._candidate(
                    signature,
                    kind_id=f"usb:{signature['vid']:04x}:{signature['pid']:04x}:"
                    f"{getattr(device, 'bus', 0)}.{getattr(device, 'address', 0)}",
                    transport="usb",
                    where=f"USB {signature['vid']:04x}:{signature['pid']:04x}",
                    settings=dict(signature["settings"]),
                )
            )
        return found

    # ----------------------------------------------------------------- serial

    def _scan_serial(self, notes: list, searched: list) -> list[dict]:
        try:
            from serial.tools import list_ports
        except ImportError:
            notes.append("Seriële poorten niet doorzocht: pyserial ontbreekt.")
            return []

        try:
            ports = list(list_ports.comports())
        except Exception as e:  # noqa: BLE001
            notes.append(f"Seriële poorten niet doorzocht ({type(e).__name__}).")
            return []

        searched.append("seriële poorten")
        found = []
        for port in ports:
            signature = self._match(SERIAL_SIGNATURES, port.vid, port.pid)
            if signature is None:
                continue
            settings = dict(signature["settings"])
            settings["serial_port"] = port.device
            found.append(
                self._candidate(
                    signature,
                    kind_id=f"serial:{port.device}",
                    transport="serieel",
                    where=port.device,
                    detail=(port.description or "").strip() or None,
                    settings=settings,
                )
            )
        return found

    # ---------------------------------------------------------------- network

    def _scan_network(self, notes: list, searched: list, seconds: float) -> list[dict]:
        seconds = max(0.5, min(float(seconds), self.MAX_SECONDS))
        subnet = self._local_subnet()
        if subnet is None:
            notes.append(
                "Netwerk niet doorzocht: deze computer heeft geen adres in een "
                "lokaal netwerk."
            )
            return []

        try:
            probe = ruida_probe_packet()
        except ImportError:
            notes.append("Netwerk niet doorzocht: de Ruida-module ontbreekt in de engine.")
            return []

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", RUIDA_LISTEN_PORT))
        except OSError:
            sock.close()
            notes.append(
                f"Netwerk niet doorzocht: poort {RUIDA_LISTEN_PORT} is al in gebruik. "
                "Waarschijnlijk praat er al iets met een Ruida."
            )
            return []

        searched.append(f"netwerk {subnet}")
        replies: dict[str, bytes] = {}
        try:
            sock.settimeout(0.2)
            for host in subnet.hosts():
                try:
                    sock.sendto(probe, (str(host), RUIDA_SEND_PORT))
                except OSError:
                    continue
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    data, address = sock.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                replies.setdefault(address[0], data)
        finally:
            sock.close()

        if not replies:
            notes.append(
                f"Op {subnet} antwoordde niets op poort {RUIDA_SEND_PORT}. "
                "Staat de machine aan en hangt hij aan hetzelfde netwerk?"
            )

        return [
            self._candidate(
                {
                    "title": "Ruida-besturing op het netwerk",
                    "kind": "co2-ruida",
                    "keys": ("ruida-beta",),
                    "confidence": "zeker",
                    "why": (
                        "Dit adres antwoordde op de vraag die de Ruida-driver "
                        "ook stelt bij het verbinden."
                    ),
                },
                kind_id=f"udp:{ip}",
                transport="netwerk",
                where=ip,
                detail=f"antwoordde op poort {RUIDA_SEND_PORT}",
                settings={"interface": "udp", "address": ip},
            )
            for ip in sorted(replies, key=_ip_sort_key)
        ]

    @staticmethod
    def _local_subnet():
        """
        The /24 this computer sits in.

        There is no portable way to read the netmask without extra packages, so
        we assume /24 — the shape of virtually every workshop network — and say
        out loud which range we searched. A UDP connect() sends no packets; it
        only makes the OS pick the interface it would route over.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1: routed nowhere.
            ip = sock.getsockname()[0]
        except OSError:
            return None
        finally:
            sock.close()
        if not ip or ip.startswith("127."):
            return None
        try:
            return ipaddress.ip_network(f"{ip}/24", strict=False)
        except ValueError:
            return None

    # ----------------------------------------------------------------- shared

    @staticmethod
    def _match(signatures, vid, pid):
        if vid is None:
            return None
        for signature in signatures:
            if signature["vid"] != vid:
                continue
            if signature["pid"] is None or signature["pid"] == pid:
                return signature
        return None

    def _candidate(
        self, signature, kind_id, transport, where, settings, detail=None
    ) -> dict:
        suggestions = []
        for key in signature["keys"]:
            entry = self.by_key.get(key)
            if entry is None:
                continue  # Plugin not loaded: proposing it would only 409.
            suggestions.append(
                {
                    "key": key,
                    "label": entry["friendly_name"],
                    "family": entry["family"],
                }
            )
        return {
            "id": kind_id,
            "transport": transport,
            "title": signature["title"],
            "where": where,
            "detail": detail,
            "kind": signature["kind"],
            "confidence": signature["confidence"] if suggestions else "onzeker",
            "why": signature["why"],
            "suggestions": suggestions,
            "settings": settings,
        }


def _ip_sort_key(ip: str):
    try:
        return int(ipaddress.ip_address(ip))
    except ValueError:
        return 0
