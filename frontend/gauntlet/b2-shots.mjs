/**
 * Screenshots voor B2 (paletstrook met geheugen) en B4 (output/show).
 *
 * Geen reset(): het ontwerp op de server ís de opstelling — vier vormen in
 * drie lagen, een kleur met geheugen zonder laag, en een laag die niet meebrandt.
 */
import { browser, open } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const UIT = new URL('../../screenshots/aaa/b2/', import.meta.url).pathname;
mkdirSync(UIT, { recursive: true });

const b = await browser();
const maten = [
	['1440', 1440],
	['1024', 1024],
	['390', 390]
];

for (const [naam, width] of maten) {
	for (const theme of ['light', 'dark']) {
		for (const [tab, achtervoegsel] of [
			['design', 'canvas'],
			['layers', 'lagen']
		]) {
			const page = await open(b, { width, theme, path: `/?tab=${tab}` });
			// Het herstelvenster wegklikken; anders fotografeer je een backdrop.
			await page
				.getByRole('button', { name: /later/i })
				.click({ timeout: 1500 })
				.catch(() => {});
			await page.waitForTimeout(400);
			await page.screenshot({
				path: `${UIT}${achtervoegsel}-${naam}-${theme}.png`
			});
			if (page.problems.length) console.log(naam, theme, tab, page.problems);
			await page.context().close();
		}
	}
}

// Eén detailopname van de strook met de aanwijzer op een kleur die geheugen
// heeft maar geen laag — dat is het geval dat je anders nooit ziet.
{
	const page = await open(b, { width: 1440, theme: 'light', path: '/?tab=layers' });
	await page.getByRole('button', { name: /later/i }).click({ timeout: 1500 }).catch(() => {});
	const strook = page.locator('.palet');
	await page.locator('.palet .vak').nth(1).hover();
	await page.waitForTimeout(300);
	await strook.screenshot({ path: `${UIT}strook-hover-oranje.png` });
	await page.locator('.palet .vak').nth(0).hover();
	await page.waitForTimeout(300);
	await strook.screenshot({ path: `${UIT}strook-hover-rood.png` });
	await page.context().close();
}

await b.close();
console.log('klaar');
