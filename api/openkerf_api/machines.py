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
# Gap E5: LightBurn has `.lbdev`, so that a manufacturer can supply a ready-made profile
# and you type nothing over on a second computer. The same shape as B7's library —
# `format`, `version`, and the content below it — but without a zip: no photos hang off a
# machine, so one readable JSON file is more honest than an archive with one file in it.
PROFILE_FORMAT = "openkerf-machine"
PROFILE_VERSION = 1
PROFILE_SUFFIX = ".openkerf-machine"

# Settings that are about *this* set-up and not about the machine type: the controller's IP
# address, this computer's serial port. They do come along — two computers beside the same
# laser have the same use for them — but the preview on import names them separately,
# because they are the first thing that does not hold elsewhere.
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
    """
    A refusal the user can act on, in the user's own terms.

    `code` is optional and exists for one reason: the interface can then say it in
    the reader's language. The message is English — the source language of this
    layer — and is what a client without a catalogue shows: curl, a script, a log.
    A raise without a code is one whose message only a developer reads.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


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
        raise MachineError(f"Unknown machine: {path}")

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
            raise MachineError(f"Unknown kind of machine: {info_key}")

        before = {device.path for device in self.kernel.services("device")}
        self.runner.run(f"device add {info_key}")
        created = [
            device
            for device in self.kernel.services("device")
            if device.path not in before
        ]
        if not created:
            raise MachineError("The engine created no machine.")

        device = created[0]
        if label:
            device.label = label
            self.kernel.signal("device;renamed", device.path, label)
        # Which catalogue entry it comes from. The engine does not keep that itself —
        # `registered_path` points at the driver, and dozens of brands share one. Without
        # this a profile (E5) cannot be recreated elsewhere.
        device.setting(str, "openkerf_info_key", "")
        device.openkerf_info_key = info_key
        self._mark_configured(device)
        # `device add` makes it active straight away; that choice should survive the
        # restart. See `_remember_active`.
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
        Recording which machine is active, at once.

        MeerK40t only writes `activated_device` at `preshutdown`
        (`device/basedevice.py:322`) and at startup otherwise falls back on
        `preferred_device`, which is `lhystudios` by default — the stand-in the kernel
        creates itself. So a headless engine that is stopped or falls over without a clean
        shutdown runs on a K40 driver after the restart instead of on the laser you chose,
        and the top bar then says "lihuiyu-device". Measured: restart the server, and the
        active device is the stand-in.

        The same key the engine uses, only written earlier; nothing changes in `meerk40t/`.
        """
        try:
            setattr(self.kernel.root, "activated_device", device.path)
            self.kernel.write_persistent("/", "activated_device", device.path)
            # And straight to disk: `write_persistent` only fills the settings in memory,
            # and those are only written out on a clean shutdown — precisely what does not
            # happen here.
            self.flush()
        except Exception:  # pragma: no cover - the engine must not break us
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
            raise MachineError("The active machine cannot be removed.")
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
            sheets.append({"sheet": "connection", "fields": extra})
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
                raise MachineError(f"Unknown setting: {attr}")
            try:
                coerced = _coerce(value, types[attr])
            except (TypeError, ValueError) as e:
                raise MachineError(f"Invalid value for {attr}: {value}") from e
            setattr(device, attr, coerced)
            applied[attr] = coerced
            # The device listens for these to re-realize its view and pipes.
            device.signal(attr, coerced)
            # And the signals the setting itself states. See `_setting_signals`: without
            # this line a setting is saved but nobody does anything with it.
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

        The engine only claims the method when the device service starts. Without this the
        setting is on the machine but the coolant registration does not know the device yet,
        and then `/api/design/capabilities` reports "no air assist" while the user has just
        set it up — or worse: the switch is there and the blower does nothing. The same call
        the drivers themselves make.
        """
        coolant = getattr(getattr(self.kernel, "root", None), "coolant", None)
        if coolant is None:
            return
        try:
            coolant.claim_coolant(device, getattr(device, "device_coolant", ""))
        except Exception:  # pragma: no cover - a driver that does not co-operate
            pass

    def _setting_signals(self, device) -> dict:
        """
        Which extra signals belong with a setting, according to the setting itself.

        The engine has an agreement for this that we were missing: a choice may carry a
        `signals` key with the codes that belong to a change, beside the setting's name. The
        wxPython GUI honours that (`gui/choicepropertypanel.py:_get_additional_signals`); we
        signalled only the name, and that is exactly one signal too few.

        What that cost: the grbl controller rebuilds its connection on `update_interface`
        (`grbl/controller.py:523`), not on `interface`. Anybody setting the interface to
        `mock` in OpenKerf got their setting saved and stayed on the old connection until a
        restart. There are thirty-seven of those declarations in the engine, in every driver —
        `coolant_changed`, `pwm_mode_changed`, `newly_autoplay`, `restart` — and
        ze vielen allemaal stil.

        The same semantics as the GUI: a string or a list, and the extra signals go out
        without arguments.
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

    # --------------------------------------------- profile uitwisselen (E5)

    def _info_key(self, device) -> str | None:
        """
        Which catalogue line this machine was created from.

        Since E5 we stamp it on the device when creating it. Machines from before that
        version do not carry it; then the provider is the best we have, and on Ruida that
        points at dozens of brands running on the same driver. The profile then reports that
        as an estimate.
        """
        device.setting(str, "openkerf_info_key", "")
        if device.openkerf_info_key:
            return device.openkerf_info_key
        provider = getattr(device, "registered_path", None)
        kandidaten = [
            entry
            for family in self.catalog()
            for entry in family["machines"]
            if entry["provider"] == provider
        ]
        return kandidaten[0]["key"] if kandidaten else None

    def export_profile(self, path: str) -> dict:
        """The whole profile of one machine, as one readable file."""
        from datetime import datetime, timezone

        device = self._find(path)
        values = {}
        for sheet in self.settings(path):
            for field in sheet["fields"]:
                # On some drivers the name is *also* in a settings sheet. It should be in
                # the file once — above, where the import can overwrite it with a name of its
                # own.
                if field["attr"] == "label":
                    continue
                values[field["attr"]] = field["value"]
        sleutel = self._info_key(device)
        if sleutel is None:
            raise MachineError(
                "It cannot be traced which type this machine comes from; "
                "a profile made from it could not be created elsewhere."
            )
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": {
                "info": sleutel,
                "provider": getattr(device, "registered_path", None),
                "label": getattr(device, "label", device.path),
                "settings": values,
            },
        }

    def read_profile(self, data) -> dict:
        """Read it and refuse at once what is not a machine profile."""
        import json
        from pathlib import Path

        if isinstance(data, (str, Path)):
            source = Path(data)
            if not source.exists():
                raise MachineError("That file is not there (any more).")
            try:
                data = json.loads(source.read_text())
            except ValueError as e:
                raise MachineError("This file is not a readable profile.") from e
        if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
            raise MachineError(
                "This file did not come from OpenKerf. A machine profile ends "
                f"in {PROFILE_SUFFIX}."
            )
        if int(data.get("version") or 0) > PROFILE_VERSION:
            raise MachineError(
                "This profile comes from a newer version of OpenKerf. Update first."
            )
        machine = data.get("machine")
        if not isinstance(machine, dict) or not machine.get("info"):
            raise MachineError("This profile does not say which machine type it is for.")
        return data

    def preview_profile(self, data) -> dict:
        """
        Wat er gaat gebeuren, vóórdat het gebeurt.

        A machine profile decides where the head goes. Blindly loading what somebody emailed
        you is exactly one step from a head running into its end stop, so this says first what
        is in it.
        """
        data = self.read_profile(data)
        machine = data["machine"]
        bekend = {
            entry["key"]: entry
            for family in self.catalog()
            for entry in family["machines"]
        }
        line = bekend.get(machine["info"])
        values = machine.get("settings") or {}
        # Only what is really filled in. The engine sets unused fields to "UNCONFIGURED";
        # showing those as "check this" on a USB machine is a warning about nothing, and that
        # teaches you to ignore warnings.
        local = {
            k: v
            for k, v in values.items()
            if k in LOCAL_ATTRS and str(v).strip() not in ("", "UNCONFIGURED", "None")
        }
        core = {
            k: values[k]
            for k in ("bedwidth", "bedheight", "interface")
            if k in values
        }
        return {
            "label": machine.get("label") or machine["info"],
            "info": machine["info"],
            "known": line is not None,
            "friendly_name": line["friendly_name"] if line else None,
            "family": line["family"] if line else None,
            "settings": len(values),
            "essential": core,
            # What does not hold elsewhere first: *this* controller's address.
            "local": local,
            "exported_at": data.get("exported_at"),
        }

    def import_profile(self, data, label: str | None = None) -> dict:
        """Create the profile as a new machine, with its settings on it."""
        data = self.read_profile(data)
        machine = data["machine"]
        name = (label or machine.get("label") or "").strip() or None
        created = self.create(machine["info"], name)

        values = machine.get("settings") or {}
        types = self._setting_types(self._find(created["path"]))
        # What this engine does not know we leave alone rather than rejecting the profile: a
        # profile from a newer MeerK40t should not block your whole set-up over one setting
        # that does not exist here.
        # On some drivers `label` is *also* in a settings sheet. Taking it along would
        # immediately overwrite the name you chose on import with the source's — two machines
        # with the same name, and that is exactly what you do not want on a second profile.
        usable = {
            k: v for k, v in values.items() if k in types and k != "label"
        }
        skipped = sorted(set(values) - set(usable))
        if usable:
            self.update_settings(created["path"], usable)
        return {
            **created,
            "applied": len(usable),
            "skipped": skipped,
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
        "title": "K40-board (CH341)",
        "kind": "co2-k40",
        "keys": ("m2-nano", "m3-nano"),
        "confidence": "waarschijnlijk",
        "why": "This is the CH341 chip on the M2 and M3 Nano boards of a K40.",
        "settings": {},
    },
    {
        "vid": 0x0471,
        "pid": 0x0999,
        "title": "Newly-besturing",
        "kind": "co2-ruida",
        "keys": ("g3v8-raylaser",),
        "confidence": "waarschijnlijk",
        "why": "This USB identity belongs to the Newly JCZ controller.",
        "settings": {},
    },
    {
        "vid": 0x9588,
        "pid": 0x9899,
        "title": "Galvo-besturing (BJJCZ / Balor)",
        "kind": "galvo",
        "keys": ("balor-fiber", "balor-fiber-mopa", "balor-co2", "balor-uv"),
        "confidence": "waarschijnlijk",
        "why": "The LMC controller of a fibre or UV galvo announces itself like this.",
        "settings": {},
    },
    {
        "vid": 0x9588,
        "pid": 0x9980,
        "title": "Galvo-besturing (BJJCZ / Balor)",
        "kind": "galvo",
        "keys": ("balor-fiber", "balor-fiber-mopa", "balor-co2", "balor-uv"),
        "confidence": "waarschijnlijk",
        "why": "The LMC controller of a fibre or UV galvo announces itself like this.",
        "settings": {},
    },
)

# Serial adapters. These chips say nothing about the laser behind them — a CH340 sits on a
# diode frame *and* on ten other devices — so the certainty is deliberately lower here and
# several proposals come with it.
SERIAL_SIGNATURES = (
    {
        "vid": 0x0403,
        "pid": 0x6001,
        "title": "FTDI-seriële poort",
        "kind": "co2-ruida",
        "keys": ("ruida-beta", "grbl-generic"),
        "confidence": "onzeker",
        "why": "A Ruida RDC6442 hangs off USB through this FTDI chip, but it is not exclusive.",
        "settings": {"interface": "usb"},
    },
    {
        "vid": 0x1A86,
        "pid": 0x7523,
        "title": "CH340-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "The CH340 is on nearly every GRBL diode frame, and on many other devices.",
        "settings": {},
    },
    {
        "vid": 0x1A86,
        "pid": 0x55D4,
        "title": "CH9102-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "The CH9102 is the successor to the CH340 on newer GRBL boards.",
        "settings": {},
    },
    {
        "vid": 0x10C4,
        "pid": 0xEA60,
        "title": "CP210x-seriële poort",
        "kind": "diode",
        "keys": ("grbl-generic", "grbl-fluidnc"),
        "confidence": "onzeker",
        "why": "The CP2102 is on ESP32 boards, FluidNC among them.",
        "settings": {},
    },
    {
        "vid": 0x2341,
        "pid": None,
        "title": "Arduino-board",
        "kind": "diode",
        "keys": ("grbl-generic",),
        "confidence": "onzeker",
        "why": "GRBL has traditionally run on an Arduino Uno with a shield.",
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
            notes.append("USB not searched: pyusb is not installed.")
            return []

        try:
            devices = list(usb.core.find(find_all=True))
        except Exception as e:  # noqa: BLE001 — libusb throws a whole zoo
            notes.append(
                "USB not searched: the operating system gave no access "
                f"to the USB bus ({type(e).__name__})."
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
            notes.append("Serial ports not searched: pyserial is missing.")
            return []

        try:
            ports = list(list_ports.comports())
        except Exception as e:  # noqa: BLE001
            notes.append(f"Serial ports not searched ({type(e).__name__}).")
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
                "Network not searched: this computer has no address in a "
                "local netwerk."
            )
            return []

        try:
            probe = ruida_probe_packet()
        except ImportError:
            notes.append("Network not searched: the Ruida module is missing from the engine.")
            return []

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", RUIDA_LISTEN_PORT))
        except OSError:
            sock.close()
            notes.append(
                f"Network not searched: port {RUIDA_LISTEN_PORT} is already in use. "
                "Something is probably already talking to a Ruida."
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
                f"Nothing on {subnet} answered on port {RUIDA_SEND_PORT}. "
                "Is the machine on and is it on the same network?"
            )

        return [
            self._candidate(
                {
                    "title": "Ruida controller on the network",
                    "kind": "co2-ruida",
                    "keys": ("ruida-beta",),
                    "confidence": "zeker",
                    "why": (
                        "This address answered the question the Ruida driver "
                        "asks when it connects."
                    ),
                },
                kind_id=f"udp:{ip}",
                transport="netwerk",
                where=ip,
                detail=f"answered on port {RUIDA_SEND_PORT}",
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
