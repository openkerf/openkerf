import { browser, open, reset } from './harness.mjs';
await reset();
const b = await browser();
const page = await open(b, { width: 1440 });
await page.evaluate(async () => {
	for (const t of ['cut', 'engrave', 'raster']) {
		await fetch('/api/design/operations', { method: 'POST',
			headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: t }) });
	}
	await fetch('/api/design/elements', { method: 'POST', headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 10, y_mm: 10, width_mm: 20, height_mm: 10 }) });
});
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar');
await page.waitForTimeout(800);
await page.click('button[role="tab"]:has-text("Lagen")').catch(() => {});
await page.waitForTimeout(500);
const chips = await page.$$eval('.chip', (nodes) =>
	nodes.map((n) => ({ tekst: n.textContent.trim(), kleur: getComputedStyle(n).backgroundColor }))
);
console.log('laagchips:', JSON.stringify(chips));
console.log('alle chips hebben een nummer:', chips.length > 0 && chips.every((c) => /\d|R/.test(c.tekst)));
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await b.close();
