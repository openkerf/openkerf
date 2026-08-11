/**
 * Detailopnamen voor het donkere thema: de plekken waar kleur zélf het werk
 * doet — laagchips, kleurkiezer, materiaaltexturen, de bedminiatuur.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, reset } from './harness.mjs';

const RONDE = process.env.RONDE ?? 'r1';
const DIR = `../screenshots/aaa/donker`;
mkdirSync(DIR, { recursive: true });

const MATERIALEN = ['Berkenmultiplex', 'Acrylaat helder', 'Plantaardig leer', 'Grijskarton', 'RVS 304'];

async function dismiss(page) {
	const later = await page.$('button:has-text("Later")');
	if (later) { await later.click(); await page.waitForTimeout(300); }
}

async function lagen(page) {
	await page.evaluate(async () => {
		const post = (u, b) => fetch(u, {
			method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b)
		}).then((r) => r.json());
		await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 70, height_mm: 45 });
		await post('/api/design/elements', { type: 'circle', cx_mm: 150, cy_mm: 55, r_mm: 28 });
		for (const [t, l] of [['cut', 'Snijden 3mm'], ['engrave', 'Graveren logo'], ['raster', 'Foto']])
			await post('/api/design/operations', { type: t, label: l, speed: 25, power_percent: 55 });
	});
	await page.waitForTimeout(1000);
}

const b = await browser();
for (const thema of ['licht', 'donker']) {
	const dk = thema === 'donker' ? 'dark' : 'light';

	// 1. Lagenpaneel opengeklapt: chips, kleurkiezer, pillen.
	{
		await reset();
		const page = await open(b, { width: 1440, theme: dk, path: '/?tab=layers' });
		await dismiss(page);
		await lagen(page);
		await page.goto((process.env.OK_BASE ?? '') + '/?tab=layers', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(1200);
		await dismiss(page);
		const chip = await page.$('.chip');
		if (chip) { await chip.click(); await page.waitForTimeout(500); }
		await page.screenshot({ path: `${DIR}/${RONDE}-chips-desktop-${thema}.png`, clip: { x: 1160, y: 48, width: 280, height: 700 } });
		console.log(`${RONDE}-chips-desktop-${thema}.png`);
		await page.context().close();
	}

	// 2. Materiaalbibliotheek met echte materialen: de textuurbanden.
	{
		const page = await open(b, { width: 1440, theme: dk, path: '/?tab=design' });
		await dismiss(page);
		await page.evaluate(async (namen) => {
			for (const name of namen)
				await fetch('/api/library/materials', {
					method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name })
				});
		}, MATERIALEN);
		await page.click('button[title="Materiaalbibliotheek"]').catch(async () => {
			await page.click('button[title="Meer gereedschap"]');
			await page.waitForTimeout(300);
			await page.click('button[title="Materiaalbibliotheek"]');
		});
		await page.waitForTimeout(1500);
		await page.screenshot({ path: `${DIR}/${RONDE}-texturen-desktop-${thema}.png` });
		console.log(`${RONDE}-texturen-desktop-${thema}.png`);
		await page.context().close();
	}

	// 3. Bedminiatuur op de telefoon, uitgesneden.
	{
		const page = await open(b, { width: 390, theme: dk, path: '/' });
		await dismiss(page);
		await page.waitForTimeout(500);
		await page.screenshot({ path: `${DIR}/${RONDE}-bedje-telefoon-${thema}.png`, clip: { x: 0, y: 0, width: 390, height: 420 } });
		console.log(`${RONDE}-bedje-telefoon-${thema}.png`);
		await page.context().close();
	}
}
await b.close();
console.log('klaar');
