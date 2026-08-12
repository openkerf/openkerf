/**
 * Metingen bij besluit B8: contrast en maten van de pre-flight-weergave.
 *
 * Kleurverschil tussen het vel en wat eromheen ligt is de enige manier waarop
 * "dit valt van je materiaal af" leesbaar is. WCAG 1.4.11 vraagt 3:1 voor
 * grafische objecten, en dat is hier de lat.
 */
import { browser, open, BASE } from './harness.mjs';

async function api(path, body, method) {
	const r = await fetch(BASE + path, {
		method: method ?? (body ? 'POST' : 'GET'),
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return r.status === 204 ? null : r.json().catch(() => null);
}

await api('/api/design/autosave', undefined, 'DELETE').catch(() => {});
await api('/api/design/clear', {});
for (let i = 0; i < 3; i++)
	await api('/api/design/elements', {
		type: 'rect', x_mm: 20 + i * 70, y_mm: 25, width_mm: 55, height_mm: 55
	});
await api('/api/design/elements', { type: 'rect', x_mm: 275, y_mm: 150, width_mm: 70, height_mm: 45 });

const b = await browser();
for (const width of [1440, 1024]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/?tab=job' });
		await page.getByRole('button', { name: /Later/ }).click({ timeout: 1000 }).catch(() => {});
		await page.getByRole('button', { name: /^(Job starten|Start(\s*job)?)$/i }).first().click();
		await page.waitForSelector('.pf-beeld svg', { timeout: 8000 });
		await page.waitForTimeout(600);

		const m = await page.evaluate(() => {
			const lees = (el, prop) => getComputedStyle(el)[prop];
			const svg = document.querySelector('.pf-beeld svg');
			const vel = svg.querySelector('.vel');
			const hatch = svg.querySelector('.arcering');
			const buiten = svg.querySelector('.vorm.buiten');
			const stil = svg.querySelector('.vorm.stil');
			const r = svg.getBoundingClientRect();
			const paneel = svg.closest('.preflight').getBoundingClientRect();
			return {
				svgBox: [Math.round(r.width), Math.round(r.height)],
				paneelBreedte: Math.round(paneel.width),
				achtergrond: lees(svg, 'backgroundColor'),
				velVulling: lees(vel, 'fill'),
				velRand: lees(vel, 'stroke'),
				arcering: hatch ? lees(hatch, 'stroke') : null,
				tekst2: getComputedStyle(document.documentElement).getPropertyValue('--text-2').trim(),
				buitenLijn: buiten ? lees(buiten, 'stroke') : null,
				stilLijn: stil ? lees(stil, 'stroke') : null,
				velTop: Math.round(r.top),
				vensterHoogte: window.innerHeight
			};
		});

		const rgb = (s) => (s.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
		const lum = (c) =>
			c.map((v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4))
				.reduce((a, k, i) => a + [0.2126, 0.7152, 0.0722][i] * k, 0);
		const ratio = (a, b2) => {
			const [x, y] = [lum(rgb(a)), lum(rgb(b2))];
			return ((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2);
		};

		console.log(`\n${width}px ${theme}`);
		console.log(`  weergave ${m.svgBox[0]}×${m.svgBox[1]} px in een paneel van ${m.paneelBreedte} px`);
		console.log(`  boven de vouw: ${m.velTop < m.vensterHoogte ? 'ja' : 'nee'} (top ${m.velTop} van ${m.vensterHoogte})`);
		console.log(`  vel ${m.velVulling} tegen omgeving ${m.achtergrond}: ${ratio(m.velVulling, m.achtergrond)}:1`);
		console.log(`  velrand ${m.velRand} tegen vel: ${ratio(m.velRand, m.velVulling)}:1`);
		if (m.arcering) console.log(`  arcering ${m.arcering} tegen vel: ${ratio(m.arcering, m.velVulling)}:1`);
		console.log(`  --text-2 zou geven: ${ratio(m.tekst2, m.velVulling)}:1`);
		if (m.buitenLijn) console.log(`  buiten-lijn ${m.buitenLijn} tegen vel: ${ratio(m.buitenLijn, m.velVulling)}:1`);
		if (m.stilLijn) console.log(`  stil-lijn ${m.stilLijn} tegen vel: ${ratio(m.stilLijn, m.velVulling)}:1`);
		if (page.problems.length) console.log(`  FOUT: ${page.problems[0]}`);
		await page.context().close();
	}
}
await b.close();
