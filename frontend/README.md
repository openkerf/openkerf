# openkerf-frontend

SvelteKit + TypeScript PWA-in-wording. Fase 1: **read-only monitor** op de
`openkerf-api`. De layout volgt `openkerf-mockup.html` en `DESIGN-SYSTEM.md`.

## Draaien

Engine + API in de ene terminal:

```bash
meerk40t --no-gui -d -e "openkerf -p 8080"
```

Frontend in de andere:

```bash
npm install
npm run dev        # http://localhost:5173, proxyt /api naar 127.0.0.1:8080
```

Een andere API-locatie: `OPENKERF_API=http://192.168.1.20:8080 npm run dev`.

## Bouwen en laten serveren door de API

Zo werkt het in productie — één poort, één ding om te installeren:

```bash
npm run build
meerk40t --no-gui -d -e "openkerf -p 8080 -f $(pwd)/build"
```

## Wat er live is en wat niet

| Onderdeel | Status |
|---|---|
| Machinechip in de bovenbalk (label + toestand) | live |
| Statusbalk X/Y in mm, API-verbinding, machinetoestand | live |
| Bed-afmeting en het gridraster van het canvas | live (uit de device-instellingen) |
| Kop-positie als kruisdraad op het bed | live |
| Job-tab: spoolerwachtrij, voortgang, tijden, engine-signalen | live |
| Ontwerp laden, job starten, pauze, hervatten, stop, wachtrij legen | live (fase 2) |
| Canvas: het geladen ontwerp op het bed, op ware maat | live (fase 3, eerste plak) |
| Bewerken-tab: lagen met snelheid/vermogen en elementaantal | live |
| Materiaalkaart | nog niet gebouwd — fase 4 |
| Kader tonen | uitgeschakeld — beweging is fase 3 |
| Tool-rail | zichtbaar, nog zonder gedrag (fase 3) |

## Bediening en veiligheid

De startknop opent geen dialoog maar een **pre-flight in het rechterpaneel**:
geschatte tijd, aantal jobs in de wachtrij en een waarschuwing over deksel,
koeling en air assist — pas daarna "Nu starten". Stoppen is één rode knop,
zowel in de bovenbalk als in het paneel.

Knoppen gaan uit als het actieve device de actie niet kent (`/api/capabilities`)
of als er een token nodig is die nog niet ingevuld is. Een knop aanbieden die
gegarandeerd 401 oplevert is een lege belofte, dus dat doen we niet.

Als de API vanaf het netwerk bereikbaar is, vraagt het paneel om de token; die
wordt in `localStorage` bewaard zodat de PWA er niet elke sessie om vraagt.

## Structuur

```
src/lib/tokens.css          alle kleuren en maten uit DESIGN-SYSTEM.md
src/lib/api.ts              types die de API-snapshot spiegelen + formatters
src/lib/status.svelte.ts    WebSocket-verbinding met herverbind-backoff
src/lib/control.svelte.ts   schrijfacties, token-opslag, foutafhandeling
src/lib/components/         TopBar, ToolRail, Canvas, DesignPanel, JobPanel,
                            JobControls, StatusBar
src/routes/+page.svelte     de drie-zone compositie
```

Componenten verwijzen uitsluitend naar CSS-variabelen uit `tokens.css` — geen losse
hexwaarden, zodat de themawissel en straks het Konva-canvas dezelfde bron delen.

## Controles

```bash
npm run check     # svelte-check, 0 errors
npm run build     # static build naar build/
```

## Machine-setup (`/setup`)

Een wizard waarin **elke stap een eigen route** is:

| Route | Stap |
|---|---|
| `/setup` | machines: wat heb je al, welke is actief |
| `/setup/type` | zoekbare catalogus uit MeerK40t, gegroepeerd per familie |
| `/setup/naam?type=<key>` | naam geven, voorgevuld uit de catalogus |
| `/setup/instellen?machine=<path>` | werkgebied en verbinding |
| `/setup/klaar?machine=<path>` | afronding |

Wat een stap nodig heeft staat in de URL, niet in component-state. Daardoor werken de
browser-terugknop, een bladwijzer en verversen alle drie, en toont een stap zonder de
benodigde parameter een nette uitleg met een weg terug in plaats van een half formulier.
De paneel-tab op het werkgebied zit om dezelfde reden in de URL (`/?tab=design`).

De machinechip in de bovenbalk linkt hierheen en toont "Machine instellen" als er
nog niets is, zodat een lege installatie geen doodlopende weg is. Instelvelden
worden gegenereerd uit wat de API teruggeeft — label, tip, type en eventuele
keuzelijst — dus er staat geen enkele machine-eigenschap hardcoded in de frontend.
