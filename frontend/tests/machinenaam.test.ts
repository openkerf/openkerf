/**
 * Twee machines die hetzelfde heten.
 *
 * Draaien tegen een lopende server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/machinenaam.test.ts
 *
 * Aanleiding: de wizard twee keer doorlopen leverde twee machines op die allebei
 * "Werkplaats 5030" heetten (`/api/machines` gaf `ruida` en `ruida1`, zelfde
 * label), zonder één woord erover. In de bovenbalk staat alleen die naam, en de
 * bovenbalk is het enige wat zegt waar je job straks naartoe gaat. Vellen kennen
 * deze regel al (`sheets.py`, `add`); machines niet.
 *
 * De test ruimt zijn eigen machines op, zodat hij herhaalbaar is.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';
const NAAM = 'Testbank naamproef';

let bereikbaar = false;
let browser: Browser | null = null;
let page: Page;

const machines = async (): Promise<{ path: string; label: string }[]> =>
	(await fetch(`${BASE}/api/machines`)).json();

before(async () => {
	bereikbaar = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!bereikbaar) return;
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
	if (!bereikbaar) return;
	// Eerst weg van de proefmachine: de actieve machine laat zich niet
	// verwijderen (409), en de laatste aangemaakte is nu de actieve.
	const alles = await machines();
	const anders = alles.find((m) => !m.label.startsWith(NAAM));
	if (anders) {
		await fetch(`${BASE}/api/machines/${encodeURIComponent(anders.path)}/activate`, {
			method: 'POST'
		});
	}
	for (const m of alles) {
		if (m.label.startsWith(NAAM)) {
			await fetch(`${BASE}/api/machines/${encodeURIComponent(m.path)}`, { method: 'DELETE' });
		}
	}
});

async function noem(naam: string) {
	await page.goto(`${BASE}/setup/naam?type=ruida-beta`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1800);
	await page.fill('input[type=text]', naam);
	await page.waitForTimeout(500);
}

test('de eerste machine met deze naam gaat zonder morren door', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await noem(NAAM);
	assert.equal(await page.getByRole('alert').count(), 0);
	await page.getByRole('button', { name: 'Aanmaken' }).click();
	await page.waitForTimeout(2500);
	assert.ok((await machines()).some((m) => m.label === NAAM));
});

test('de tweede met dezelfde naam wordt gemeld, met een uitweg', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await noem(NAAM);

	const melding = page.getByRole('alert');
	assert.equal(await melding.count(), 1, 'een dubbele machinenaam hoort gemeld te worden');
	const tekst = await melding.innerText();
	assert.match(tekst, new RegExp(NAAM), `de melding noemt de naam niet: ${tekst}`);
	assert.match(tekst, /bovenbalk/, `de melding zegt niet waaróm het erg is: ${tekst}`);

	// En hij biedt een naam aan die wél onderscheidt.
	await page.getByRole('button', { name: /Maak er/ }).click();
	await page.waitForTimeout(400);
	assert.equal(await page.inputValue('input[type=text]'), `${NAAM} (2)`);
	assert.equal(await page.getByRole('alert').count(), 0, 'de melding hoort weg te zijn');
});

test('de voorgestelde naam is meteen vrij van botsingen', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await page.getByRole('button', { name: 'Aanmaken' }).click();
	await page.waitForTimeout(2500);
	const labels = (await machines()).map((m) => m.label).filter((l) => l.startsWith(NAAM));
	assert.deepEqual([...labels].sort(), [NAAM, `${NAAM} (2)`]);

	// En de standaardnaam op een vers scherm botst ook niet meer.
	await page.goto(`${BASE}/setup/naam?type=ruida-beta`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1800);
	assert.equal(await page.getByRole('alert').count(), 0);
});
