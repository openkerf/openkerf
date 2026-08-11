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
const spot = await page.evaluate(() => {
	const r = document.querySelector('svg path.hit').getBoundingClientRect();
	return { x: r.x + 1, y: r.y + r.height / 2 };
});
await page.mouse.click(spot.x, spot.y);
await page.waitForTimeout(500);
console.log('url na klik:', await page.evaluate(() => location.search));
const read = () => page.evaluate(async () => {
	const d = await (await fetch('/api/design')).json();
	return +(d.elements[0].bounds[0] / d.units_per_mm).toFixed(3);
});
const a = await read();
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(700);
const c = await read();
await page.keyboard.down('Shift'); await page.keyboard.press('ArrowRight'); await page.keyboard.up('Shift');
await page.waitForTimeout(700);
const d = await read();
console.log(`x: ${a} -> pijl ${(c - a).toFixed(3)} mm -> shift ${(d - c).toFixed(3)} mm`);
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await b.close();
