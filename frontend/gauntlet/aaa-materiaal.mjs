/**
 * Screenshots van het materiaal-oppervlak: bibliotheek, presetkaart, Presetariat.
 *
 * Ronde-nummer als argument: `node gauntlet/aaa-materiaal.mjs r1`.
 */
import { browser, open, BASE } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const ronde = process.argv[2] ?? 'r1';
const dir = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/materiaal';
mkdirSync(dir, { recursive: true });

async function wegmetHerstel(page) {
	// Het herstelvenster van een vorige sessie fotografeert een backdrop.
	const later = page.getByRole('button', { name: /Later|Annuleren/ }).first();
	if (await later.isVisible().catch(() => false)) await later.click().catch(() => {});
	// Sinds de eerste-start-poort staat er op een schoon profiel een venster
	// vóór de studio; zonder die klik is de bibliotheek onbereikbaar.
	// Let op: dit is een knop, geen link. Een klik via getByText landt op de
	// omhullende doos en doet niets — dat kostte me een ronde.
	const rond = page.getByRole('button', { name: 'Rondkijken zonder machine' });
	if (await rond.count()) {
		await rond.click().catch(() => {});
		await page.waitForSelector('.statusbar', { timeout: 10000 }).catch(() => {});
		await page.waitForTimeout(600);
	}
}

/** Opent de materiaalbibliotheek via de rail; geeft false als die er niet is. */
async function openBibliotheek(page) {
	const knop = page.locator('button[title="Materiaalbibliotheek"]:visible');
	if (!(await knop.count())) {
		// Op smallere schermen zit hij achter "Meer".
		const meer = page.locator('button[title*="Meer"]:visible, button[title*="meer"]:visible').first();
		if (await meer.count()) {
			await meer.click();
			await page.waitForTimeout(400);
		}
	}
	if (!(await knop.count())) return false;
	await knop.first().click();
	await page.waitForTimeout(600);
	return true;
}

async function openCatalogus(page) {
	const knop = page.locator('button[title^="Presetariat"]');
	if (!(await knop.count()) || !(await knop.first().isVisible().catch(() => false))) return false;
	await knop.first().click();
	await page.waitForTimeout(900);
	return true;
}

const b = await browser();
console.log('base', BASE);

for (const [naam, width] of [
	['desktop', 1440],
	['tablet', 1024],
	['telefoon', 390]
]) {
	for (const theme of ['licht', 'donker']) {
		const page = await open(b, { width, theme: theme === 'donker' ? 'dark' : 'light' });
		await wegmetHerstel(page);
		const gelukt = await openBibliotheek(page);
		await page.screenshot({
			path: `${dir}/${ronde}-bibliotheek-${naam}-${theme}.png`,
			fullPage: false
		});
		console.log(`${ronde} bibliotheek ${naam} ${theme}: ${gelukt ? 'open' : 'GEEN INGANG'}`);
		if (gelukt) {
			// De groepen staan onder de "onlangs"-sectie; zonder scrollen zie je
			// de materiaalbanden nooit.
			await page.evaluate(() => {
				const vak = [...document.querySelectorAll('*')].find(
					(n) => n.scrollHeight > n.clientHeight + 40 && n.closest('dialog, [role=dialog]')
				);
				(vak ?? document.scrollingElement)?.scrollBy(0, 520);
			});
			await page.waitForTimeout(300);
			await page.screenshot({ path: `${dir}/${ronde}-groepen-${naam}-${theme}.png` });
			// De herkomst van een gemeten preset: dáár zit de foto in.
			const herkomst = page
				.locator('article.ok')
				.first()
				.getByRole('button', { name: 'Herkomst' });
			if (await herkomst.isVisible().catch(() => false)) {
				await herkomst.click();
				await page.waitForTimeout(400);
				await page.screenshot({ path: `${dir}/${ronde}-herkomst-${naam}-${theme}.png` });
				await herkomst.click();
			}
		}
		if (gelukt && width >= 1024) {
			// Bewerken opengeklapt: hoe ziet de kaart eruit als je hem aanpast.
			const bewerk = page.getByRole('button', { name: 'Bewerken' }).first();
			if (await bewerk.isVisible().catch(() => false)) {
				await bewerk.click();
				await page.waitForTimeout(400);
				await page.screenshot({ path: `${dir}/${ronde}-bewerken-${naam}-${theme}.png` });
			}
		}
		await page.keyboard.press('Escape');
		await page.waitForTimeout(400);
		const cat = await openCatalogus(page);
		if (cat) {
			await page.screenshot({ path: `${dir}/${ronde}-presetariat-${naam}-${theme}.png` });
		}
		console.log(`${ronde} presetariat ${naam} ${theme}: ${cat ? 'open' : 'GEEN INGANG'}`);
		await page.context().close();
	}
}
await b.close();
