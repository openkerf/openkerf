/** Eén uitgeklapte laag in zijn geheel, plus de maten ervan. */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'voor';
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability2/${ronde}`;
mkdirSync(OUT, { recursive: true });
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
await page.goto(BASE + '/?tab=layers', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(1000);
const later = page.getByRole('button', { name: /^Later$/ });
if (await later.count()) await later.first().click().catch(() => {});
const maten = {};
maten.rijHoogtes = await page.$$eval('.layer', (n) => n.map((x) => Math.round(x.getBoundingClientRect().height)));
maten.knoppenPerRij = await page.$$eval('.layer', (n) => n.map((x) => x.querySelectorAll('button').length));
await page.locator('.layer').nth(3).locator('.more').click().catch(() => {});
await page.waitForTimeout(1200);
maten.naKlik = await page.$$eval('.layer', (n) =>
	n.map((x) => ({ h: Math.round(x.getBoundingClientRect().height), open: x.classList.contains('open') }))
);
const laag = page.locator('.layer.open').first();
if (await laag.count()) {
	await laag.screenshot({ path: `${OUT}/l5-laag-uitgeklapt.png` });
	maten.uitgeklapt = await page.evaluate(() => {
		const el = document.querySelector('.layer.open');
		return el ? Math.round(el.scrollHeight) : null;
	});
	maten.knoppenUitgeklapt = await laag.locator('button').count();
	maten.veldenUitgeklapt = await laag.locator('input, select').count();
}
console.log(JSON.stringify(maten, null, 1));
await b.close();
