# openkerf-api

De API-laag van OpenKerf, naast de MeerK40t-engine: live status, jobcontrole en
machinebeheer.

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
| `GET /api/capabilities` | welke acties het **actieve** device ondersteunt + of een token nodig is |
| `WS /api/ws` | live: snapshot bij connect, daarna signalen + heartbeat (2 s) |
| `POST /api/job/load` | multipart upload; laadt het bestand in de elementenboom |
| `POST /api/job/start` | plant de operaties en zet de job in de spooler |
| `POST /api/job/pause` · `/resume` · `/stop` | realtime jobcontrole |
| `POST /api/spooler/clear` | wachtrij legen |
| `GET /api/machines/catalog` | MeerK40t's eigen machinecatalogus, gegroepeerd per familie |
| `GET /api/machines` · `POST /api/machines` | machines tonen / toevoegen |
| `POST /api/machines/{path}/activate` · `/rename` · `DELETE` | machine kiezen, hernoemen, verwijderen |
| `GET`/`PATCH /api/machines/{path}/settings` | instellingen lezen en wijzigen (`?essential=true` voor de setup) |
| `GET /` | de frontend (met `-f`), anders een kale devpagina |

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

## Schrijfacties: afgebakend en bewaakt

De schrijfroutes hierboven zijn de **volledige** lijst. Er is geen endpoint dat
de kop beweegt, jogt of de laser aanzet — dat is fase 3 — en er is geen
endpoint dat willekeurige console-commando's uitvoert. Binnenkomende
WebSocket-frames worden weggegooid. Twee tests bewaken dat: één die de set
POST-routes exact vastlegt, en één die eist dat elke POST-route de
`require_write`-dependency draagt.

**Token.** Lezen mag altijd. Schrijven mag zonder token zolang de API op
loopback luistert; zodra je `-b 0.0.0.0` gebruikt (nodig voor de telefoon) is
een token verplicht, als `Authorization: Bearer <token>` of `X-OpenKerf-Token`.
De API genereert er een bij het starten en logt hem op het console-kanaal; met
`-t <token>` geef je een eigen waarde mee.

**Serialisatie.** Console-commando's muteren gedeelde kernelstaat en HTTP-verzoeken
komen binnen op uvicorn-threads. Alle uitvoering loopt daarom door één
`CommandRunner` met een lock, zodat twee verzoeken niet halverwege de
plan-pijplijn door elkaar lopen.

**Device-afhankelijkheid.** `pause`, `resume` en `estop` worden geregistreerd door
de device-service (Ruida en Lihuiyu doen dat, het dummy-device niet), niet door
de kernel. `/api/capabilities` zegt per actief device wat er kan; de frontend
zet knoppen daarop uit. Een niet-ondersteunde actie geeft een nette 409 met de
console-uitvoer erbij, geen 500.

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

## Machine-setup

De catalogus komt uit MeerK40t's `dev_info`-registry (9 families, 46 types) en de
instellingen uit de `choices/*`-sheets die elk device zelf registreert. Niets is
hardcoded, dus nieuwe upstream-devices en -instellingen verschijnen vanzelf.

Twee dingen die de engine niet vanzelf goed doet, en die hier opgevangen worden:

1. **`device add -l "<label>"` crasht upstream.** `basedevice.py` doet `dict(choices)`
   op een *lijst* van dicts, wat er `{"attr": "default"}` van maakt; het device
   struikelt daarna over `'str' object has no attribute 'get'`. De wxPython-GUI
   gebruikt exact dit pad. Wij maken de machine zonder label aan en zetten
   `device.label` daarna zelf. `test_create_applies_a_custom_label` faalt zodra
   iemand die omweg weghaalt voordat upstream gerepareerd is.
2. **Verbindingsinstellingen staan in geen enkele sheet.** Ruida maakt `interface`
   en `address` met een kale `setting()`-aanroep, dus de sheet-mechaniek van de GUI
   ziet ze niet — terwijl USB-of-UDP kiezen juist de kern van de eerste setup is.
   Die halen we er op naam bij, met het type afgeleid uit de huidige waarde.

Waarden worden JSON-veilig gemaakt: Ruida typeert `bedwidth` als `Length`, en dat
object zou anders zijn interne velden uitstorten in de response.

## Tests

```bash
python -m pytest tests -q      # 55 tests, draait op een echte MeerK40t-kernel
```

De tests starten een kernel via `tests/conftest.py` (naar het model van
upstream `test/bootstrap.py`) met een dummy device, dus er is geen hardware nodig.
