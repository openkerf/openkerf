/**
 * Screenshots + metingen voor het oppervlak "telefoon".
 *
 * Argument = naam van de staat (rust | job | ronde2 ...). De inhoud van de
 * server zet je zelf klaar; dit script kijkt alleen.
 */
import { browser, open, BASE } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const staat = process.argv[2] ?? 'rust';
const map = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/telefoon';
mkdirSync(map, { recursive: true });

const b = await browser();
for (const width of [390, 430]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/' });
		// Herstelvenster wegklikken als het opduikt.
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});
		await page.waitForTimeout(900);
		const naam = `${staat}-${width}-${theme}`;
		await page.screenshot({ path: `${map}/${naam}.png`, fullPage: true });

		// Metingen: raakdoelen, hun onderlinge afstand en verticale positie.
		const meting = await page.evaluate(() => {
			const vh = window.innerHeight;
			const doelen = [...document.querySelectorAll('button, a[href], label, input, select')]
				.map((n) => {
					const r = n.getBoundingClientRect();
					return {
						t: (n.textContent ?? '').trim().slice(0, 28) || n.tagName,
						x: Math.round(r.x), y: Math.round(r.y),
						w: Math.round(r.width), h: Math.round(r.height),
						bereik: Math.round((r.y / vh) * 100)
					};
				})
				.filter((d) => d.w > 0 && d.h > 0);
			const pauze = doelen.find((d) => /pauze/i.test(d.t));
			const stop = doelen.find((d) => /^stop/i.test(d.t));
			return {
				vh,
				docH: document.documentElement.scrollHeight,
				doelen,
				kloof: pauze && stop ? Math.round(stop.x - (pauze.x + pauze.w)) : null
			};
		});
		console.log(`\n== ${naam} (viewport ${meting.vh}, document ${meting.docH})`);
		for (const d of meting.doelen)
			console.log(
				`  ${String(d.w).padStart(4)}x${String(d.h).padStart(3)} @ y=${String(d.y).padStart(4)} (${String(d.bereik).padStart(3)}% v/h scherm)  ${d.t}`
			);
		console.log(`  kloof pauze↔stop: ${meting.kloof}`);
		if (page.problems.length) console.log('  consolefouten:', page.problems);
		await page.context().close();
	}
}
await b.close();
console.log('\nbasis:', BASE);
