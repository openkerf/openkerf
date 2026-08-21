/**
 * Captures voor de twee nieuwe oppervlakken: hoeken en tegels.
 *
 * Volgens GAUNTLET-AAA-BRIEF: eigen server, eigen poort, 1440/1024/390 in licht
 * én donker, per relevante staat. De metingen (paneelbreedtes, of de knoptekst
 * echt meebeweegt) staan naast de screenshots, want een screenshot bewijst niets
 * over wat er stond — hij bewijst dat het er stond.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8137';
const WORTEL = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa';
const BREEDTES = [1440, 1024, 390];
const THEMAS = ['light', 'dark'];

async function api(pad, body, method = 'POST') {
	const r = await fetch(BASE + pad, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return { status: r.status, body: await r.json().catch(() => null) };
}

const b = await chromium.launch();

async function pagina(width, theme, pad) {
	const ctx = await b.newContext({
		viewport: { width, height: width === 390 ? 844 : 900 },
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
	const fouten = [];
	page.on('pageerror', (e) => fouten.push(String(e).slice(0, 140)));
	page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 140)));
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1100);
	// Het herstelvenster wegklikken, anders fotografeer je een backdrop.
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	page.fouten = fouten;
	return { ctx, page };
}

const metingen = [];

// ---------------------------------------------------------------- opzet

await api('/api/design/clear');
const vel = (await api('/api/sheets', undefined, 'GET')).body.sheets[0];
await api(`/api/sheets/${vel.id}`, { width_mm: 500, height_mm: 150 }, 'PATCH');
const gemaakt = await api('/api/design/elements', {
	type: 'rect',
	x_mm: 40,
	y_mm: 40,
	width_mm: 60,
	height_mm: 45
});
const rechthoek = gemaakt.body.ids[0];
console.log('rechthoek:', rechthoek, '| vel 500x150');

// ------------------------------------------------------- oppervlak hoeken

mkdirSync(`${WORTEL}/hoeken`, { recursive: true });
for (const width of BREEDTES) {
	for (const theme of THEMAS) {
		const { ctx, page } = await pagina(width, theme, `/?tab=design&select=${rechthoek}`);
		// Gericht op de uitklapper die de hoekensectie bevat: 'Hoeken' als tekst
		// matcht ook 'Pad bewerken', en dan klik je de verkeerde open.
		const vouw = page.locator('details.fold:has(.hoeken) summary').first();
		const zichtbaar = await vouw.isVisible().catch(() => false);
		if (zichtbaar) {
			await vouw.click();
			await page.waitForTimeout(400);
		}
		metingen.push({
			oppervlak: 'hoeken',
			width,
			theme,
			vouwZichtbaar: zichtbaar,
			knop: zichtbaar
				? await page
						.locator('.hoeken button.primair')
						.first()
						.innerText()
						.catch(() => '(geen)')
				: '(paneel niet aanwezig)',
			fouten: page.fouten.length
		});
		await page.screenshot({ path: `${WORTEL}/hoeken/rond-${width}-${theme}.png` });
		if (zichtbaar) {
			await page.locator('.hoekstijl button', { hasText: 'Schuin' }).first().click();
			await page.waitForTimeout(400);
			await page.screenshot({ path: `${WORTEL}/hoeken/schuin-${width}-${theme}.png` });
		}
		await ctx.close();
	}
}

// ------------------------------------------------------- oppervlak tegels

mkdirSync(`${WORTEL}/tegels`, { recursive: true });

// 1. Het aanbod: vel groter dan bed, tegels nog uit.
await api(`/api/sheets/${vel.id}`, { tiling: { enabled: false } }, 'PATCH');
await api('/api/tiling/cancel');
for (const width of BREEDTES) {
	for (const theme of THEMAS) {
		const { ctx, page } = await pagina(width, theme, '/?tab=design');
		const aanbod = page.getByRole('button', { name: /tegels branden/i });
		metingen.push({
			oppervlak: 'tegels/aanbod',
			width,
			theme,
			aanbodZichtbaar: await aanbod.first().isVisible().catch(() => false),
			fouten: page.fouten.length
		});
		await page.screenshot({ path: `${WORTEL}/tegels/aanbod-${width}-${theme}.png` });
		await ctx.close();
	}
}

// 2. Reeks gestart, tegel 1, nog niet uitgelijnd.
await api(`/api/sheets/${vel.id}`, { tiling: { enabled: true } }, 'PATCH');
const gestart = await api('/api/tiling/start');
console.log('start:', gestart.status, JSON.stringify(gestart.body)?.slice(0, 120));

async function tegelSchot(naam) {
	for (const width of BREEDTES) {
		for (const theme of THEMAS) {
			const { ctx, page } = await pagina(width, theme, '/?tab=job');
			const paneel = page.locator('section.tegels');
			const aanwezig = await paneel.first().isVisible().catch(() => false);
			metingen.push({
				oppervlak: `tegels/${naam}`,
				width,
				theme,
				paneelZichtbaar: aanwezig,
				tekst: aanwezig
					? (await paneel.first().innerText()).replace(/\s+/g, ' ').slice(0, 150)
					: '(paneel niet aanwezig)',
				fouten: page.fouten.length
			});
			await page.screenshot({ path: `${WORTEL}/tegels/${naam}-${width}-${theme}.png` });
			await ctx.close();
		}
	}
}

await tegelSchot('stap1');

// 3. Uitgelijnd op de plaathoek: nu mag er gebrand worden.
const uitgelijnd = await api('/api/tiling/align', {
	reference: 'plate_corner',
	points: [{ x_mm: 0, y_mm: 0 }]
});
console.log('align:', uitgelijnd.status, JSON.stringify(uitgelijnd.body)?.slice(0, 140));
await tegelSchot('uitgelijnd');

// 4. Tegel 2: hier hoort de verschuifafstand en de naam van het merk te staan.
const door = await api('/api/tiling/advance');
console.log('advance:', door.status, JSON.stringify(door.body)?.slice(0, 140));
await tegelSchot('tegel2');

await b.close();
console.log('\n--- metingen ---');
for (const m of metingen) console.log(JSON.stringify(m));
