/**
 * Vullen en de rasterlaag: de twee klikken waarmee je een getekend vierkant
 * gevuld rastert.
 *
 * De metingen naast de screenshots zijn het bewijs dat het werkt: wat er op de
 * knop staat, en hoeveel van het vlak onze rasteraar zwart maakt (de tijd zegt
 * hier niets — een rasterlaag scant de omtrekbox toch al, gevuld of niet).
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8151';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/vulling';
mkdirSync(UIT, { recursive: true });

async function api(pad, body, method = 'POST') {
	const r = await fetch(BASE + pad, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return { status: r.status, body: await r.json().catch(() => null) };
}

await api('/api/design/clear');
const vorm = (
	await api('/api/design/elements', {
		type: 'rect',
		x_mm: 30,
		y_mm: 30,
		width_mm: 40,
		height_mm: 30
	})
).body.ids[0];
console.log('vorm:', vorm);

const b = await chromium.launch();
const metingen = [];

async function pagina(width, theme) {
	const ctx = await b.newContext({
		viewport: { width, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark') {
		await page.addInitScript(() => {
			const set = () => document.documentElement?.setAttribute('data-theme', 'dark');
			set();
			document.addEventListener('DOMContentLoaded', set);
		});
	}
	page.fouten = [];
	page.on('pageerror', (e) => page.fouten.push(String(e).slice(0, 120)));
	await page.goto(`${BASE}/?tab=design&select=${vorm}`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1300);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	return { ctx, page };
}

const knoppen = async (page) => ({
	vul: await page
		.locator('.indelen button.rot')
		.first()
		.innerText()
		.catch(() => '(geen)'),
	bestemmingen: await page
		.locator('.alleen-in')
		.innerText()
		.then((t) => t.replace(/\s+/g, ' '))
		.catch(() => '(geen)')
});

for (const width of [1440, 1024]) {
	for (const theme of ['light', 'dark']) {
		// 1. Onbewerkt: alleen een omtrek.
		await api('/api/design/fill', { ids: [vorm], filled: false });
		let { ctx, page } = await pagina(width, theme);
		metingen.push({ staat: 'open', width, theme, ...(await knoppen(page)), fouten: page.fouten.length });
		await page.screenshot({ path: `${UIT}/open-${width}-${theme}.png` });

		// 2. Vullen via de knop, en dan naar de rasterlaag.
		await page.locator('.indelen button.rot').first().click();
		await page.waitForTimeout(2000);
		metingen.push({
			staat: 'gevuld',
			width,
			theme,
			...(await knoppen(page)),
			melding: await page.locator('.indelen .tip').last().innerText().catch(() => '(geen)'),
			fouten: page.fouten.length
		});
		await page.screenshot({ path: `${UIT}/gevuld-${width}-${theme}.png` });

		await page.locator('.alleen-in button', { hasText: 'rasterlaag' }).click();
		await page.waitForTimeout(2200);
		metingen.push({
			staat: 'in-rasterlaag',
			width,
			theme,
			melding: await page.locator('.indelen .tip').last().innerText().catch(() => '(geen)'),
			fouten: page.fouten.length
		});
		await page.screenshot({ path: `${UIT}/rasterlaag-${width}-${theme}.png` });
		await ctx.close();
	}
}

await b.close();
console.log('--- metingen ---');
for (const m of metingen) console.log(JSON.stringify(m));
