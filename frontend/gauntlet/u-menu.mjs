/**
 * Het rechterklikmenu in beeld: op een vorm, op het canvas, en de actiebalk.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'na';
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability/${ronde}`;
mkdirSync(OUT, { recursive: true });

const els = (await (await fetch(`${BASE}/api/design`)).json()).elements.map((e) => e.id);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const fouten = [];
page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 200)));
page.on('pageerror', (e) => fouten.push('pageerror: ' + String(e).slice(0, 200)));

async function schoon() {
	await page.goto(`${BASE}/?tab=design&select=${els.slice(0, 3).join(',')}`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1100);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
}

await schoon();
await page.screenshot({ path: `${OUT}/20-actiebalk.png` });

// Rechterklik op de rand van de eerste vorm. Op de rand en niet in het midden:
// een vorm zonder vulling is alleen op zijn contour aan te klikken, en dat is
// hetzelfde gedrag als bij een gewone klik.
const rand = await page.evaluate(() => {
	const doos = document.querySelector('.hit')?.getBoundingClientRect();
	return doos ? { x: doos.x + doos.width / 2, y: doos.y + 1 } : { x: 210, y: 215 };
});
await page.mouse.move(rand.x, rand.y);
await page.mouse.click(rand.x, rand.y, { button: 'right' });
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/21-menu-object.png` });

// Submenu uitlijnen.
const uitlijn = page.getByRole('menuitem', { name: /Uitlijnen en verdelen/ });
if (await uitlijn.count()) { await uitlijn.first().hover(); await page.waitForTimeout(400); }
await page.screenshot({ path: `${OUT}/22-menu-uitlijnen.png` });
await page.keyboard.press('Escape');
await page.waitForTimeout(300);

// Rechterklik op leeg bed.
await page.mouse.click(760, 600, { button: 'right' });
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/23-menu-canvas.png` });
await page.keyboard.press('Escape');
await page.waitForTimeout(300);

// De zoomuitklap.
const zoom = page.locator('.zoom .val').first();
if (await zoom.count()) { await zoom.click(); await page.waitForTimeout(450); }
await page.screenshot({ path: `${OUT}/24-zoomstanden.png` });

await page.keyboard.press('Escape');
await page.waitForTimeout(300);

// Het paneel na de verhuizing, en het menu op een laagrij.
await page.goto(`${BASE}/?tab=design&select=${els[0]}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(1000);
await page.screenshot({ path: `${OUT}/25-paneel-eigenschappen.png` });
const paneel = page.locator('.panel-scroll').first();
if (await paneel.count()) await paneel.screenshot({ path: `${OUT}/25-paneel-eigenschappen-paneel.png` });

await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(1000);
const rij = page.locator('.layer').first();
if (await rij.count()) {
	const doos = await rij.boundingBox();
	await page.mouse.click(doos.x + 80, doos.y + 14, { button: 'right' });
	await page.waitForTimeout(500);
}
await page.screenshot({ path: `${OUT}/26-menu-laagrij.png` });

console.log('fouten:', fouten.slice(0, 6));
await b.close();
