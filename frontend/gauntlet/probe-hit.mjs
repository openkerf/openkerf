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
const shapes = await page.$$eval('svg path, svg rect, svg circle, svg ellipse', (nodes) =>
	nodes.map((n) => {
		const r = n.getBoundingClientRect();
		const s = getComputedStyle(n);
		return { tag: n.tagName, cls: String(n.className?.baseVal ?? '').slice(0, 20),
			role: n.getAttribute('role'), fill: s.fill, strokeW: s.strokeWidth,
			w: +r.width.toFixed(0), h: +r.height.toFixed(0), x: +r.x.toFixed(0), y: +r.y.toFixed(0),
			pointer: s.pointerEvents };
	}).filter((x) => x.w > 4)
);
console.log(shapes.map((s) => `${s.tag}.${s.cls} role=${s.role} fill=${s.fill} stroke=${s.strokeW} pointer=${s.pointer} box=${s.w}x${s.h}@${s.x},${s.y}`).join('\n'));
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await b.close();
