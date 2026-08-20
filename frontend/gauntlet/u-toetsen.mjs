/**
 * De sneltoetsen echt indrukken en kijken wat er gebeurt.
 *
 * Een sneltoetsentabel is makkelijk te schrijven en makkelijk verkeerd te
 * schrijven: één verkeerde combo-tekst en de toets doet niets, zonder foutmelding.
 */
import { chromium } from 'playwright';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';

async function verse() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	for (const vorm of [
		{ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 },
		{ type: 'rect', x_mm: 120, y_mm: 20, width_mm: 40, height_mm: 40 }
	])
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(vorm)
		});
	return (await (await fetch(`${BASE}/api/design`)).json()).elements.map((e) => e.id);
}

async function aantal() {
	return (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
}

const b = await chromium.launch();
const uitslag = [];

async function proef(naam, toetsen, verwacht) {
	const els = await verse();
	const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
	const page = await ctx.newPage();
	const fouten = [];
	page.on('pageerror', (e) => fouten.push(String(e).slice(0, 120)));
	await page.goto(`${BASE}/?tab=design&select=${els[0]}`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(200);
	// Focus op het canvas, niet in een veld.
	await page.mouse.click(700, 650);
	await page.waitForTimeout(200);
	// De selectie terugzetten na die klik op leeg bed.
	await page.evaluate(() => {});
	await page.goto(`${BASE}/?tab=design&select=${els[0]}`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(800);

	const voor = await verwacht.lees(page);
	for (const toets of toetsen) {
		await page.keyboard.press(toets);
		await page.waitForTimeout(700);
	}
	const na = await verwacht.lees(page);
	const goed = verwacht.toets(voor, na);
	uitslag.push({ naam, toetsen: toetsen.join(' '), voor: String(voor), na: String(na), goed, fouten: fouten.length });
	await ctx.close();
}

const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
const elementen = { lees: () => aantal(), toets: (v, n) => n !== v };

await proef('kopiëren + plakken', [`${MOD}+c`, `${MOD}+v`], { lees: () => aantal(), toets: (v, n) => n === v + 1 });
await proef('knippen', [`${MOD}+x`], { lees: () => aantal(), toets: (v, n) => n === v - 1 });
await proef('knippen + plakken', [`${MOD}+x`, `${MOD}+v`], { lees: () => aantal(), toets: (v, n) => n === v });
await proef('dupliceren', [`${MOD}+d`], { lees: () => aantal(), toets: (v, n) => n === v + 1 });
await proef('verwijderen + ongedaan', ['Delete', `${MOD}+z`], { lees: () => aantal(), toets: (v, n) => n === v });
await proef('alles selecteren', [`${MOD}+a`], {
	lees: (p) => p.evaluate(() => new URL(location.href).searchParams.get('select')?.split(',').length ?? 0),
	toets: (v, n) => n === 2
});
await proef('groeperen', [`${MOD}+a`, `${MOD}+g`], {
	lees: async () => (await (await fetch(`${BASE}/api/design`)).json()).elements.filter((e) => e.group_id).length,
	toets: (v, n) => n === 2
});
await proef('spiegelen horizontaal', [`${MOD}+Shift+h`], {
	lees: async () => (await (await fetch(`${BASE}/api/design`)).json()).elements.filter((e) => e.pose?.mirrored).length,
	toets: (v, n) => n > v
});
await proef('draaien met de punt', ['.'], {
	lees: async () => (await (await fetch(`${BASE}/api/design`)).json()).elements[0]?.pose?.angle_deg ?? 0,
	toets: (v, n) => Math.abs(n - 90) < 0.5
});

const zoom = {
	lees: (p) => p.evaluate(() => document.querySelector('.zoom .val')?.textContent?.trim() ?? '?'),
	toets: (v, n) => n !== v
};
await proef('100 % (toets 1)', ['1'], { ...zoom, toets: (v, n) => n.startsWith('100') });
await proef('alles passend (toets 3)', ['1', '3'], zoom);
// Eerst naar 100 %, dan terug naar het bed: dan moet de stand weer die van het
// begin zijn — dat is de enige toets die zegt dat "0" écht het bed pakt.
await proef('hele bed (toets 0)', ['1', '0'], { ...zoom, toets: (v, n) => n === v });
await proef('naar selectie (⌘⇧A)', [`${MOD}+Shift+a`], zoom);

console.table(uitslag);
const stuk = uitslag.filter((r) => !r.goed);
console.log(stuk.length ? `MIS: ${stuk.map((r) => r.naam).join(', ')}` : 'alle sneltoetsen doen wat ze zeggen');
await b.close();
