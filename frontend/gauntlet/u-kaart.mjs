/** De hoogte van de selectiekaart zelf — dat is wat de verbouwing raakte. */
import { chromium } from 'playwright';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const els = (await (await fetch(`${BASE}/api/design`)).json()).elements.map((e) => e.id);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const uit = {};
for (const [naam, sel] of [['een', els.slice(0, 1)], ['drie', els.slice(0, 3)]]) {
	await page.goto(`${BASE}/?tab=design&select=${sel.join(',')}`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1000);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	uit[naam] = await page.evaluate(() => {
		const kaart = document.querySelector('.selected');
		const scroll = document.querySelector('.panel-scroll');
		return {
			kaartHoogte: kaart ? Math.round(kaart.getBoundingClientRect().height) : null,
			knoppenInPaneel: scroll ? scroll.querySelectorAll('button').length : null,
			paneelInhoud: scroll ? Math.round(scroll.scrollHeight) : null
		};
	});
}
console.log(JSON.stringify(uit));
await b.close();
