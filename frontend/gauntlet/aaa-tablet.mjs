/**
 * Tablet-gedaante (768–1199): screenshots op de randen van het bereik plus
 * metingen van raakdoelen. De metingen zijn het argument, de beelden het bewijs.
 */
import { browser, open } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/tablet';
const ronde = process.argv[2] ?? 'r1';
const b = await browser();

/** Alles wat je met een vinger kunt raken, met doos. */
async function doelen(page) {
	return page.$$eval('button, a[href], label.btn, label.tool, input[type=range]', (nodes) =>
		nodes
			.filter((n) => {
				const r = n.getBoundingClientRect();
				return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== 'hidden';
			})
			.map((n) => {
				const r = n.getBoundingClientRect();
				return {
					wat: (n.getAttribute('title') || n.getAttribute('aria-label') || n.textContent || '')
						.trim()
						.slice(0, 38),
					cls: String(n.className?.baseVal ?? n.className ?? '').slice(0, 30),
					x: Math.round(r.x), y: Math.round(r.y),
					w: Math.round(r.width), h: Math.round(r.height)
				};
			})
	);
}

const rapport = [];

for (const width of [768, 1024, 1199]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/?tab=job' });
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});
		await page.waitForTimeout(400);
		await page.screenshot({ path: `${OUT}/${ronde}-${width}-${theme}-job.png` });

		if (width === 1024 && theme === 'light') {
			// Rail uitgeklapt
			const meer = page.locator('button[title="Meer"]');
			if (await meer.count()) {
				await meer.first().click();
				await page.waitForTimeout(300);
				await page.screenshot({ path: `${OUT}/${ronde}-1024-light-rail-uit.png` });
				// Buiten het menu tikken moet het sluiten (er is geen Escape-toets
				// op een tablet); de afdeklaag vangt die tik.
				await page.locator('.afdek').click({ position: { x: 500, y: 400 } });
				await page.waitForTimeout(250);
				if (await page.locator('.menu').count()) throw new Error('menu sluit niet bij tikken buiten');
			}
			// Paneel ingeklapt
			const greep = page.locator('.paneelgreep');
			if (await greep.count()) {
				await greep.first().click();
				await page.waitForTimeout(350);
				await page.screenshot({ path: `${OUT}/${ronde}-1024-light-paneel-dicht.png` });
				await greep.first().click();
				await page.waitForTimeout(300);
			}
			// Lagen-tab
			await page.getByRole('tab', { name: 'Lagen' }).click().catch(() => {});
			await page.waitForTimeout(400);
			await page.screenshot({ path: `${OUT}/${ronde}-1024-light-lagen.png` });
		}

		const t = await doelen(page);
		const klein = t.filter((d) => d.w < 44 || d.h < 44);
		rapport.push({ width, theme, totaal: t.length, klein: klein.length, voorbeelden: klein.slice(0, 14) });
		if (page.problems?.length) rapport.push({ width, theme, console: page.problems.slice(0, 4) });
		await page.context().close();
	}
}

console.log(JSON.stringify(rapport, null, 1));
await b.close();
