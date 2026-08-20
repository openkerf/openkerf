/**
 * De screenshotset voor de usability-ronde: desktop 1440, licht thema.
 * Elke schermstaat die een gebruiker kan bereiken, in één map per ronde.
 *
 *   node gauntlet/u-shots.mjs voor
 *   node gauntlet/u-shots.mjs na
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'voor';
const alleen = process.argv[3] ?? null;
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability/${ronde}`;
mkdirSync(OUT, { recursive: true });

async function ids() {
	const d = await (await fetch(`${BASE}/api/design`)).json();
	return d.elements.map((e) => e.id);
}
const ELS = await ids();

const b = await chromium.launch();

async function open(path = '/') {
	const ctx = await b.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	const page = await ctx.newPage();
	const fouten = [];
	page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 160)));
	page.on('pageerror', (e) => fouten.push('pageerror: ' + String(e).slice(0, 160)));
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	page.fouten = fouten;
	return page;
}

const SCHERMEN = [
	['01-canvas-leeg-selectie', '/?tab=design', async () => {}],
	['02-canvas-een-vorm', `/?tab=design&select=${ELS[0]}`, async () => {}],
	['03-canvas-drie-vormen', `/?tab=design&select=${ELS.slice(0, 3).join(',')}`, async () => {}],
	['04-lagen', '/?tab=layers', async () => {}],
	['05-job', '/?tab=job', async () => {}],
	['06-job-preflight', '/?tab=job', async (p) => {
		await p.getByRole('button', { name: /start/i }).first().click().catch(() => {});
		await p.waitForTimeout(800);
	}],
	['07-bibliotheek', '/', async (p) => {
		await p.click('button[title="Materiaalbibliotheek"]').catch(() => {});
		await p.waitForTimeout(900);
	}],
	['08-testraster', '/', async (p) => {
		await p.click('button[title^="Testraster"]').catch(() => {});
		await p.waitForTimeout(1200);
	}],
	['09-generatoren', '/', async (p) => {
		await p.click('button[title^="Generatoren"]').catch(() => {});
		await p.waitForTimeout(900);
	}],
	['10-clipart', '/', async (p) => {
		await p.click('button[title^="Clipart"]').catch(() => {});
		await p.waitForTimeout(1200);
	}],
	['11-presetariat', '/', async (p) => {
		await p.click('button[title^="Presetariat"], button[title*="atalog"]').catch(() => {});
		await p.waitForTimeout(1200);
	}],
	['12-materiaal-vel', '/', async (p) => {
		await p.getByRole('button', { name: /materiaal/i }).first().click().catch(() => {});
		await p.waitForTimeout(700);
	}],
	['13-tekst', '/', async (p) => {
		await p.click('button[title^="Tekst"]').catch(() => {});
		await p.mouse.click(600, 400);
		await p.waitForTimeout(900);
	}],
	['14-setup', '/setup', async () => {}],
	['15-afbeelding-selectie', `/?tab=design&select=${ELS[3] ?? ELS[0]}`, async () => {}]
];

const log = [];
for (const [naam, pad, stap] of SCHERMEN) {
	if (alleen && !naam.includes(alleen)) continue;
	const page = await open(pad);
	await stap(page);
	await page.waitForTimeout(600);
	await page.screenshot({ path: `${OUT}/${naam}.png` });
	// Het paneel apart, ook het deel onder de vouw.
	const paneel = page.locator('.panel-scroll').first();
	if (await paneel.count())
		await paneel.screenshot({ path: `${OUT}/${naam}-paneel.png` }).catch(() => {});
	const maat = await page.evaluate(() => {
		const s = document.querySelector('.panel-scroll');
		return s ? { zichtbaar: Math.round(s.clientHeight), inhoud: Math.round(s.scrollHeight) } : null;
	});
	log.push({ naam, ...(maat ?? {}), fouten: page.fouten.length });
	if (page.fouten.length) console.log('  ! ', naam, page.fouten.slice(0, 3));
	await page.context().close();
}
console.table(log);
await b.close();
