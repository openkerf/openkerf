import { browser, open } from './harness.mjs';
const b = await browser();
const page = await open(b, { width: 1440 });
for (const [naam, sel] of [
	['Generatoren (eerst)', 'button[title^="Generatoren"]'],
	['Materiaalbibliotheek', 'button[title="Materiaalbibliotheek"]'],
	['Materiaalbibliotheek (2e poging)', 'button[title="Materiaalbibliotheek"]'],
	['Presetariat', 'button[title^="Presetariat"]'],
	['Generatoren', 'button[title^="Generatoren"]'],
	['Clipart', 'button[title^="Clipart"]'],
	['Testraster', 'button[title="Testraster"]']
]) {
	const knop = await page.$(sel);
	if (!knop) { console.log(naam, '-> knop niet gevonden'); continue; }
	await knop.click({ force: true });
	await page.waitForTimeout(400);
	const open1 = await page.$$eval('.backdrop', (n) => n.length);
	const focus = await page.evaluate(() => document.activeElement?.getAttribute('role') || document.activeElement?.tagName);
	await page.keyboard.press('Escape');
	await page.waitForTimeout(400);
	const open2 = await page.$$eval('.backdrop', (n) => n.length);
	console.log(`${naam}: open=${open1} focus=${focus} na Escape=${open2} ${open2 ? '<-- BLIJFT OPEN' : ''}`);
	if (open2) {
		await page.click('.backdrop', { position: { x: 5, y: 5 } }).catch(() => {});
		await page.waitForTimeout(300);
	}
}
await b.close();
