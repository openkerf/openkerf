import { browser, open } from './harness.mjs';
const b = await browser();
const page = await open(b, { width: 1440 });
const state = await page.evaluate(() => {
	const el = document.querySelector('button[title^="Generatoren"]');
	const r = el.getBoundingClientRect();
	const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
	return { disabled: el.disabled, box: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
		bovenop: `${top?.tagName}.${String(top?.className?.baseVal ?? top?.className ?? '').slice(0, 26)}`,
		zelfde: top === el || el.contains(top) };
});
console.log(JSON.stringify(state, null, 1));
await page.click('button[title^="Generatoren"]');
await page.waitForTimeout(600);
console.log('na echte klik, backdrops:', await page.$$eval('.backdrop', (n) => n.length));
await b.close();
