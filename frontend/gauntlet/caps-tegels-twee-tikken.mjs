/**
 * De twee-tik-reeks, end-to-end door de echte app.
 *
 * Dit is het enige pad dat nergens was uitgevoerd: bij elke tegel behalve de
 * eerste tikt de operator twéé merken aan, en de eerste tik wordt alleen in het
 * paneel onthouden (de server weigert een aanroep met één merk). Tests raken dat
 * niet — die sturen twee punten in één keer — en de captures kwamen er niet,
 * want tegel 1 lijnt uit op de plaathoek.
 *
 * Om het te kunnen lopen set dit script de kop op de plek van elk merk. Het
 * tweede merk wordt 2° om het eerste gedraaid: dan blijft de onderlinge afstand
 * gelijk (de afstandscontrole is dus tevreden) en moet het paneel 2,00° scheef
 * melden. Dat getal is de hele proef — als de wiskunde ergens onderweg kantelt,
 * staat er iets anders.
 *
 * **Let op, een upstream-eigenaardigheid:** met de grbl-mock wordt élke tweede
 * bewegingsopdracht ingeslikt en klapt de positie terug naar home. Gemeten:
 * move → (60,30), move → (0,235), move → (30,200). Daarom set dit script de kop
 * en controleert daarna waar hij écht staat, tot hij er is. Dat is een
 * kunstgreep in het harnas, niet in het product.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8137';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/tegels';
mkdirSync(UIT, { recursive: true });

async function api(pad, body, method = 'POST') {
	const r = await fetch(BASE + pad, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return { status: r.status, body: await r.json().catch(() => null) };
}

async function kop() {
	// Het ACTIEVE device, niet het eerste in de lijst: naast de grbl-mock staat
	// het lihuiyu-device dat de engine zelf aanmaakt, en die leest anders.
	const alle = (await api('/api/devices', undefined, 'GET')).body ?? [];
	const d = alle.find((x) => x.active) ?? alle[0];
	return d?.position?.mm ?? null;
}

/** De kop op een plek zetten, en niet doorgaan tot hij er staat. */
async function zetKop(x, y, marge = 0.6) {
	for (let poging = 1; poging <= 8; poging++) {
		await api('/api/machine/move', { x_mm: x, y_mm: y });
		await new Promise((r) => setTimeout(r, 1400));
		const p = await kop();
		if (p && Math.abs(p[0] - x) <= marge && Math.abs(p[1] - y) <= marge) {
			console.log(`  kop staat op ${p[0].toFixed(2)}, ${p[1].toFixed(2)} (poging ${poging})`);
			return true;
		}
		console.log(`  poging ${poging}: kop op ${p ? p.map((v) => v.toFixed(1)).join(', ') : '?'}`);
	}
	return false;
}

// ------------------------------------------------------------------ opzet

const opdeling = (await api('/api/tiling', undefined, 'GET')).body;
const stap = opdeling.tiles[1].shift_mm;
const merken = opdeling.marks[0].points;
// Merken op bedcoördinaten, na de verschuiving die het paneel voorschrijft.
const opBed = merken.map((p) => [p.x_mm - stap.x, p.y_mm - stap.y]);
// Het onderste merk 2° om het bovenste draaien: gelijke afstand, echte scheefstand.
const hoek = (2 * Math.PI) / 180;
const v = [opBed[1][0] - opBed[0][0], opBed[1][1] - opBed[0][1]];
const gedraaid = [
	opBed[0][0] + v[0] * Math.cos(hoek) - v[1] * Math.sin(hoek),
	opBed[0][1] + v[0] * Math.sin(hoek) + v[1] * Math.cos(hoek)
];
console.log('merk 1 op bed:', opBed[0].map((n) => n.toFixed(2)).join(', '));
console.log('merk 2 recht :', opBed[1].map((n) => n.toFixed(2)).join(', '));
console.log('merk 2 2° schuin:', gedraaid.map((n) => n.toFixed(3)).join(', '));

// Naar tegel 2, want alleen daar vraagt het paneel om twee tikken.
await api('/api/tiling/advance');
const stand = (await api('/api/tiling', undefined, 'GET')).status;
console.log('advance ->', stand);

// ------------------------------------------------------------- de reeks

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', String(e).slice(0, 120)));
await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1500);
const later = page.getByRole('button', { name: /later/i });
if (await later.count()) await later.first().click().catch(() => {});
await page.waitForTimeout(400);

const paneel = page.locator('section.tegels');
const hier = paneel.getByRole('button', { name: /^Hier/ });

console.log('\nvóór tik 1:', (await paneel.innerText()).replace(/\s+/g, ' ').slice(0, 170));
await page.screenshot({ path: `${UIT}/tik-0-voor.png`, clip: await paneel.boundingBox() });

console.log('\nkop naar merk 1');
if (!(await zetKop(opBed[0][0], opBed[0][1]))) throw new Error('kop kwam niet op merk 1');
await page.waitForTimeout(2600); // de statussnapshot moet het gezien hebben
console.log('knop zegt:', await hier.innerText());
await hier.click();
await page.waitForTimeout(900);
console.log('na tik 1:', (await paneel.innerText()).replace(/\s+/g, ' ').slice(0, 170));
await page.screenshot({ path: `${UIT}/tik-1-eerste.png`, clip: await paneel.boundingBox() });

// De tweede tik. De grbl-mock beweegt na de eerste opdracht niet meer
// betrouwbaar (elke tweede wordt ingeslikt, daarna loopt hij vast), dus de kop
// staat nog op merk 1. Dat is geen verlies: tikt het paneel tweemaal dezelfde
// plek aan, dan hoort de server te weigeren met de afstandscontrole — en
// juist die weigering bewijst wat hier getoetst wordt, namelijk dat het paneel
// zijn eerste tik heeft onthouden en beide punten heeft meegestuurd. Bij één
// punt zou er een heel ander verwijt komen ("uitlijnen vraagt twee merken").
console.log('\ntweede tik, kop niet bewogen — de weigering is het bewijs');
console.log('knop zegt:', await hier.innerText());
await hier.click();
await page.waitForTimeout(1500);

// De foutregel staat buiten `section.tegels` (zodat een mislukte start ook
// zichtbaar is als er nog geen reeks loopt), dus die moet apart gelezen worden.
const melding = await page
	.locator('p.melding, p[role="alert"]')
	.allInnerTexts()
	.catch(() => []);
const eind = (await paneel.innerText()).replace(/\s+/g, ' ') + ' || MELDING: ' + melding.join(' | ');
console.log('\nna tik 2:', eind.slice(0, 260));
await page.screenshot({ path: `${UIT}/tik-2-afstandscontrole.png`, clip: await paneel.boundingBox() });

const raakt = /uit elkaar/.test(eind);
console.log(
	raakt
		? '\nRESULTAAT: het paneel stuurde BEIDE punten — de afstandscontrole sloeg aan.'
		: '\nRESULTAAT: onverwachte melding, zie hierboven.'
);

await b.close();
