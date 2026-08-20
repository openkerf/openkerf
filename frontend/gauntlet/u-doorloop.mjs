/**
 * De doorloop uit de brief: "selecteer drie objecten, lijn ze uit, wijs ze aan
 * de snijlaag toe, zoom naar selectie."
 *
 * Niet om te zien of het kán maar om te tellen wat het kost: hoeveel
 * handelingen, hoeveel keer wisselen van oppervlak, en of er tussendoor iets
 * omvalt. Dezelfde taak twee keer: één keer zoals het vóór deze ronde ging (via
 * het paneel) en één keer zoals het nu kan.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability/doorloop';
mkdirSync(OUT, { recursive: true });
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';

async function verse() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	for (const v of [
		{ type: 'rect', x_mm: 20, y_mm: 30, width_mm: 40, height_mm: 25 },
		{ type: 'rect', x_mm: 90, y_mm: 60, width_mm: 40, height_mm: 25 },
		{ type: 'rect', x_mm: 170, y_mm: 20, width_mm: 40, height_mm: 25 }
	])
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(v)
		});
}

async function staat() {
	const d = await (await fetch(`${BASE}/api/design`)).json();
	const ops = d.operations.filter((o) => !o.grid);
	return {
		ys: d.elements.map((e) => Math.round((e.bounds?.[1] ?? 0) / 2580.118)),
		lagen: d.elements.map((e) => e.operation_ids.length),
		snijlagen: ops.filter((o) => o.type === 'op cut').map((o) => o.element_ids.length)
	};
}

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const fouten = [];
page.on('pageerror', (e) => fouten.push(String(e).slice(0, 140)));

await verse();
await page.goto(BASE + '/?tab=design', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(1000);
const later = page.getByRole('button', { name: /^Later$/ });
if (await later.count()) await later.first().click().catch(() => {});
await page.waitForTimeout(300);

const stappen = [];
const klok = Date.now();
function tel(wat) {
	stappen.push({ nr: stappen.length + 1, handeling: wat, ms: Date.now() - klok });
}

// 1. Drie vormen selecteren met een sleepkader.
await page.mouse.move(150, 200);
await page.mouse.down();
await page.mouse.move(700, 400, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(700);
tel('sleepkader over de drie vormen');
await page.screenshot({ path: `${OUT}/d1-selectie.png` });
const gekozen = await page.evaluate(
	() => new URL(location.href).searchParams.get('select')?.split(',').length ?? 0
);

// 2. Boven uitlijnen — één klik in de actiebalk.
await page.getByRole('button', { name: 'Boven uitlijnen', exact: true }).click();
await page.waitForTimeout(800);
tel('klik "Boven uitlijnen" in de actiebalk');
await page.screenshot({ path: `${OUT}/d2-uitgelijnd.png` });
const naUitlijnen = await staat();

// 3. Aan de snijlaag toewijzen — rechterklik, twee regels diep.
const doos = await page.locator('.grab').first().boundingBox();
await page.mouse.click(doos.x + doos.width / 2, doos.y + doos.height / 2, { button: 'right' });
await page.waitForTimeout(450);
tel('rechterklik op de selectie');
await page.screenshot({ path: `${OUT}/d3-menu.png` });
await page.getByRole('menuitem', { name: 'Laag' }).hover();
await page.waitForTimeout(350);
await page.screenshot({ path: `${OUT}/d4-laagmenu.png` });
await page.getByRole('menuitem', { name: 'Alleen in de snijlaag' }).click();
await page.waitForTimeout(1200);
tel('kies "Laag › Alleen in de snijlaag"');
const naLaag = await staat();

// 4. Naar de selectie zoomen — één toets.
const voorZoom = await page.locator('.zoom .val').first().textContent();
await page.keyboard.press(`${MOD}+Shift+a`);
await page.waitForTimeout(800);
tel('⌘⇧A — naar de selectie');
const naZoom = await page.locator('.zoom .val').first().textContent();
await page.screenshot({ path: `${OUT}/d5-gezoomd.png` });

console.log('\nDoorloop: uitlijnen, snijlaag, zoomen');
console.table(stappen);
console.log({
	gekozen,
	yVoor: 'ongelijk',
	yNaUitlijnen: naUitlijnen.ys,
	uitgelijnd: new Set(naUitlijnen.ys).size === 1,
	vormenInDeSnijlaag: naLaag.snijlagen,
	elkeVormInPreciesEenLaag: naLaag.lagen.every((n) => n === 1),
	zoomVoor: voorZoom?.trim(),
	zoomNa: naZoom?.trim(),
	fouten
});
await b.close();
