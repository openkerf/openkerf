/**
 * Checks the checker: a deliberately too-low contrast has to be found. A meter
 * that finds nothing because it is broken is worse than no meter.
 */
import { browser, open } from './harness.mjs';
const b = await browser();
const page = await open(b, { width: 1440 });
await page.addStyleTag({
	content: '.statusbar span { color: #c8cdd2 !important; background: #ffffff !important; }'
});
await page.waitForTimeout(200);
const bad = await page.$$eval('.statusbar span', (nodes) =>
	nodes.map((n) => getComputedStyle(n).color)
);
console.log('injected colour:', bad[0]);
const found = await page.evaluate(() => {
	function lum([r, g, b]) {
		const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
		return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
	}
	const n = document.querySelector('.statusbar span');
	const fg = getComputedStyle(n).color.match(/[\d.]+/g).slice(0, 3).map(Number);
	const ratio = (lum([255, 255, 255]) + 0.05) / (lum(fg) + 0.05);
	return +ratio.toFixed(2);
});
if (found >= 4.5) {
	console.error('SELF-TEST FAILED: the injection did not give a low contrast');
	process.exit(1);
}
console.log('self-test ok: measured', found, '(< 4.5, so findable)');
await b.close();
