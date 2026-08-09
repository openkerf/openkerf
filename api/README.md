# openkerf-api

Fase 1 van OpenKerf: een **read-only** status-API naast de MeerK40t-engine.

Dit pakket wijzigt niets in MeerK40t. Het registreert zichzelf via de setuptools
entry-pointgroep `meerk40t.extension`, waardoor MeerK40t het bij het opstarten
automatisch als externe plugin oppikt (`meerk40t/external_plugins.py`).

## Installatie

```bash
pip install -e ".[dev]"      # naast een bestaande meerk40t-installatie
```

## Starten

De plugin voegt één console-commando toe, met dezelfde vorm als upstream's
`webserver`:

```bash
meerk40t --no-gui -d -e "openkerf -p 8080"          # alleen localhost
meerk40t --no-gui -d -e "openkerf -p 8080 -b 0.0.0.0"  # ook vanaf het LAN
meerk40t --no-gui -e "openkerf -q"                  # stoppen
```

Anders dan de MeerK40t-webserver (die hardcoded op `127.0.0.1` bindt) is het
bind-adres hier een optie, zodat de PWA op telefoon of tablet erbij kan.

## Endpoints

| Endpoint | Doel |
|---|---|
| `GET /api/health` | liveness + aantal WebSocket-clients |
| `GET /api/status` | volledige snapshot (kernel, devices, posities, spooler) |
| `GET /api/devices` | alleen de devicelijst |
| `WS /api/ws` | live: snapshot bij connect, daarna signalen + heartbeat (2 s) |
| `GET /` | kale devpagina die de WebSocket toont — handig om de keten te zien |

Voorbeeld:

```json
{
  "kernel": { "name": "MeerK40t", "version": "0.9.9040 pkg" },
  "devices": [{
    "label": "lihuiyu-device", "path": "lhystudios", "active": true,
    "laser_status": "idle",
    "position": { "native": [0, 0], "mm": [0.0, 0.0], "state": ["idle", "idle"] },
    "spooler": { "present": true, "idle": true, "queue_length": 0, "jobs": [] }
  }]
}
```

## Read-only, met opzet

Er is geen endpoint dat de kop beweegt, een job start of een console-commando
uitvoert. Binnenkomende WebSocket-frames worden weggegooid. `test_api.py`
bewaakt dat: een test faalt zodra er een andere HTTP-methode dan GET/HEAD
bijkomt. Schrijfacties komen pas in fase 2, met de machine erbij.

## Hoe het aan de engine hangt

- **Status lezen** gebeurt via `device.native` / `device.current` (door alle
  drivers geïmplementeerd) en `driver.status()` voor de state-vlaggen. Alle
  toegang is defensief: device-attributen zijn vaak properties die hardware
  aanraken, dus een gewone `getattr` kan gooien.
- **Live updates** komen van kernel-signalen (`driver;position`, `spooler;queue`,
  `spooler;completed`, `pipe;usb_status`, `pipe;running`, `warn_state_update`).
  Die worden op de kernelthread gedispatcht (~20 Hz); de brug zet ze met
  `loop.call_soon_threadsafe` op de asyncio-loop van uvicorn.
- **Heartbeat** van 2 s stuurt een volledige snapshot, zodat een client die een
  signaal mist alsnog convergeert.

## Tests

```bash
python -m pytest tests -q      # 13 tests, draait op een echte MeerK40t-kernel
```

De tests starten een kernel via `tests/conftest.py` (naar het model van
upstream `test/bootstrap.py`) met een dummy device, dus er is geen hardware nodig.
