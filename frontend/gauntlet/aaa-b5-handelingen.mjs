/**
 * Hoeveel handelingen kost het om twee rechthoeken exact naast elkaar te
 * zetten — met vastklikken en zonder?
 *
 * "Zonder" is niet verzonnen: het is de weg die er vóór B5 was, namelijk slepen
 * en daarna X en Y in het selectiepaneel intypen. Alt ingedrukt houden zet het
 * vastklikken uit en geeft precies die oude situatie terug.
 */
import { browser, open, BASE } from './harness.mjs';

const BED = { w: 310, h: 210 };

async function verseVormen() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	for (const r of [
		{ x_mm: 60, y_mm: 60, width_mm: 40, height_mm: 30 },
		{ x_mm: 103.1, y_mm: 62.7, width_mm: 40, height_mm: 30 }
	]) {
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ type: 'rect', ...r })
		});
	}
}

async function stand() {
	const d = await (await fetch(`${BASE}/api/design`)).json();
	const per = d.units_per_mm;
	const b = d.elements
		.map((e) => ({ x0: e.bounds[0] / per, y0: e.bounds[1] / per, x1: e.bounds[2] / per }))
		.sort((p, q) => p.x0 - q.x0);
	return { gat: b[1].x0 - b[0].x1, scheef: b[1].y0 - b[0].y0 };
}

async function pagina(b) {
	const page = await open(b, { width: 1440, theme: 'light', path: '/?tab=design' });
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	const bed = await page.locator('.bed').boundingBox();
	const s = bed.width / BED.w;
	page.mm = (x, y) => ({ x: bed.x + x * s, y: bed.y + y * s });
	return page;
}

const b = await browser();

for (const met of [true, false]) {
	await verseVormen();
	const page = await pagina(b);
	const van = page.mm(103.1 + 20, 62.7 + 15);
	const naar = page.mm(121.4, 76.1); // wat een mens met de muis haalt: 1,4 mm ernaast
	let handelingen = 0;
	const t0 = Date.now();

	// 1. Klikken om te selecteren.
	await page.mouse.click(van.x, van.y);
	handelingen++;
	await page.waitForTimeout(250);

	// 2. Slepen.
	if (!met) await page.keyboard.down('Alt');
	await page.mouse.move(van.x, van.y);
	await page.mouse.down();
	await page.mouse.move(naar.x, naar.y, { steps: 10 });
	await page.mouse.up();
	if (!met) await page.keyboard.up('Alt');
	handelingen++;
	await page.waitForTimeout(700);

	if (!met) {
		// 3 en 4. X en Y met de hand rechtzetten in het selectiepaneel.
		for (const [naam, waarde] of [['X', '100'], ['Y', '60']]) {
			// Volgorde in het selectiepaneel: B, H, X, Y. De velden hebben geen
			// aria-label — apart bevonden, staat in het rapport.
			const veld = page.locator('input[type="number"]').nth(naam === 'X' ? 2 : 3);
			await veld.click();
			await veld.press('Meta+a');
			await veld.type(waarde);
			await veld.press('Enter');
			handelingen++;
			await page.waitForTimeout(600);
		}
	}

	const ms = Date.now() - t0;
	const s = await stand();
	console.log(
		`${met ? 'MET vastklikken ' : 'ZONDER (alt)   '}: ${handelingen} handelingen, ` +
			`${(ms / 1000).toFixed(1)} s, gat ${s.gat.toFixed(3)} mm, hoogteverschil ${s.scheef.toFixed(3)} mm`
	);
	await page.context().close();
}
await b.close();
