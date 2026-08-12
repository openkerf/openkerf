/**
 * Besluit B1: materiaal en dikte als eigenschap van het vel.
 *
 * Vier oppervlakken in één ronde, want ze horen bij elkaar: de knop in de
 * bovenbalk, het venster erachter, de bibliotheek die erop filtert en de
 * pre-flight die erover waarschuwt.
 */
import { browser, open, BASE } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/b1/';
const ronde = process.argv[2] ?? 'v2';

async function weg(page) {
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(250);
}

async function sluit(page) {
	await page.keyboard.press('Escape');
	await page.waitForTimeout(250);
	while (await page.locator('.backdrop').count()) {
		await page.locator('.backdrop').first().click({ position: { x: 4, y: 4 } });
		await page.waitForTimeout(250);
	}
}

const b = await browser();
for (const [naam, w] of [
	['1440', 1440],
	['1024', 1024],
	['390', 390]
]) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width: w, theme, path: '/?tab=design' });
		await weg(page);
		await page.screenshot({ path: `${OUT}${ronde}-balk-${naam}-${theme}.png` });

		if (w >= 768 && process.env.LEEG) {
			// Nog niets gekozen: de knop moet dat zeggen zonder te alarmeren.
			await page.locator('button.materiaal').first().click();
			await page.waitForTimeout(450);
			await page.screenshot({ path: `${OUT}${ronde}-leeg-venster-${naam}-${theme}.png` });
			await sluit(page);
			await page.screenshot({ path: `${OUT}${ronde}-leeg-balk-${naam}-${theme}.png` });
			await page.close();
			continue;
		}

		if (w >= 768) {
			// Het venster achter de knop.
			await page.locator('button.materiaal').first().click();
			await page.waitForTimeout(450);
			await page.screenshot({ path: `${OUT}${ronde}-venster-${naam}-${theme}.png` });
			await sluit(page);

			// De bibliotheek, gefilterd op het materiaal van het vel.
			const bieb = page.locator('button[title="Materiaalbibliotheek"]');
			if (!(await bieb.first().isVisible().catch(() => false))) {
				await page.locator('button[title="Meer gereedschap"]').first().click().catch(() => {});
				await page.waitForTimeout(250);
			}
			await bieb.first().click();
			await page.waitForTimeout(700);
			await page.screenshot({ path: `${OUT}${ronde}-bibliotheek-${naam}-${theme}.png` });
			await sluit(page);

			// De pre-flight met een instelling van ánder materiaal.
			await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
			await page.waitForTimeout(900);
			await weg(page);
			const start = page.locator('button.btn.primary', { hasText: 'Start' });
			await start.first().click().catch(() => {});
			await page.waitForTimeout(2500);
			await page.screenshot({ path: `${OUT}${ronde}-preflight-${naam}-${theme}.png` });
		}
		await page.close();
	}
}
await b.close();
console.log('klaar');
