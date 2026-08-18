/**
 * Captures voor de drie handelingen die een geïmporteerde tekening bruikbaar
 * maken: splitsen, naar één laag, lege lagen opruimen.
 *
 * De proef loopt op het échte bestand van Jelle — één OpenSCAD-export met 46
 * panelen in één pad. De metingen naast de screenshots zijn het bewijs: wat er
 * op de knop staat (46), hoeveel elementen de snapshot daarna heeft, en hoeveel
 * lagen er overblijven. Een screenshot bewijst niet wat er stond; hij bewijst
 * dat het er stond.
 *
 * De stapel lege lagen is hier nagemaakt met de API. Bij Jelle komt hij uit de
 * vorige sessie: de engine bewaart de lagenlijst in een gedeelde
 * `operations.cfg` en zet die bij het opstarten terug.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8141';
const BESTAND = '/Users/Jelle.Tigchelaar/Downloads/k2_wled_lightbar_16.svg';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/import';
const BREEDTES = [1440, 1024, 390];
const THEMAS = ['light', 'dark'];
mkdirSync(UIT, { recursive: true });

async function api(pad, body, method = 'POST') {
	const r = await fetch(BASE + pad, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return { status: r.status, body: await r.json().catch(() => null) };
}

async function ontwerp() {
	const d = (await api('/api/design', undefined, 'GET')).body;
	return {
		elementen: d.elements.length,
		stukken: d.elements.map((e) => e.subpaths),
		lagen: d.operations.map((o) => `${o.type}:${o.element_ids.length}`)
	};
}

/** Het bestand opnieuw inladen en de stapel lege lagen erbij zetten. */
async function opzet() {
	await api('/api/design/clear');
	const form = new FormData();
	const bytes = await (await import('node:fs/promises')).readFile(BESTAND);
	form.append('file', new Blob([bytes], { type: 'image/svg+xml' }), 'k2.svg');
	const r = await fetch(BASE + '/api/job/load', { method: 'POST', body: form });
	console.log('laden:', r.status);
	for (let i = 0; i < 9; i++) await api('/api/design/operations', { type: 'cut' });
	console.log('opzet:', JSON.stringify(await ontwerp()));
}

const b = await chromium.launch();
const metingen = [];

async function pagina(width, theme, pad) {
	const ctx = await b.newContext({
		viewport: { width, height: width === 390 ? 844 : 900 },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark') {
		await page.addInitScript(() => {
			const zet = () => document.documentElement?.setAttribute('data-theme', 'dark');
			zet();
			document.addEventListener('DOMContentLoaded', zet);
		});
	}
	const fouten = [];
	page.on('pageerror', (e) => fouten.push(String(e).slice(0, 140)));
	page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 140)));
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	page.fouten = fouten;
	return { ctx, page };
}

/** Eén staat over de hele matrix fotograferen, met wat er te lezen valt. */
async function staat(naam, tab, selectie, lezer) {
	for (const width of BREEDTES) {
		for (const theme of THEMAS) {
			const pad = `/?tab=${tab}` + (selectie ? `&select=${selectie}` : '');
			const { ctx, page } = await pagina(width, theme, pad);
			metingen.push({
				staat: naam,
				width,
				theme,
				...(await lezer(page)),
				fouten: page.fouten.length
			});
			await page.screenshot({ path: `${UIT}/${naam}-${width}-${theme}.png` });
			await ctx.close();
		}
	}
}

async function tekst(page, selector) {
	const el = page.locator(selector).first();
	if (!(await el.count())) return '(niet aanwezig)';
	return (await el.innerText()).replace(/\s+/g, ' ').slice(0, 130);
}

// ------------------------------------------------------- 1. net geladen

await opzet();
let d = await ontwerp();
const pad = (await api('/api/design', undefined, 'GET')).body.elements[0].id;
console.log('\n1. net geladen:', JSON.stringify(d));

await staat('geladen', 'design', pad, async (page) => ({
	tip: await tekst(page, '.indelen .tip'),
	knop: await tekst(page, '.indelen button.primair')
}));

// ------------------------------------------------------- 2. na splitsen

// Door de UI, niet via de API: de knop is wat hier getoetst wordt.
{
	const { ctx, page } = await pagina(1440, 'light', `/?tab=design&select=${pad}`);
	const knop = page.locator('.indelen button.primair').first();
	console.log('\nknop zegt:', await knop.innerText());
	await knop.click();
	await page.waitForTimeout(2500);
	console.log('melding na splitsen:', await tekst(page, '.indelen .tip'));
	await ctx.close();
}
d = await ontwerp();
console.log('2. na splitsen:', JSON.stringify({ ...d, stukken: `${d.stukken.length}× ${d.stukken[0]}` }));

// Eén stuk aanklikken is genoeg: de stukken zitten na het splitsen in één
// groep, en het paneel selecteert de hele groep. Alle 46 ids in de URL zetten
// doet juist het omgekeerde — de eerste selecteert de groep, de 45 daarna
// zetten hem stuk voor stuk weer uit.
const stukken = (await api('/api/design', undefined, 'GET')).body.elements[0].id;
await staat('gesplitst', 'design', stukken, async (page) => ({
	knoppen: await tekst(page, '.alleen-in'),
	melding: await tekst(page, '.indelen .tip')
}));

// --------------------------------------------------- 3. naar de snijlaag

{
	const { ctx, page } = await pagina(1440, 'light', `/?tab=design&select=${stukken}`);
	const knop = page.locator('.alleen-in button', { hasText: 'snijlaag' }).first();
	await knop.click();
	await page.waitForTimeout(2500);
	console.log('\n3. melding na toewijzen:', await tekst(page, '.indelen .tip'));
	await ctx.close();
}
d = await ontwerp();
console.log('3. na toewijzen:', JSON.stringify({ elementen: d.elementen, lagen: d.lagen }));

await staat('snijlaag', 'design', stukken, async (page) => ({
	melding: await tekst(page, '.indelen .tip')
}));

// ------------------------------------------------------- 4. lagen opruimen

await staat('lagen-vol', 'layers', '', async (page) => ({
	opruimknop: await tekst(page, '.lijst-balk button:nth-of-type(3)'),
	regels: await page.locator('.lijst .laag, .laag').count()
}));

{
	const { ctx, page } = await pagina(1440, 'light', '/?tab=layers');
	const knop = page.locator('.lijst-balk button', { hasText: /opruimen/ }).first();
	console.log('\n4. opruimknop zegt:', await knop.innerText());
	await knop.click();
	await page.waitForTimeout(2500);
	await ctx.close();
}
d = await ontwerp();
console.log('4. na opruimen:', JSON.stringify({ elementen: d.elementen, lagen: d.lagen }));

await staat('lagen-op', 'layers', '', async (page) => ({
	balk: await tekst(page, '.lijst-balk')
}));

await b.close();
console.log('\n--- metingen ---');
for (const m of metingen) console.log(JSON.stringify(m));
