/**
 * Werkt "omkeerbaar" echt?
 *
 * Twee beloften worden hier getoetst, niet bekeken:
 *  1. Doorklikken stapelt niet. Twee keer spiegelen is terug bij af, en het
 *     hoekveld toont de stand van de vorm in plaats van een optelsom.
 *  2. "Terugzetten" brengt de selectie exact terug op de stand van vóór het
 *     schikken — hoek, spiegeling én kader, tot op een tiende millimeter.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8131';

async function stand(id) {
	const d = await (await fetch(`${BASE}/api/design`)).json();
	const e = d.elements.find((x) => x.id === id);
	const m = d.units_per_mm;
	return {
		hoek: e.pose.angle_deg,
		gespiegeld: e.pose.mirrored,
		box: e.bounds.map((v) => +(v / m).toFixed(2))
	};
}

const d = await (await fetch(`${BASE}/api/design`)).json();
const id = d.elements[0].id;

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
await page.goto(`${BASE}/?tab=design&select=${id}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1200);
const later = page.getByRole('button', { name: /later/i });
if (await later.count()) await later.first().click().catch(() => {});
await page.waitForTimeout(400);

const klik = async (naam) => {
	await page.getByRole('button', { name: naam, exact: true }).first().click();
	await page.waitForTimeout(800);
};
const veld = () => page.getByLabel('Hoek in graden').inputValue();

const begin = await stand(id);
console.log('begin           ', JSON.stringify(begin), 'veld=', await veld());

await klik('Horizontaal spiegelen');
console.log('1x spiegelen    ', JSON.stringify(await stand(id)), 'veld=', await veld());
await klik('Horizontaal spiegelen');
const terugGespiegeld = await stand(id);
console.log('2x spiegelen    ', JSON.stringify(terugGespiegeld), 'veld=', await veld());
console.log(
	'  → stapelt niet:',
	JSON.stringify(terugGespiegeld) === JSON.stringify(begin) ? 'JA' : 'NEE'
);

await klik('+90 graden draaien');
await klik('+90 graden draaien');
console.log('2x +90          ', JSON.stringify(await stand(id)), 'veld=', await veld());
await klik('Horizontaal spiegelen');
console.log('+ spiegelen     ', JSON.stringify(await stand(id)), 'veld=', await veld());
await klik('+1 graden draaien');
console.log('+1              ', JSON.stringify(await stand(id)), 'veld=', await veld());

// De hoek intikken: een bestemming, geen stap. Twee keer hetzelfde getal moet
// twee keer hetzelfde beeld geven.
const invoer = page.getByLabel('Hoek in graden');
await invoer.fill('45');
await invoer.press('Enter');
await page.waitForTimeout(900);
const na45 = await stand(id);
await invoer.fill('45');
await invoer.press('Enter');
await page.waitForTimeout(900);
const naNog45 = await stand(id);
console.log('hoek 45 ingetikt', JSON.stringify(na45), 'veld=', await veld());
console.log(
	'  → nogmaals 45 verandert niets:',
	JSON.stringify(na45) === JSON.stringify(naNog45) ? 'JA' : 'NEE'
);

await klik('Terugzetten');
const terug = await stand(id);
console.log('terugzetten     ', JSON.stringify(terug));
const gelijk =
	Math.abs(terug.hoek - begin.hoek) < 0.05 &&
	terug.gespiegeld === begin.gespiegeld &&
	terug.box.every((v, i) => Math.abs(v - begin.box[i]) < 0.1);
console.log('  → exact terug op het origineel:', gelijk ? 'JA' : 'NEE');
console.log(
	'  → knop weg na terugzetten:',
	(await page.getByRole('button', { name: 'Terugzetten' }).count()) === 0 ? 'JA' : 'NEE'
);

await b.close();
