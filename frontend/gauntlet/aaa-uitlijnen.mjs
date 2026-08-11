/**
 * De uitlijnstap echt uitvoeren: vier hoeken naar de hoeken van het gebrande
 * raster slepen en dan een vakje aanwijzen. Zonder dit meet je alleen de
 * beginstand, en juist de eindstand is waar de flow op staat of valt.
 */
import { browser, open } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/testraster';
const ronde = process.argv[2] ?? 'r4';

// De nepfoto: bord van 66 mm met het raster van 38 mm op 14 mm marge, plus een
// scheefstand van 0,6 mm per rij.
const DOEL = [
	[14 / 66, 14 / 66],
	[52 / 66, 14 / 66],
	[(52 + 1.8) / 66, 52 / 66],
	[(14 + 1.8) / 66, 52 / 66]
];

const b = await browser();
for (const [naam, width] of [['desktop', 1440], ['tablet', 1024]]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/' });
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});

		const knop = page.locator('button[title="Testraster"]');
		if (!(await knop.first().isVisible().catch(() => false))) {
			await page.locator('button[title="Meer gereedschap"]').first().click().catch(() => {});
			await page.waitForTimeout(300);
		}
		await knop.first().click();
		await page.waitForTimeout(900);

		const picker = page.locator('select.picker');
		await picker
			.first()
			.selectOption({
				index: await picker.locator('option', { hasText: '#1 ' }).first().evaluate((o) => o.index)
			});
		await page.waitForTimeout(700);
		await page.locator('.podium').first().scrollIntoViewIfNeeded();
		await page.waitForTimeout(300);

		const doos = await page.locator('.podium').first().boundingBox();
		for (let i = 0; i < 4; i++) {
			const h = page.locator('.hoek').nth(i);
			const hb = await h.boundingBox();
			await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
			await page.mouse.down();
			await page.mouse.move(doos.x + DOEL[i][0] * doos.width, doos.y + DOEL[i][1] * doos.height, {
				steps: 8
			});
			await page.mouse.up();
			await page.waitForTimeout(120);
		}
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-uitgelijnd.png` });

		await page.getByRole('button', { name: 'Uitlijnen klaar' }).click();
		await page.waitForTimeout(300);
		// Het donkerste vakje: rij 0, kolom 3 — dat is wat je in het echt kiest.
		const cel = page.locator('.podium svg polygon').nth(3);
		await cel.hover();
		await page.waitForTimeout(200);
		await cel.click();
		await page.waitForTimeout(300);
		await page.mouse.move(doos.x + doos.width / 2, doos.y - 40);
		await page.waitForTimeout(200);
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-gekozen.png` });

		if (page.problems.length) console.log(naam, theme, page.problems.slice(0, 3));
		await page.context().close();
	}
}
await b.close();
console.log('klaar', ronde);
