/**
 * Eindcontrole voor de tweede usability-ronde: Lagen en Job.
 *
 * Elke handeling die verhuisd is, machinaal nagelopen — is hij nog bereikbaar en
 * waar? Verplaatst mag, verdwenen is een blocker (FUNCTIONALITEIT.md).
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const post = (p) =>
	fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const fouten = [];
page.on('pageerror', (e) => fouten.push(String(e).slice(0, 120)));

async function open(pad) {
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1300);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
}

const uit = [];
async function toets(nr, wat, waar, hoe) {
	try {
		uit.push({ nr, actie: wat, waar, gevonden: (await hoe()) ? 'ja' : 'NEE' });
	} catch (e) {
		uit.push({ nr, actie: wat, waar, gevonden: 'FOUT: ' + String(e).slice(0, 50) });
	}
}

/** Het rijmenu van de eerste laag openen via de ⋯. */
async function rijmenu() {
	await open('/?tab=layers');
	await page.locator('.layer .more').first().click();
	await page.waitForTimeout(400);
}
async function lijstmenu() {
	await open('/?tab=layers');
	await page.locator('.lijstmeer').first().click();
	await page.waitForTimeout(400);
}
const inMenu = (naam) => page.getByRole('menu').getByText(naam, { exact: false }).count();

// ── Lagen: wat uit de rij verhuisde ──
for (const [nr, naam] of [
	['8.6', 'Eerder branden'],
	['8.7', 'Later branden'],
	['8.11', 'Zichtbaar op het canvas'],
	['8.10', 'Brandt mee'],
	['8.16', 'Selectie in deze laag zetten'],
	['8.22', 'Laag verwijderen']
])
	await toets(nr, naam, 'Lagen › rijmenu (⋯ of rechterklik)', async () => {
		await rijmenu();
		const n = await inMenu(naam);
		await page.keyboard.press('Escape');
		return n > 0;
	});

// ── Lagen: wat uit de balk verhuisde ──
for (const [nr, naam] of [
	['8.2', 'Op brandvolgorde zetten'],
	['8.3', 'Alle lagen weghalen'],
	['8.4', 'opruimen']
])
	await toets(nr, naam, 'Lagen › lijstmenu', async () => {
		await lijstmenu();
		const n = await inMenu(naam);
		await page.keyboard.press('Escape');
		return n > 0;
	});

await toets('8.4b', 'Lege lagen opruimen (inline)', 'Lagen › regel onder de balk', async () => {
	await open('/?tab=layers');
	return (await page.locator('.opruimregel .alsLink').count()) > 0;
});
await toets('8.5', 'Compacte/ruime lijst', 'Lagen › balk', async () => {
	await open('/?tab=layers');
	return (await page.locator('.dichtheid').count()) > 0;
});
await toets('8.8', 'Laag verslepen', 'Lagen › greep in de rij', async () => {
	await open('/?tab=layers');
	return (await page.locator('.layer .greep').count()) > 0;
});
await toets('8.9', 'Laag open-/dichtklappen', 'Lagen › kleurchip', async () => {
	await open('/?tab=layers');
	await page.locator('.layer .chip').first().click();
	await page.waitForTimeout(1200);
	return (
		(await page.locator('.layer.open').count()) > 0 &&
		(await page.locator('.layer.open .swatch, .layer.open input').count()) > 0
	);
});
for (const [nr, naam, sel] of [
	['8.12', 'Snelheid wijzigen', '.layer .vals .val input'],
	['8.25', 'Nieuwe laag: soort kiezen', null],
	['8.26', 'Nieuwe laag toevoegen', null]
])
	await toets(nr, naam, sel ? 'Lagen › rij' : 'Lagen › + Laag toevoegen', async () => {
		await open('/?tab=layers');
		if (sel) return (await page.locator(sel).count()) > 0;
		await page.locator('.panel .add').first().click();
		await page.waitForTimeout(400);
		const n = await page.getByRole('menu').getByText('Snijden', { exact: true }).count();
		await page.keyboard.press('Escape');
		return n > 0;
	});

// ── Job: stil ──
await post('/api/job/stop');
await post('/api/spooler/clear');
await new Promise((r) => setTimeout(r, 800));
for (const [nr, naam, hoe] of [
	['9.1', 'Job starten', async () => (await page.locator('.panel').getByRole('button', { name: /^Job starten/ }).count()) > 0],
	['9.2', 'Voorbeeld en maten', async () => (await page.locator('.panel .pf-time, .panel .preflight').count()) > 0],
	['9.5', 'Eerst kader tonen', async () => (await page.locator('.panel').getByRole('button', { name: /Kader tonen/ }).count()) > 0],
	['9.11', 'Jog', async () => (await page.locator('.panel .jog').count()) >= 4],
	['9.12', 'Home', async () => (await page.locator('.panel').getByRole('button', { name: /^Home$/ }).count()) > 0],
	['9.14', 'Stapgrootte', async () => (await page.locator('.panel').getByRole('radio', { name: /mm/ }).count()) >= 3],
	['9.15', 'Ontgrendelen', async () => (await page.locator('.panel').getByRole('button', { name: /Ontgrendelen/ }).count()) > 0],
	['9.16', 'Naar oorsprong', async () => (await page.locator('.panel').getByRole('button', { name: /Naar oorsprong/ }).count()) > 0],
	['9.19', 'Nulpunt zetten', async () => (await page.locator('.panel').getByRole('button', { name: /nulpunt/i }).count()) > 0],
	['9.24', 'Meldingen van de machine', async () => (await page.locator('.panel').getByRole('button', { name: /Meldingen van de machine/ }).count()) > 0]
])
	await toets(nr, naam, 'Job, stil', async () => {
		await open('/?tab=job');
		return hoe();
	});

// ── Job: onderweg ──
await post('/api/job/start');
await new Promise((r) => setTimeout(r, 2200));
for (const [nr, naam, hoe] of [
	['9.8', 'Pauzeren', async () => (await page.locator('.panel').getByRole('button', { name: /^Pauze$|^Hervatten$/ }).count()) > 0],
	['9.9', 'Wachtrij legen', async () => (await page.locator('.panel').getByRole('button', { name: /Wachtrij legen/ }).count()) > 0],
	['9.10', 'Stoppen', async () => (await page.locator('.panel').getByRole('button', { name: /^Stop/ }).count()) > 0],
	['9.23', 'Voortgang lezen', async () => (await page.locator('.panel .nu-balk').count()) > 0],
	['9.x', 'Machine bedienen (ingeklapt)', async () => (await page.locator('.panel .machinevouw').count()) > 0]
])
	await toets(nr, naam, 'Job, werk onderweg', async () => {
		await open('/?tab=job');
		return hoe();
	});
await toets('9.11b', 'Jog nog bereikbaar tijdens een job', 'Job › Machine bedienen uitklappen', async () => {
	await open('/?tab=job');
	await page.locator('.panel .machinevouw > summary').click();
	await page.waitForTimeout(400);
	return (await page.locator('.panel .jog').count()) >= 4;
});

// ── Statusbalk / bovenbalk ──
for (const [nr, naam, hoe] of [
	['1.10', 'Pauzeren in de bovenbalk', async () => (await page.locator('.topbar').getByRole('button', { name: /Pauze|Hervat/ }).count()) > 0],
	['1.12', 'Stoppen in de bovenbalk', async () => (await page.locator('.topbar').getByRole('button', { name: /^Stop$/ }).count()) > 0],
	['10.3', 'Voortgang in de statusbalk', async () => /%|nog/.test((await page.locator('.statusbar').first().textContent()) ?? '')],
	['10.5', 'Verbinden', async () => (await page.locator('.statusbar').getByRole('button', { name: /Verbinden|Verbreken/ }).count()) > 0]
])
	await toets(nr, naam, 'balken', async () => {
		await open('/?tab=design');
		return hoe();
	});

await post('/api/job/stop');
await post('/api/spooler/clear');
console.table(uit);
const mis = uit.filter((r) => r.gevonden !== 'ja');
console.log(mis.length ? `NIET GEVONDEN: ${mis.map((r) => r.actie).join(', ')}` : 'alles bereikbaar');
console.log('paginafouten:', fouten.slice(0, 5));
await b.close();
