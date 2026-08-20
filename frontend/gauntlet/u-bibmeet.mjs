/** Hoeveel instellingen zie je in de bibliotheek zonder te scrollen? */
import { chromium } from 'playwright';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(900);
const later = page.getByRole('button', { name: /^Later$/ });
if (await later.count()) await later.first().click().catch(() => {});
await page.click('button[title="Materiaalbibliotheek"]');
await page.waitForTimeout(1200);
console.log(JSON.stringify(await page.evaluate(() => {
	const rijen = [...document.querySelectorAll('.preset')];
	const zichtbaar = rijen.filter((r) => {
		const d = r.getBoundingClientRect();
		return d.height > 0 && d.top >= 0 && d.bottom <= window.innerHeight;
	});
	return {
		instellingenInDeDom: rijen.length,
		zichtbaarZonderScrollen: zichtbaar.length,
		hoogtePerInstelling: rijen.length ? Math.round(rijen[0].getBoundingClientRect().height) : 0,
		knoppenPerInstelling: rijen.length ? rijen[0].querySelectorAll('button').length : 0,
		totaleHoogteVanDeLijst: rijen.reduce((n, r) => n + Math.round(r.getBoundingClientRect().height), 0)
	};
})));
await b.close();
