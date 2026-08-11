/** Metingen op het canvas: bewijs bij de bevindingen. */
import { browser, open, reset } from './harness.mjs';

const b = await browser();

for (const [naam, breedte] of [['desktop', 1440], ['tablet', 1024]]) {
	await reset();
	const page = await open(b, { width: breedte });
	const later = await page.$('button:has-text("Later")');
	if (later) await later.click();

	await page.evaluate(async () => {
		const post = (u, x) =>
			fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(x) });
		await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 });
	});
	await page.waitForTimeout(900);

	const m = await page.evaluate(() => {
		const wrap = document.querySelector('.canvas-wrap');
		const vlak = document.querySelector('.canvas');
		const bed = document.querySelector('.bed');
		const r = (e) => (e ? e.getBoundingClientRect() : null);
		const labels = [...document.querySelectorAll('.ruler-x text')].map((t) => ({
			tekst: t.textContent,
			x: +t.getBoundingClientRect().x.toFixed(1),
			w: +t.getBoundingClientRect().width.toFixed(1)
		}));
		const grid = getComputedStyle(bed).backgroundSize;
		return {
			wrap: r(wrap), vlak: r(vlak), bed: r(bed),
			labels: labels.slice(0, 8), grid,
			// afstand tussen twee labels vs labelbreedte
		};
	});
	console.log(`\n== ${naam} ${breedte}`);
	console.log('canvasvlak', Math.round(m.vlak.width), 'x', Math.round(m.vlak.height));
	console.log('bed        ', Math.round(m.bed.width), 'x', Math.round(m.bed.height),
		' links', Math.round(m.bed.x - m.vlak.x), ' rechts over',
		Math.round(m.vlak.right - m.bed.right));
	console.log('bed vult   ', ((m.bed.width * m.bed.height) / (m.vlak.width * m.vlak.height) * 100).toFixed(0) + '%');
	console.log('gridstap   ', m.grid);
	console.log('labels     ', m.labels.map((l) => `${l.tekst}@${l.x}(${l.w})`).join(' '));

	// Klik midden in de rechthoek: selecteert dat?
	const bedbox = m.bed;
	const perMm = bedbox.width / 310;
	await page.mouse.click(bedbox.x + 50 * perMm, bedbox.y + 40 * perMm);
	await page.waitForTimeout(400);
	const binnen = await page.evaluate(() => !!document.querySelector('.selection'));
	// Klik op de rand
	await page.mouse.click(bedbox.x + 20 * perMm, bedbox.y + 40 * perMm);
	await page.waitForTimeout(400);
	const rand = await page.evaluate(() => {
		const h = document.querySelector('.selection .handle');
		const b = h?.getBoundingClientRect();
		return { sel: !!document.querySelector('.selection'), handle: b ? [+b.width.toFixed(1), +b.height.toFixed(1)] : null };
	});
	console.log('klik binnen selecteert:', binnen, '| klik op rand:', rand.sel, '| greep px:', rand.handle);

	// Zelfde greep bij 400% zoom
	for (let i = 0; i < 6; i++) await page.click('.zoom button[title="Inzoomen"]');
	await page.waitForTimeout(400);
	const na = await page.evaluate(() => {
		const h = document.querySelector('.selection .handle');
		const b = h?.getBoundingClientRect();
		const z = document.querySelector('.zoom .val')?.textContent;
		return { z, handle: b ? [+b.width.toFixed(1), +b.height.toFixed(1)] : null };
	});
	console.log('na inzoomen', na.z, 'greep px:', na.handle);
	await page.context().close();
}
await b.close();
await reset();
