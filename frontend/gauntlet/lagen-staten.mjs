import { browser, open } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const DIR = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/lagen';
mkdirSync(DIR, { recursive: true });
const ronde = process.argv[2] ?? 'r1';

const b = await browser();
for (const [naam, width] of [['1440', 1440], ['1024', 1024]]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: `/?tab=layers` });
		const later = page.locator('button', { hasText: 'Later' });
		if (await later.count()) await later.first().click().catch(() => {});
		if (width < 1200) {
			const opener = page.locator('button[aria-label*="igenschap"]');
			if (await opener.count()) await opener.first().click().catch(() => {});
		}
		await page.waitForTimeout(500);

		// Meten is het argument; het plaatje is het archief.
		const maten = await page.$$eval('.layer', (rows) =>
			rows.slice(0, 3).map((r) => {
				const box = r.getBoundingClientRect();
				const knop = (sel) => {
					const n = r.querySelector(sel);
					if (!n) return null;
					const b = n.getBoundingClientRect();
					return [Math.round(b.width), Math.round(b.height)];
				};
				const veld = r.querySelector('.val input');
				const vb = veld?.getBoundingClientRect();
				return {
					h: Math.round(box.height),
					overflow: Math.round(box.right - r.parentElement.getBoundingClientRect().right),
					chip: knop('.chip'),
					out: knop('.out'),
					more: knop('.more'),
					veld: vb ? [Math.round(vb.width), Math.round(vb.height)] : null
				};
			})
		);
		console.log(naam, theme, JSON.stringify(maten));

		// 1. editor open op laag 2
		const dots = page.locator('.layer .more');
		if (await dots.count()) {
			await dots.nth(1).click();
			await page.waitForTimeout(400);
			await page.screenshot({ path: `${DIR}/${ronde}-editor-${naam}-${theme}.png` });
			await dots.nth(1).click();
		}

		// 2. met selectie: alles selecteren via het toetsenbord, dan zijn de
		//    "hierin"-knoppen zichtbaar zonder op de vorm te hoeven mikken.
		await page.locator('canvas, .canvas').first().click({ position: { x: 8, y: 8 } }).catch(() => {});
		await page.keyboard.press('Control+a');
		await page.keyboard.press('Meta+a');
		await page.waitForTimeout(700);
		await page.screenshot({ path: `${DIR}/${ronde}-selectie-${naam}-${theme}.png` });

		if (page.problems?.length) console.log(naam, theme, page.problems.slice(0, 3));
		await page.context().close();
	}
}
await b.close();
console.log('klaar staten', ronde);
