/**
 * Visuele bevestiging van afronden en afschuinen.
 *
 * De eerdere captures toonden de bediening, niet de uitkomst — je zag het
 * voorbeeldtekeningetje in het paneel, maar nooit de vorm die er werkelijk uit
 * kwam. Hier staan drie rechthoeken naast elkaar: scherp, afgerond, afgeschuind,
 * met dezelfde maat. Eén beeld met de drie naast elkaar zegt meer dan drie
 * losse, want het verschil is het punt.
 *
 * De vormen staan al klaar via de API; dit script fotografeert alleen.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8137';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/hoeken';
mkdirSync(UIT, { recursive: true });

const b = await chromium.launch();

for (const theme of ['light', 'dark']) {
	const ctx = await b.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 2, // scherp genoeg om een boog van een knik te onderscheiden
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark') {
		await page.addInitScript(() => {
			const zet = () => document.documentElement?.setAttribute('data-theme', 'dark');
			zet();
			document.addEventListener('DOMContentLoaded', zet);
		});
	}
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1500);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);

	// De drie vormen opzoeken en hun omhullende samenvoegen, in plaats van
	// pixelposities in het script te zetten: die verschuiven met elke wijziging
	// in de bovenbalk.
	const doos = await page.evaluate(() => {
		const vormen = [...document.querySelectorAll('svg path')]
			.map((n) => n.getBoundingClientRect())
			.filter((r) => r.width > 100 && r.width < 300 && r.height > 100);
		if (!vormen.length) return null;
		const x0 = Math.min(...vormen.map((r) => r.x));
		const y0 = Math.min(...vormen.map((r) => r.y));
		const x1 = Math.max(...vormen.map((r) => r.x + r.width));
		const y1 = Math.max(...vormen.map((r) => r.y + r.height));
		return { x0, y0, x1, y1 };
	});
	if (!doos) throw new Error('geen vormen gevonden');
	console.log(theme, 'doos:', JSON.stringify(doos));

	const rand = 26;
	await page.screenshot({
		path: `${UIT}/vergelijk-${theme}.png`,
		clip: {
			x: doos.x0 - rand,
			y: doos.y0 - rand,
			width: doos.x1 - doos.x0 + 2 * rand,
			height: doos.y1 - doos.y0 + 2 * rand
		}
	});

	// En een band over de bovenhoeken: daar zit het verschil, en op de hele vorm
	// is een hoek van 12 mm een detail dat je moet gaan zoeken.
	await page.screenshot({
		path: `${UIT}/detail-${theme}.png`,
		clip: {
			x: doos.x0 - 14,
			y: doos.y0 - 14,
			width: doos.x1 - doos.x0 + 28,
			height: 76
		}
	});
	await ctx.close();
}

await b.close();
console.log('klaar');
