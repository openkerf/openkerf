/**
 * Screenshotset voor het oppervlak Canvas (gauntlet AAA).
 *
 * Staten: leeg bed, geïmporteerd bestand, selectie, meervoudige selectie,
 * ingezoomd, element zonder laag. Drie breedtes, twee thema's.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { browser, open, reset, BASE } from './harness.mjs';

const RONDE = process.env.RONDE ?? 'r1';
const DIR = `../screenshots/aaa/canvas`;
mkdirSync(DIR, { recursive: true });

/** Een testbestand dat lijkt op wat een gebruiker importeert. */
const SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80">
  <rect x="2" y="2" width="116" height="76" rx="6" fill="none" stroke="#000" stroke-width="0.5"/>
  <circle cx="30" cy="40" r="18" fill="none" stroke="#f00" stroke-width="0.5"/>
  <path d="M60 20 L100 20 L100 60 L60 60 Z" fill="none" stroke="#00f" stroke-width="0.5"/>
  <path d="M65 25 L95 55 M95 25 L65 55" fill="none" stroke="#0a0" stroke-width="0.5"/>
</svg>`;
writeFileSync('/tmp/aaa/kerf-test.svg', SVG);

async function dismiss(page) {
	const later = await page.$('button:has-text("Later")');
	if (later) {
		await later.click();
		await page.waitForTimeout(300);
	}
}

async function vul(page) {
	await page.evaluate(async () => {
		const post = (u, b) =>
			fetch(u, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(b)
			});
		await post('/api/design/elements', {
			type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40
		});
		await post('/api/design/elements', { type: 'circle', cx_mm: 150, cy_mm: 60, r_mm: 25 });
		await post('/api/design/generate/qrcode', {
			text: 'openkerf', size_mm: 30, x_mm: 220, y_mm: 30
		});
		await post('/api/design/elements', {
			type: 'rect', x_mm: 40, y_mm: 110, width_mm: 90, height_mm: 55
		});
		await post('/api/design/generate/polygon', {
			sides: 6, radius_mm: 25, cx_mm: 200, cy_mm: 140
		});
	});
	await page.waitForTimeout(900);
}

const STATEN = [
	['leeg', async () => {}],
	['vol', async (p) => { await vul(p); }],
	['selectie', async (p) => {
		await vul(p);
		// Klik op de contour van de eerste rechthoek.
		const doel = await p.$('svg path.hit');
		if (doel) await doel.click({ force: true });
		await p.waitForTimeout(500);
	}],
	['ingezoomd', async (p) => {
		await vul(p);
		await p.click('.zoom button[title="Inzoomen"]');
		await p.click('.zoom button[title="Inzoomen"]');
		await p.click('.zoom button[title="Inzoomen"]');
		await p.waitForTimeout(400);
	}]
];

const b = await browser();
for (const [klasse, breedte] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const thema of ['licht', 'donker']) {
		for (const [naam, stap] of STATEN) {
			if (breedte < 768 && naam !== 'leeg' && naam !== 'vol') continue;
			await reset();
			const page = await open(b, { width: breedte, theme: thema === 'donker' ? 'dark' : 'light' });
			await dismiss(page);
			await stap(page);
			await page.waitForTimeout(600);
			await page.screenshot({ path: `${DIR}/${RONDE}-${klasse}-${thema}-${naam}.png` });
			if (page.problems.length) console.log('  ! console:', page.problems.slice(0, 3));
			await page.context().close();
		}
	}
	console.log(klasse, 'klaar');
}
await b.close();
await reset();
console.log('klaar ->', DIR, 'base', BASE);
