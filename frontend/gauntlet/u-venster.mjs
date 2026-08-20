/**
 * Vensters in hun geheel: 1440 breed maar 2200 hoog, zodat een dialoog niet
 * door de vouw geknipt wordt. Alleen voor het kijken, niet voor het meten.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'voor';
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability/${ronde}`;
mkdirSync(OUT, { recursive: true });
const b = await chromium.launch();
const VENSTERS = [
	['v-testraster', 'button[title^="Testraster"]'],
	['v-bibliotheek', 'button[title="Materiaalbibliotheek"]'],
	['v-generatoren', 'button[title^="Generatoren"]'],
	['v-clipart', 'button[title^="Clipart"]']
];
for (const [naam, sel] of VENSTERS) {
	const ctx = await b.newContext({ viewport: { width: 1440, height: 2400 }, colorScheme: 'light' });
	const page = await ctx.newPage();
	await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});

	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.click(sel).catch(() => {});
	await page.waitForTimeout(1500);
	const dlg = page.locator('dialog, [role="dialog"], .venster').first();
	if (await dlg.count()) await dlg.screenshot({ path: `${OUT}/${naam}.png` }).catch((e) => console.log(naam, e.message));
	else await page.screenshot({ path: `${OUT}/${naam}.png` });
	await ctx.close();
}
await b.close();
console.log('klaar');
