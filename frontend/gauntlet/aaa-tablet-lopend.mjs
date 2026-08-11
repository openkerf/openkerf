/** Tablet met een lopende job: waar staan pauze en stop, en hoe groot zijn ze? */
import { browser, open } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/tablet';
const ronde = process.argv[2] ?? 'r1';
const b = await browser();

for (const [width, theme, tab] of [
	[1024, 'light', 'job'],
	[1024, 'light', 'design'],
	[768, 'dark', 'design'],
	[1024, 'dark', 'job']
]) {
	const page = await open(b, { width, theme, path: `/?tab=${tab}` });
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(800);
	await page.screenshot({ path: `${OUT}/${ronde}-${width}-${theme}-lopend-${tab}.png` });

	const acties = await page.$$eval('.statusbar button, .topbar button', (nodes) =>
		nodes
			.filter((n) => n.getBoundingClientRect().width > 0)
			.map((n) => {
				const r = n.getBoundingClientRect();
				return `${(n.textContent || n.getAttribute('aria-label') || '').trim().slice(0, 20)} ${Math.round(r.width)}x${Math.round(r.height)} @${Math.round(r.x)},${Math.round(r.y)}`;
			})
	);
	console.log(`\n${width} ${theme} tab=${tab}`);
	for (const a of acties) console.log('  ' + a);
	await page.context().close();
}
await b.close();
