/**
 * Importeren vervangt het vel. Vraagt het dat eerst?
 *
 * Draaien tegen een lopende server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/import-vraagt-eerst.test.ts
 *
 * Deze test deelt één draaiende engine met de andere e2e-tests, dus meer dan
 * één bestand tegelijk draaien gaat mis: gebruik `--test-concurrency=1`.
 * Zonder bereikbare server slaat de test zichzelf over — hij hoort bij een
 * draaiende engine, niet bij een bundelstap.
 *
 * Aanleiding: de vraag hing aan `design.dirty`. Een net geïmporteerde tekening
 * staat op `dirty === false` (`/api/job/load` roept `document.clean()` aan) en
 * heeft op dat moment ook geen autosave. Gemeten gedrag vóór de fix: importeer
 * proef.svg (5 vormen), importeer daarna logo.svg (1 vorm), en er staat 1 vorm
 * op het bed — geen vraag, geen melding, geen weg terug.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

const VIJF_VORMEN = `<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm" viewBox="0 0 200 150">
  <rect x="10" y="10" width="80" height="40" fill="none" stroke="#ff0000" stroke-width="0.5"/>
  <rect x="10" y="60" width="30" height="30" fill="none" stroke="#ff0000" stroke-width="0.5"/>
  <circle cx="130" cy="30" r="20" fill="none" stroke="#0000ff" stroke-width="0.5"/>
  <polygon points="100,60 160,60 130,110" fill="none" stroke="#00aa00" stroke-width="0.5"/>
  <line x1="10" y1="120" x2="170" y2="120" stroke="#0000ff" stroke-width="0.5"/>
</svg>`;
const EEN_VORM = `<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" viewBox="0 0 50 50">
  <circle cx="25" cy="25" r="20" fill="none" stroke="#ff00ff" stroke-width="0.5"/>
</svg>`;

let bereikbaar = false;
let browser: Browser | null = null;
let page: Page;
let map = '';

const design = async () => (await fetch(`${BASE}/api/design`)).json();

before(async () => {
	bereikbaar = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!bereikbaar) return;
	// Zonder ingestelde machine toont `/` het welkomstscherm en is er geen
	// importknop; dan meet je de setup in plaats van het importeren.
	const machines: { path: string; configured?: boolean }[] = await (
		await fetch(`${BASE}/api/machines`)
	).json();
	if (!machines.some((m) => m.configured)) {
		await fetch(`${BASE}/api/machines`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ info: 'ruida-beta', label: 'Testbank import' })
		});
	}
	map = mkdtempSync(join(tmpdir(), 'openkerf-import-'));
	writeFileSync(join(map, 'vijf.svg'), VIJF_VORMEN);
	writeFileSync(join(map, 'een.svg'), EEN_VORM);
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
});

async function schoonBeginnen() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
}

async function importeer(bestand: string) {
	await page.setInputFiles('input[aria-label="Bestand importeren in dit vel"]', join(map, bestand));
	await page.waitForTimeout(3000);
}

const dialogen = () =>
	page.evaluate(() =>
		[...document.querySelectorAll('dialog, [role=dialog], [role=alertdialog]')]
			.filter((n) => n.getBoundingClientRect().width > 0)
			.map((n) => (n as HTMLElement).innerText.replace(/\n+/g, ' | '))
	);

test('een tweede import vraagt eerst, ook als het eerste bestand niet bewerkt is', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await schoonBeginnen();

	await importeer('vijf.svg');
	const eerste = await design();
	assert.equal(eerste.elements.length, 5, 'het eerste bestand hoort gewoon binnen te komen');
	assert.equal(eerste.dirty, false, 'een net geladen bestand is per definitie niet vuil');

	await importeer('een.svg');
	const gevraagd = await dialogen();
	assert.equal(gevraagd.length, 1, `er hoort één vraag te staan, gezien: ${JSON.stringify(gevraagd)}`);
	assert.match(gevraagd[0], /vervangt/i, `de vraag moet zeggen dat er iets verdwijnt: ${gevraagd[0]}`);

	// En zolang er niet geantwoord is, staat het werk er nog.
	const tussenin = await design();
	assert.equal(tussenin.elements.length, 5, 'niets vervangen voordat de vraag beantwoord is');
});

test('annuleren laat het bestaande werk staan', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await page.getByRole('button', { name: 'Annuleren' }).click();
	await page.waitForTimeout(1200);
	assert.equal((await design()).elements.length, 5);
	assert.deepEqual(await dialogen(), []);
});

test('doorzetten vervangt wél, want dat is wat openen doet', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await importeer('een.svg');
	// De knop heet "Niet opslaan" — het drieluik annuleren / niet opslaan /
	// opslaan-en-openen dat elk besturingssysteem bij deze vraag gebruikt. Deze
	// test wachtte nog op "Zonder opslaan openen", de naam van vóór die wijziging,
	// en liep dus dertig seconden in een timeout.
	await page.getByRole('button', { name: 'Niet opslaan' }).click();
	await page.waitForTimeout(3000);
	const na = await design();
	assert.equal(na.elements.length, 1);
	assert.equal(na.elements[0].stroke, '#ff00ff');
});

test('op een leeg bed komt er geen vraag tussen', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await schoonBeginnen();
	await importeer('vijf.svg');
	assert.deepEqual(await dialogen(), [], 'een leeg bed heeft niets te verliezen');
	assert.equal((await design()).elements.length, 5);
});
