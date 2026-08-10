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
| `GET /api/design` | het ontwerp: elementcontouren (SVG-pad in Tats) + operaties |
| `POST /api/design/move` · `/resize` · `/rotate` | selectie verplaatsen, exact maatvoeren, draaien |
| `POST /api/design/assign` · `/unassign` | selectie in of uit een bewerking (laag) halen |
| `POST /api/design/undo` · `/redo` | wijziging terugdraaien |
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
| `GET`/`POST`/`DELETE /api/library/materials` · `/presets` · `/machines` | de lokale materiaalbibliotheek |
| `POST /api/library/presets/{id}/apply` | preset op een bewerking (laag) zetten |
| `POST /api/library/testgrids/preview` | cellen uitrekenen zonder iets te tekenen |
| `POST`/`GET`/`DELETE /api/library/testgrids` | testraster genereren, teruglezen, weggooien |
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

## Ontwerp uitlezen

`GET /api/design` levert per element een SVG-pad **in de interne eenheid van de
engine** (Tat, 65535 per inch) plus `units_per_mm`. Omrekenen zou betekenen dat
we padstrings moeten herschrijven; de frontend zet er één schaaltransform
omheen.

Elementen horen bij **meerdere** operaties tegelijk: MeerK40t classificeert een
element automatisch in elke operatie waarvan de kleur matcht. `operation_ids`
geeft ze allemaal. Daarom kleurt het canvas op de eigen streekkleur van het
element — net als de scene van MeerK40t zelf — en niet op "de kleur van de laag".

## Elementen bewerken

Transformaties in MeerK40t werken op de **emphasized** selectie, niet op een
argument. Elke bewerking zet daarom eerst de nadruk op precies de nodes die hij
bedoelt en voert daarna het console-commando uit; de selectie van de engine komt
zo overeen met wat de gebruiker in de browser koos. Omdat nadruk een verzameling
is, werkt dezelfde code voor één element of twintig — `ids` is dan ook altijd
een lijst (een losse string mag ook).

Bij meerdere elementen werkt `resize` op de gezamenlijke omhullende en houdt de
engine de onderlinge posities intact, net als bij het slepen van een groep.

**Toewijzen aan een bewerking** gaat niet via een console-commando maar via
`operation.add_reference(node)` binnen een `undoscope`, zoals de engine het zelf
doet. Operaties bevatten geen elementen maar verwijzingen, dus een element kan
in meerdere bewerkingen tegelijk zitten — en dat gebeurt ook: de engine
classificeert nieuwe elementen automatisch in elke bewerking waarvan de kleur
matcht.

**Vertrouw een id niet na een undo.** Id's overleven een undo normaal gesproken
prima. Maar undo herstelt een snapshot van de héle boom, en kan uitkomen op een
toestand van vóórdat er id's waren toegekend — dan hernummert `validate_ids()`
en krijgt de client andere id's dan hij vasthoudt. Daar komt bij dat undo verder
terug kan springen dan één bewerking: waargenomen is dat na drie verplaatsingen
één undo er twee ongedaan maakte.

Daarom melden `/undo` en `/redo` `ids_invalidated: true` en laat de frontend de
selectie los, in plaats van het risico te lopen een ander element aan te wijzen.
Gemeld bij upstream.

## Materiaalbibliotheek (fase 4)

SQLite in één bestand naast de instellingen van de engine — geen dienst, geen
poort, niets dat de gebruiker apart installeert. Het schema volgt het datamodel
uit ARCHITECTUUR.md: `machine_profile`, `material` en `preset`, waarbij een
preset naar het machineprofiel wijst waarop hij gemaakt is. Presets dragen van
begin af aan een `source` (handmatig / geëxtrapoleerd / testraster /
geïmporteerd) en een optionele `origin_id`, zodat de community-repo later
zonder migratie kan binnenkomen.

**Let op de vermogensschaal.** MeerK40t bewaart `power` op een schaal van
0–1000, niet als percentage. Een preset van 65% wordt dus `power = 650`. Dat
verkeerd doen is een factor tien op een machine die brandt; `apply_settings`
rekent het om en een test legt het vast.

## Testrasters

Een raster van vakjes dat vermogen (naar rechts) tegen snelheid (naar beneden)
uitzet. **Elke cel krijgt een eigen operatie** met één vierkant eraan gekoppeld —
zo modelleert MeerK40t nu eenmaal verschillende instellingen, en het betekent dat
de bestaande `plan → spool`-route het raster zonder aanpassing brandt.

`preview` rekent de cellen uit zonder de elementenboom aan te raken, zodat je
ziet wat er komt voordat er iets in je ontwerp verschijnt. Het is een POST omdat
er een body bij hoort, maar hij muteert niets; dat staat expliciet in de
routebewaking van de tests.

Genereren gebeurt binnen één `undoscope`, dus één keer ongedaan maken haalt het
hele raster weg. Past het raster niet op het bed van het actieve device, dan
weigert de API het met een 409 en blijft het ontwerp onaangeroerd.

De cellen worden mét hun element- en operatie-id opgeslagen. Dat is wat de
volgende plak nodig heeft: een tik op de foto terugvertalen naar de snelheid en
het vermogen van dat vakje.

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
python -m pytest tests -q      # 123 tests, draait op een echte MeerK40t-kernel
```

De tests starten een kernel via `tests/conftest.py` (naar het model van
upstream `test/bootstrap.py`) met een dummy device, dus er is geen hardware nodig.
