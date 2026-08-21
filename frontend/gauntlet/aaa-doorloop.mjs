/**
 * De echte taak: nieuwe gebruiker, klik voor klik, van koude start tot job.
 * Elke klik wordt gelogd met wat er zichtbaar was, zodat "wat nu?" telbaar is.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/eerste-start';
mkdirSync(OUT, { recursive: true });
const ronde = process.argv[2] ?? 'r1';

const b = await browser();
const page = await open(b, { width: 1440, theme: 'light', path: '/setup/kind' });

async function stap(naam, fn) {
	await fn();
	await page.waitForTimeout(900);
	await page.screenshot({ path: `${OUT}/${ronde}-flow-${naam}.png` });
	console.log('→', naam, '|', page.url());
}

await stap('1-soort', async () => {});
await stap('2-model', () => page.click('text=CO2 met Ruida of Newly'));
await stap('3-naam', () => page.locator('a.type').first().click());
await stap('4-instellen', async () => {
	await page.fill('input[type=text]', '5030 CO2');
	await page.click('button.primary');
	await page.waitForTimeout(1500);
});
// Alles wat op de instellen-pagina staat, letterlijk.
console.log('--- instellen, zichtbare tekst ---');
console.log((await page.locator('.setup').innerText()).slice(0, 2500));
await stap('5-klaar', async () => {
	const knop = page.locator('.setup .btn.primary');
	if (await knop.count()) await knop.first().click();
	await page.waitForTimeout(1200);
});
await stap('6-werkgebied', async () => {
	const naar = page.locator('text=Naar het werkgebied');
	if (await naar.count()) await naar.first().click();
	await page.waitForTimeout(2000);
});
console.log('--- bovenbalk ---');
console.log(await page.locator('body').innerText().catch(() => '?'));
await b.close();
