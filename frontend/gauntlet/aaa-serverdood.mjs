/**
 * De server gaat echt onderuit terwijl de browser openstaat.
 *
 * setOffline() van Playwright laat een al open WebSocket met rust, dus dat
 * meet niets. Hier sluiten we de server af: dat is wat er gebeurt als iemand
 * de laptop dichtklapt of de service herstart.
 */
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { browser, open } from './harness.mjs';

const DIR = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/lege-staten';
mkdirSync(DIR, { recursive: true });
const POORT = new URL(process.env.OK_BASE).port;

const b = await browser();
const paden = { job: '/?tab=job', ontwerp: '/?tab=design' };
const pages = [];
for (const width of [1440, 1024, 390]) {
	for (const theme of ['light', 'dark']) {
		for (const [naam, pad] of Object.entries(paden)) {
			if (width === 390 && naam === 'ontwerp') continue;
			const page = await open(b, { width, theme, path: pad });
			// Het welkomscherm van een verse installatie staat vóór de app.
			const rond = page.getByRole('button', { name: /rondkijken zonder machine/i });
			if (await rond.count().catch(() => 0)) {
				await rond.first().click().catch(() => {});
				await page.waitForTimeout(900);
			}
			const later = page.getByRole('button', { name: /later/i });
			if (await later.count().catch(() => 0)) await later.first().click().catch(() => {});
			pages.push({ page, naam: `serverdood-${naam}`, width, theme });
		}
	}
}
console.log(`${pages.length} pagina's open; server gaat nu neer`);
execSync(`lsof -ti :${POORT} | xargs kill`, { stdio: 'ignore' });
await pages[0].page.waitForTimeout(12000);

for (const { page, naam, width, theme } of pages) {
	await page.screenshot({ path: `${DIR}/${naam}-${width}-${theme}.png` });
	console.log(`${naam}-${width}-${theme}.png`);
}
await b.close();
