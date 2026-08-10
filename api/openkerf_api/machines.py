"""
Machine catalogue, creation and settings.

MeerK40t already ships a curated catalogue of machine types under the
`dev_info/*` registry — friendly names, families and prefilled defaults — and
every device service describes its own settings through `choices/*` sheets.
Both are read here rather than hardcoded, so new upstream devices and settings
show up in our setup flow without a code change on our side.
"""

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
            }
            for device in self.kernel.services("device")
        ]

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
        self.flush()
        return {
            "path": device.path,
            "label": getattr(device, "label", device.path),
            "active": self.kernel.device.path == device.path,
        }

    def activate(self, path: str) -> dict:
        device = self._find(path)
        self.kernel.activate_service_path("device", device.path)
        return {"path": device.path, "active": True}

    def rename(self, path: str, label: str) -> dict:
        device = self._find(path)
        device.label = label
        self.kernel.signal("device;renamed", device.path, label)
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
        self.flush()
        return applied

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
