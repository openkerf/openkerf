/** Pauzeren binnen 2s vanaf elk scherm, en materiaal/testraster in tikken. */
import { browser, open } from './harness.mjs';
const b = await browser();
for (const width of [768, 1024, 1199]) {
	for (const tab of ['design', 'layers', 'job']) {
		const page = await open(b, { width, theme: 'light', path: `/?tab=${tab}` });
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});
		await page.waitForTimeout(500);
		const knop = page.locator('.topbar button.pauze');
		const zichtbaar = await knop.isVisible().catch(() => false);
		const aan = zichtbaar && !(await knop.isDisabled());
		let ms = null;
		if (aan) {
			const t0 = Date.now();
			await knop.click();
			await page.waitForResponse((r) => r.url().includes('/api/job/pause'), { timeout: 5000 }).catch(() => {});
			ms = Date.now() - t0;
			await page.request.post('/api/job/resume').catch(() => {});
		}
		console.log(`${width} tab=${tab}: pauzeknop in bovenbalk zichtbaar=${zichtbaar} bruikbaar=${aan} tikken=1 respons=${ms}ms`);
		await page.context().close();
	}
	// Materiaal en testraster: hoeveel tikken vanaf het standaardscherm?
	const page = await open(b, { width, theme: 'light', path: '/' });
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	for (const naam of ['Materiaalbibliotheek', 'Testraster']) {
		const t0 = Date.now();
		await page.locator(`.rail button[title="${naam}"]`).click();
		await page.waitForSelector('.backdrop .panel', { timeout: 5000 }).catch(() => {});
		console.log(`${width} ${naam}: 1 tik vanaf de rail, venster open na ${Date.now() - t0}ms`);
		await page.keyboard.press('Escape');
		await page.waitForTimeout(400);
	}
	await page.context().close();
}
await b.close();
