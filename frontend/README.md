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
| Canvas: het geladen ontwerp op het bed, op ware maat | live |
| Selectie: klikken op een element, contour + maten | live |
| Bewerken: slepen, schalen, draaien, pijltjes, ongedaan maken | live |
| Meervoudige selectie (shift-klik) | live |
| Bewerking (laag) toekennen aan de selectie | live |
| Bewerken-tab: lagen met snelheid/vermogen en elementaantal | live |
| Materiaalbibliotheek: materialen, presets, toepassen op een laag | live (fase 4, eerste plak) |
| Testraster: bereik instellen, voorbeeld, genereren | live |
| Testraster: foto en beste vakje aanwijzen | nog niet gebouwd — volgende plak |
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
De paneel-tab en de selectie zitten om dezelfde reden in de URL
(`/?tab=design&select=meerk40t:133`) — een selectie is daarmee deelbaar en
overleeft een verversing.

De machinechip in de bovenbalk linkt hierheen en toont "Machine instellen" als er
nog niets is, zodat een lege installatie geen doodlopende weg is. Instelvelden
worden gegenereerd uit wat de API teruggeeft — label, tip, type en eventuele
keuzelijst — dus er staat geen enkele machine-eigenschap hardcoded in de frontend.

## Selectie op het canvas

Klikken op een contour selecteert het element: de omtrek krijgt de kerflijn
(statisch gestreept, animatie pas bij slepen), met greep-blokjes op de hoeken en
de maat eronder in mono. Het rechterpaneel toont breedte, hoogte en positie in
mm. Escape of een klik naast het ontwerp heft de selectie op.

Twee dingen die niet vanzelf goed gaan:

- **Een contour van 1 pixel is niet aan te klikken.** Boven elk pad ligt een
  onzichtbare trefzone van 12 px (`stroke="transparent"`, `pointer-events` op de
  streek), zodat aanklikken ook op een touchscreen lukt. Die zones zijn
  focusbaar en met Enter of spatie te selecteren.
- **Identiteit moet een wijziging overleven.** De id's komen van de engine zelf
  (`elements.validate_ids()` → `meerk40t:N`, terug op te zoeken met
  `find_node()`), niet uit de volgorde van de snapshot. Anders zou een selectie
  na het toevoegen van een element stilletjes naar een ander object wijzen.

## Bewerken

Sleep het selectiekader om te verplaatsen, de hoekgrepen om te schalen (de
tegenoverliggende hoek blijft liggen). Tijdens het slepen loopt de kerflijn —
het enige moment waarop hij beweegt. Pijltjestoetsen verplaatsen 0,1 mm, met
shift 1 mm.

Er gaat **één** opdracht naar de engine, bij loslaten; tijdens het slepen is de
contour een lokale voorvertoning. Anders zou elke muisbeweging een commando
worden.

Ongedaan maken zit in het Ontwerp-blok. Na een undo laat de frontend de selectie
los: de boom kan dan uit een toestand komen waarin de id's anders liggen, dus een
bewaard id zou een ander element kunnen aanwijzen.

**Meervoudige selectie** met shift-klik. Het kader is dan de gezamenlijke
omhullende; slepen, schalen en draaien werken op de hele groep. De kop van het
selectieblok telt hoeveel elementen er gekozen zijn.

**Draaien** kan op twee manieren: met de knoppen −90°, −1°, +1° en +90° in het
selectieblok, of door aan de ronde greep boven het kader te slepen. Tijdens het
slepen draait het kader mee als voorvertoning en toont het label de hoek; shift
klikt vast op stappen van 15°. De engine draait om het middelpunt van de
selectie.

Net als bij verplaatsen gaat er één opdracht naar de engine, bij loslaten. Onder
een halve graad telt het als getril en gebeurt er niets.

**Laag toekennen** met het vinkje voor elke laagrij: aan zet de hele selectie in
die bewerking, uit haalt hem eruit. Zit maar een deel van de selectie erin, dan
staat het vinkje op onbepaald — dat is eerlijk, want in MeerK40t kan elk element
in meerdere bewerkingen zitten.

Bewerken vereist dezelfde token als de jobcontrole; zonder token zijn de grepen
inactief en zegt het paneel waarom.
