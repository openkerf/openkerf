/** Wat elk stuk van een laagrij aan breedte opeist. */
import { chromium } from 'playwright';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
await page.goto(BASE + '/?tab=layers', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(1300);
const later = page.getByRole('button', { name: /^Later$/ });
if (await later.count()) await later.first().click().catch(() => {});
await page.waitForTimeout(400);
console.log(
	JSON.stringify(
		await page.evaluate(() => {
			const rij = document.querySelector('.layer');
			const ident = rij?.querySelector('.ident');
			const stukken = [...(ident?.children ?? [])].map((el) => ({
				cls: el.className.split(' ')[0],
				w: Math.round(el.getBoundingClientRect().width)
			}));
			return {
				rij: Math.round(rij?.getBoundingClientRect().width ?? 0),
				rijHoogte: Math.round(rij?.getBoundingClientRect().height ?? 0),
				ident: Math.round(ident?.getBoundingClientRect().width ?? 0),
				stukken
			};
		}),
		null,
		1
	)
);
await b.close();
