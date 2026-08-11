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
const info = await page.evaluate(() => {
	const hit = document.querySelector('svg path.hit');
	const r = hit.getBoundingClientRect();
	const points = [
		['linkerrand midden', r.x, r.y + r.height / 2],
		['bovenrand midden', r.x + r.width / 2, r.y],
		['midden', r.x + r.width / 2, r.y + r.height / 2]
	];
	return points.map(([naam, x, y]) => {
		const el = document.elementFromPoint(x, y);
		return `${naam} (${x.toFixed(0)},${y.toFixed(0)}) -> ${el?.tagName}.${String(el?.className?.baseVal ?? el?.className ?? '').slice(0, 24)}`;
	});
});
console.log(info.join('\n'));
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await b.close();
