import { browser, open } from './harness.mjs';
const b = await browser();
const page = await open(b, { width: 1440 });
await page.evaluate(() =>
	fetch('/api/design/elements', { method: 'POST', headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 40, y_mm: 40, width_mm: 20, height_mm: 10 }) })
);
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar');
await page.waitForTimeout(900);
console.log('klikbare vormen:', await page.$$eval('svg .hit, svg path[role="button"], svg rect[role="button"]', (n) => n.length));
const target = await page.$('svg path.hit');
if (target) {
	const box = await target.boundingBox();
	console.log('hitdoos:', JSON.stringify(box));
	await page.mouse.click(box.x, box.y + box.height / 2);
	await page.waitForTimeout(500);
}
console.log('geselecteerde ids:', await page.evaluate(() => window.location.search));
console.log('selectie in het paneel:', await page.$$eval('.selected .name', (n) => n.map((x) => x.textContent.trim())));
console.log('canEdit-knoppen actief:', await page.$$eval('button.rot', (n) => n.filter((x) => !x.disabled).length));
const before = await page.evaluate(async () => {
	const d = await (await fetch('/api/design')).json();
	return +(d.elements[0].bounds[0] / d.units_per_mm).toFixed(3);
});
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(600);
const after = await page.evaluate(async () => {
	const d = await (await fetch('/api/design')).json();
	return +(d.elements[0].bounds[0] / d.units_per_mm).toFixed(3);
});
console.log('x voor:', before, '| na pijl rechts:', after, '| verschil:', +(after - before).toFixed(3));
console.log('focus op:', await page.evaluate(() => document.activeElement?.tagName + '.' + String(document.activeElement?.className ?? '').slice(0, 30)));
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await b.close();
