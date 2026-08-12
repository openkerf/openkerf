/**
 * B4 in beeld: dezelfde drie lagen, maar met laag 2 op onzichtbaar.
 *
 * Eén beeld met de laag zichtbaar en één zonder, zodat het verschil tussen
 * "brandt niet mee" (laag 3, blijft staan) en "verborgen" (laag 2, verdwijnt)
 * naast elkaar te zien is.
 */
import { browser, open } from './harness.mjs';

const UIT = new URL('../../screenshots/aaa/b2/', import.meta.url).pathname;
const b = await browser();

for (const [naam, width, theme] of [
	['1440-light', 1440, 'light'],
	['1440-dark', 1440, 'dark'],
	['1024-light', 1024, 'light']
]) {
	const page = await open(b, { width, theme, path: '/?tab=layers' });
	await page.getByRole('button', { name: /later/i }).click({ timeout: 1500 }).catch(() => {});
	await page.getByRole('switch', { name: /Zichtbaar op het canvas voor Graveren logo/ }).click();
	await page.waitForTimeout(400);
	await page.screenshot({ path: `${UIT}verborgen-${naam}.png` });
	await page.context().close();
}

await b.close();
console.log('klaar');
