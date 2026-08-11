/**
 * Meten in plaats van vinden: hoeveel handelingen kost het om de instelling
 * van gisteren terug te zetten, en staat hij zonder scrollen in beeld?
 */
import { browser, open } from './harness.mjs';

const b = await browser();
for (const [naam, width] of [
	['desktop', 1440],
	['tablet', 1024]
]) {
	const page = await open(b, { width, theme: 'light' });
	const later = page.getByRole('button', { name: /Later|Annuleren/ }).first();
	if (await later.isVisible().catch(() => false)) await later.click().catch(() => {});

	const start = Date.now();
	let klikken = 0;
	const knop = page.locator('button[title="Materiaalbibliotheek"]').first();
	if (!(await knop.isVisible().catch(() => false))) {
		// Op tablet zit de bibliotheek achter "Meer gereedschap".
		await page.locator('button[title="Meer gereedschap"]').first().click();
		klikken++;
	}
	await knop.click();
	klikken++;
	await page.waitForSelector('article', { timeout: 5000 });

	// De klus van gisteren: 3 mm multiplex snijden.
	const kaart = page.locator('article', { hasText: 'Multiplex berken, 3 mm Snijden' }).first();
	const doos = await kaart.boundingBox();
	const venster = page.viewportSize();
	const zichtbaar = doos && doos.y >= 0 && doos.y + Math.min(doos.height, 120) <= venster.height;

	await kaart.getByRole('button', { name: /Toepassen/ }).click();
	klikken++;
	await page.waitForTimeout(400);
	const ms = Date.now() - start;

	// Hoeveel tekst moet je lezen voordat je hem herkent?
	const kop = (await kaart.locator('.titel').first().innerText()).replace(/\s+/g, ' ');
	console.log(
		`${naam}: ${klikken} klikken, ${ms} ms machinaal, zonder scrollen zichtbaar: ${zichtbaar}, ` +
			`y=${doos ? Math.round(doos.y) : '?'} — kaarttekst "${kop}"`
	);

	// Kwam het aan?
	const design = await page.evaluate(async () => {
		const r = await fetch('/api/design');
		const d = await r.json();
		return d.operations.map((o) => `${o.label}: ${o.speed} mm/s ${o.power}`);
	});
	console.log(`   lagen na toepassen: ${design.join(' | ')}`);
	await page.context().close();
}
await b.close();
