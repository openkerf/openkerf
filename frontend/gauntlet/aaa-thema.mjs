/**
 * Schermen voor het oppervlak "thema, tokens, typografie".
 *
 * Niet één scherm maar de plekken waar de trap, de accentkleur, de vinkjes en
 * de knoppen samenkomen: het hoofdscherm met alle drie de tabbladen, de
 * materiaalbibliotheek (veel chips, veel accenttekst) en de instelstap van de
 * wizard (veel vinkjes). Beide thema's, drie breedtes.
 *
 * Gebruik: OK_BASE=... node gauntlet/aaa-thema.mjs <ronde>
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';
import { eisScherm, eisHeleBuild } from './g-thema-guard.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/g-thema';
const ronde = process.argv[2] ?? 'r1';
mkdirSync(OUT, { recursive: true });

/** Een leeg bed toont geen laagkleuren; dus eerst werk erop zetten. */
async function zaai() {
	const post = (pad, body) =>
		fetch(BASE + pad, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body)
		}).catch(() => {});
	await fetch(BASE + '/api/design/clear', { method: 'POST' }).catch(() => {});
	await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 80, height_mm: 50 });
	await post('/api/design/elements', { type: 'ellipse', cx_mm: 150, cy_mm: 60, rx_mm: 30, ry_mm: 30 });
	await post('/api/design/elements', { type: 'text', x_mm: 30, y_mm: 110, text: 'OpenKerf' });
	for (const [type, label] of [['engrave', 'Graveren'], ['cut', 'Snijden'], ['raster', 'Rasteren']]) {
		await post('/api/design/operations', { type, label });
	}
}

async function weg(page) {
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(200);
}

/**
 * Geen foto van een halve pagina.
 *
 * `frontend/build` is in deze wave gedeeld; twee builds door elkaar leverden al
 * een index.html op die naar een ontbrekende chunk wees, en dan is het
 * screenshot een egaal vlak in --surface-0 dat er als een thema uitziet. Deze
 * poort faalt luid in plaats van een plaatje op te leveren.
 */
async function poort(page, verwacht, waar) {
	await eisScherm(page, verwacht, waar);
}

await zaai();
const b = await browser();

for (const [naam, width] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const theme of ['light', 'dark']) {
		for (const tab of ['design', 'layers', 'job']) {
			const page = await open(b, { width, theme, path: `/?tab=${tab}` });
			await weg(page);
			// Op 390 is het een andere app: PhoneView, met `.telefoon` als wortel.
			await poort(page, width === 390 ? '.telefoon' : '.topbar', `${naam} ${theme} ${tab}`);
			if (tab === 'design' && theme === 'light') await eisHeleBuild(page);
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-${tab}.png` });
			await page.context().close();
		}

		// Materiaalbibliotheek: de dichtste bak accenttekst en chips die we hebben.
		const page = await open(b, { width, theme });
		await weg(page);
		let knop = page.locator('button[title="Materiaalbibliotheek"]');
		if (!(await knop.first().isVisible().catch(() => false))) {
			await page.locator('button[title="Meer gereedschap"]').first().click().catch(() => {});
			await page.waitForTimeout(300);
		}
		if (await knop.first().isVisible().catch(() => false)) {
			await knop.first().click();
			await page.waitForTimeout(900);
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-bibliotheek.png` });
		}
		await page.context().close();

		// De instelstap van de wizard: daar staan de vinkjes.
		const w = await open(b, { width, theme, path: '/setup/instellen?machine=ruida' });
		await weg(w);
		await poort(w, '.setup', `${naam} ${theme} instellen`);
		await w.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-instellen.png`, fullPage: false });
		await w.context().close();
	}
}

await b.close();
console.log('klaar:', ronde);
