/** Geen nevenschade: desktop en telefoon moeten onaangeraakt zijn. */
import { browser, open } from './harness.mjs';
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/tablet';
const b = await browser();
for (const [width, theme] of [[1440,'light'],[1440,'dark'],[390,'dark']]) {
	const page = await open(b, { width, theme, path: '/?tab=job' });
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(()=>{});
	await page.waitForTimeout(500);
	await page.screenshot({ path: `${OUT}/r5-${width}-${theme}-nevenschade.png` });
	const klein = await page.$$eval('button, a[href], label.btn', (ns) => ns
		.filter(n => n.getBoundingClientRect().width > 0)
		.map(n => { const r = n.getBoundingClientRect(); return {w:Math.round(r.width),h:Math.round(r.height),t:(n.getAttribute('title')||n.textContent||'').trim().slice(0,24)}; })
		.filter(d => d.w < 44 || d.h < 44));
	console.log(width, theme, 'onder 44px:', klein.length, klein.slice(0,5), 'console:', page.problems?.slice(0,2) ?? []);
	await page.context().close();
}
await b.close();
