/**
 * GAUNTLET-AAA — oppervlak "eerste start → eerste snede".
 * Schiet elke stap van de koude start op drie breedtes in beide thema's.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/eerste-start';
mkdirSync(OUT, { recursive: true });

const ronde = process.argv[2] ?? 'r1';
const paden = [
	['start', '/'],
	['setup', '/setup'],
	['soort', '/setup/kind'],
	['type', '/setup/type?soort=co2'],
	['naam', '/setup/name?type=lhystudios'],
	['klaar', '/setup/done']
];

const b = await browser();
console.log('BASE =', BASE);
for (const [naam, pad] of paden) {
	for (const [breedte, wlabel] of [[1440, 'desktop'], [1024, 'tablet'], [390, 'telefoon']]) {
		for (const thema of ['light', 'dark']) {
			const page = await open(b, { width: breedte, theme: thema, path: pad });
			const file = `${OUT}/${ronde}-${naam}-${wlabel}-${thema}.png`;
			await page.screenshot({ path: file, fullPage: breedte === 390 });
			if (page.problems.length) console.log(naam, wlabel, thema, 'CONSOLE:', page.problems.slice(0, 3));
			await page.context().close();
		}
	}
	console.log('geschoten:', naam);
}
await b.close();
