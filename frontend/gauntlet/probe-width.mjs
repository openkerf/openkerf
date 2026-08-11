import { browser, open } from './harness.mjs';
const b = await browser();
const page = await open(b, { width: 390 });
const wide = await page.$$eval('*', (nodes) =>
	nodes
		.map((n) => {
			const r = n.getBoundingClientRect();
			return { cls: String(n.className ?? '').slice(0, 34), tag: n.tagName.toLowerCase(),
				w: +r.width.toFixed(0), right: +(r.x + r.width).toFixed(0),
				min: getComputedStyle(n).minWidth };
		})
		.filter((x) => x.right > 391)
		.slice(0, 12)
);
console.log(wide.map((w) => `${w.tag}.${w.cls} w=${w.w} right=${w.right} min=${w.min}`).join('\n'));
await b.close();
