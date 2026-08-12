# Lettertypen in de build

OpenKerf levert zijn eigen letters mee. Sinds v3.3 van het design system komen ze
niet meer van `fonts.googleapis.com`: een werkplaats-pc naast een laser heeft vaak
geen netwerk, en dan viel de huisstijl terug op systeemletters.

## IBM Plex Sans en IBM Plex Mono

- Copyright 2019 IBM Corp. All rights reserved.
- Licentie: **SIL Open Font License, Version 1.1** — <https://openfontlicense.org>
- Herkomst: de npm-pakketten `@fontsource/ibm-plex-sans` en `@fontsource/ibm-plex-mono`
  (zie `package.json`); de volledige licentietekst staat in
  `node_modules/@fontsource/ibm-plex-*/LICENSE`.

De OFL staat gebruiken, aanpassen en meeleveren toe, ook in een commercieel product,
zolang de fontbestanden niet los verkocht worden en de naam "IBM Plex" niet op een
gewijzigde versie geplakt wordt. Wij leveren ze onveranderd mee.

## Wat er precies in de build zit

Zes `woff2`-bestanden, samen 128 KB — alleen de latin-subset, alleen de gewichten
die de app echt zet:

| Familie | Gewichten |
|---|---|
| IBM Plex Sans | 400, 500, 600, 700 |
| IBM Plex Mono | 400, 500 |

De `@font-face`-blokken staan in `src/lib/tokens.css`. Ze wijzen rechtstreeks naar de
`woff2` in het npm-pakket en niet naar de meegeleverde css, want die verwijst óók
naar `woff` — zes bestanden extra die geen enkele browser van deze eeuw ophaalt.
