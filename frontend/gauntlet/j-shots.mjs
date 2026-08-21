/**
 * De schermstaten van Lagen en Job, desktop 1440, licht thema.
 *
 *   node gauntlet/j-shots.mjs voor
 *
 * De lopende job is het lastige beeld: hij is er alleen als er werkelijk iets in
 * de spooler staat. Op deze machine (KH-5030, niet verbonden) blijft een job op
 * 0,998 hangen — dat is de gedocumenteerde upstream-failure waarbij `calc_steps` één
 * stap meer telt dan `execute` uitvoert. Onhandig voor de engine, handig hier: het
 * geeft een stabiel "loopt"-beeld om naar te kijken.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'voor';
const alleen = process.argv[3] ?? null;
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability2/${ronde}`;
mkdirSync(OUT, { recursive: true });

const post = (pad, body) =>
	fetch(BASE + pad, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

const b = await chromium.launch();
const log = [];

async function open(pad) {
	const ctx = await b.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	const page = await ctx.newPage();
	const fouten = [];
	page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 140)));
	page.on('pageerror', (e) => fouten.push('pageerror: ' + String(e).slice(0, 140)));
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1000);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	page.fouten = fouten;
	return page;
}

async function schiet(naam, pad, stap) {
	if (alleen && !naam.includes(alleen)) return;
	const page = await open(pad);
	if (stap) await stap(page);
	await page.waitForTimeout(600);
	await page.screenshot({ path: `${OUT}/${naam}.png` });
	const paneel = page.locator('.panel-scroll').first();
	if (await paneel.count())
		await paneel.screenshot({ path: `${OUT}/${naam}-paneel.png` }).catch(() => {});
	const maat = await page.evaluate(() => {
		const s = document.querySelector('.panel-scroll');
		if (!s) return null;
		return {
			zichtbaar: Math.round(s.clientHeight),
			inhoud: Math.round(s.scrollHeight),
			knoppen: s.querySelectorAll('button').length,
			koppen: s.querySelectorAll('h2, h3, legend, .section-title').length
		};
	});
	log.push({ naam, ...(maat ?? {}), fouten: page.fouten.length });
	if (page.fouten.length) console.log('  !', naam, page.fouten.slice(0, 2));
	await page.context().close();
}

// ── Job, stil ──
await post('/api/job/stop');
await post('/api/spooler/clear');
await schiet('j1-job-stil', '/?tab=job');

// ── Job, pre-flight ──
await schiet('j2-preflight', '/?tab=job', async (page) => {
	await page.getByRole('button', { name: /^Job starten$/ }).click().catch(() => {});
	await page.waitForTimeout(900);
});

// ── Job, lopend ──
await post('/api/job/start');
await new Promise((r) => setTimeout(r, 2500));
await schiet('j3-job-loopt', '/?tab=job');
await schiet('j4-job-loopt-ontwerp', '/?tab=design');

// ── Job, gepauzeerd ──
await post('/api/job/pause');
await new Promise((r) => setTimeout(r, 1200));
await schiet('j5-job-pauze', '/?tab=job');
await post('/api/job/resume');
await new Promise((r) => setTimeout(r, 800));

// ── Job, twee in de wachtrij ──
await post('/api/job/start');
await new Promise((r) => setTimeout(r, 1500));
await schiet('j6-wachtrij-twee', '/?tab=job');
await post('/api/job/stop');
await post('/api/spooler/clear');
await new Promise((r) => setTimeout(r, 800));

// ── Lagen ──
await schiet('l1-lagen', '/?tab=layers');
await schiet('l2-lagen-open', '/?tab=layers', async (page) => {
	// De chip klapt de laag open; de ⋯ opent since v5 het rijmenu.
	await page.locator('.layer .chip').first().click().catch(() => {});
	await page.waitForTimeout(800);
});
await schiet('l4-lagen-raster-open', '/?tab=layers', async (page) => {
	// De rasterlaag: die heeft de meeste instellingen (dpi, overscan, heen en weer).
	await page.locator('.layer').nth(3).locator('.chip').click().catch(() => {});
	await page.waitForTimeout(800);
});
await schiet('l6-rijmenu', '/?tab=layers', async (page) => {
	await page.locator('.layer .more').first().click().catch(() => {});
	await page.waitForTimeout(500);
});
await schiet('l7-lijstmenu', '/?tab=layers', async (page) => {
	await page.locator('.lijstmeer').first().click().catch(() => {});
	await page.waitForTimeout(500);
});
await schiet('l8-laagtoevoegen', '/?tab=layers', async (page) => {
	await page.locator('.panel .add').first().click().catch(() => {});
	await page.waitForTimeout(500);
});
await schiet('l3-lagen-compact', '/?tab=layers', async (page) => {
	await page.getByRole('button', { name: /^(Compact|Ruim)$/ }).first().click().catch(() => {});
	await page.waitForTimeout(600);
});

console.table(log);
await b.close();
