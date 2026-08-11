/**
 * Screenshots van het testraster-oppervlak: wizard, voorbeeld, resultaat-overlay.
 * Draaien vanuit frontend/ met OK_BASE op de eigen poort.
 */
import { browser, open } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/testraster';
mkdirSync(OUT, { recursive: true });

const ronde = process.argv[2] ?? 'r1';

async function weg(page) {
	// Herstelvenster van een vorige sessie wegklikken.
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(200);
}

async function openRaster(page) {
	const knop = page.locator('button[title="Testraster"]');
	if (!(await knop.first().isVisible().catch(() => false))) {
		// Tablet: het testraster zit achter "Meer gereedschap".
		const meer = page.locator('button[title="Meer gereedschap"]');
		if (await meer.count()) await meer.first().click().catch(() => {});
		await page.waitForTimeout(300);
	}
	if (await knop.count()) {
		await knop.first().click();
		await page.waitForTimeout(900);
		return true;
	}
	return false;
}

const b = await browser();
for (const [naam, width] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/' });
		await weg(page);
		if (width === 390) {
			await page.screenshot({ path: `${OUT}/${ronde}-telefoon-${theme}.png`, fullPage: true });
			await page.context().close();
			continue;
		}
		const ok = await openRaster(page);
		if (!ok) {
			console.log('geen testrasterknop op', naam);
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-geenknop.png` });
			await page.context().close();
			continue;
		}
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-instap.png` });

		// Het formulier openklappen als het dicht staat.
		const openen = page.getByRole('button', { name: /^Openen$/ });
		if (await openen.count()) {
			await openen.first().click().catch(() => {});
			await page.waitForTimeout(900);
		}
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-wizard.png` });

		// Stap 1 afmaken: materiaal kiezen en tekenen.
		const mat = page.locator('select').first();
		await mat.selectOption({ index: 1 }).catch(() => {});
		await page.waitForTimeout(600);
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-ingevuld.png` });
		const teken = page.getByRole('button', { name: /Raster tekenen/ });
		if (await teken.count()) {
			await teken.first().click().catch(() => {});
			await page.waitForTimeout(2500);
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-getekend.png` });
		}

		// Resultaat: raster 1 kiezen (heeft een foto)
		const picker = page.locator('select.picker');
		if (await picker.count()) {
			await picker.first().selectOption({ index: await picker.locator('option', { hasText: 'met foto' }).first().evaluate((o) => o.index) });
			await page.waitForTimeout(600);
			await page.screenshot({
				path: `${OUT}/${ronde}-${naam}-${theme}-resultaat.png`,
				fullPage: false
			});
			// Scrollen naar de overlay zelf
			const stage = page.locator('.podium, .geenfoto').last();
			if (await stage.count()) {
				await stage.scrollIntoViewIfNeeded().catch(() => {});
				await page.waitForTimeout(300);
				await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-overlay.png` });
				// Een vakje aantikken: hoe ziet de keuze eruit?
				const cellen = page.locator('.podium svg polygon');
				if (await cellen.count()) {
					await cellen.nth(5).click({ force: true }).catch(() => {});
					await page.waitForTimeout(300);
					await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-gekozen.png` });
				}
			}
			// raster 2: zonder foto
			await picker.first().selectOption({ index: await picker.locator('option', { hasText: 'wacht op foto' }).first().evaluate((o) => o.index) });
			await page.waitForTimeout(500);
			await page.locator('.geenfoto, .podium').last().scrollIntoViewIfNeeded().catch(() => {});
			await page.waitForTimeout(200);
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-geenfoto.png` });
		}
		if (page.problems.length) console.log(naam, theme, 'console:', page.problems.slice(0, 3));
		await page.context().close();
	}
}
await b.close();
console.log('klaar', ronde);
