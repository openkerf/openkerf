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
| Bewerken-tab: materiaalkaart en lagen | **voorbeelddata**, expliciet gelabeld — komt in fase 3/4 |
| Start job / Kader tonen | uitgeschakeld — schrijfacties zijn fase 2 |
| Tool-rail | zichtbaar, nog zonder gedrag (fase 3) |

## Structuur

```
src/lib/tokens.css          alle kleuren en maten uit DESIGN-SYSTEM.md
src/lib/api.ts              types die de API-snapshot spiegelen + formatters
src/lib/status.svelte.ts    WebSocket-verbinding met herverbind-backoff
src/lib/components/         TopBar, ToolRail, Canvas, DesignPanel, JobPanel, StatusBar
src/routes/+page.svelte     de drie-zone compositie
```

Componenten verwijzen uitsluitend naar CSS-variabelen uit `tokens.css` — geen losse
hexwaarden, zodat de themawissel en straks het Konva-canvas dezelfde bron delen.

## Controles

```bash
npm run check     # svelte-check, 0 errors
npm run build     # static build naar build/
```
