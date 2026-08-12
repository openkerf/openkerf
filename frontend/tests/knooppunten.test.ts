/**
 * Het knooppuntgereedschap heeft drie stille standen. Zegt het welke?
 *
 * Draaien tegen een lopende server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/knooppunten.test.ts
 *
 * Deze test deelt één draaiende engine met de andere e2e-tests, dus meer dan
 * één bestand tegelijk draaien gaat mis: gebruik `--test-concurrency=1`.
 *
 * Aanleiding: met niets of met meer dan één vorm gekozen tekent het gereedschap
 * geen punten. Het staat wel ingedrukt. Gemeten met twee vormen geselecteerd:
 * het rechterpaneel toont de gewone meervoudsselectie en het woord "knooppunt"
 * komt nergens in beeld voor — het gereedschap ziet er kapot uit terwijl het
 * gewoon wacht op één vorm.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let bereikbaar = false;
let browser: Browser | null = null;
let page: Page;
let bed: { x: number; y: number; w: number; h: number };

/** Een punt op het bed in millimeters omrekenen naar het scherm. */
const punt = (xmm: number, ymm: number, breed: number, hoog: number) => ({
	x: bed.x + (bed.w * xmm) / breed,
	y: bed.y + (bed.h * ymm) / hoog
});

before(async () => {
	bereikbaar = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!bereikbaar) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await fetch(`${BASE}/api/machines`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ info: 'ruida-beta', label: 'Testbank knooppunten' })
		});
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
});

after(async () => {
	await browser?.close();
});

const zichtbaar = () => page.evaluate(() => document.body.innerText);

test('zonder selectie zegt het gereedschap wat het nodig heeft', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	await page.waitForTimeout(2500);
	const doos = await page.$eval('.bed > svg', (n) => {
		const r = n.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height };
	});
	bed = doos;
	const maat = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;

	// Twee vormen om mee te werken.
	for (const [gereedschap, x, y] of [
		['Rechthoek', 80, 60],
		['Cirkel', 200, 60]
	] as const) {
		await page.getByRole('button', { name: gereedschap, exact: true }).click();
		await page.waitForTimeout(300);
		const p = punt(x, y, maat.width_mm, maat.height_mm);
		await page.mouse.click(p.x, p.y);
		await page.waitForTimeout(1000);
	}

	// Deselecteren en het knooppuntgereedschap pakken.
	await page.getByRole('button', { name: 'Selecteren', exact: true }).click();
	await page.waitForTimeout(250);
	const leeg = punt(maat.width_mm - 20, maat.height_mm - 20, maat.width_mm, maat.height_mm);
	await page.mouse.click(leeg.x, leeg.y);
	await page.waitForTimeout(600);
	await page.getByRole('button', { name: /Knooppunten/ }).click();
	await page.waitForTimeout(1000);

	const tekst = await zichtbaar();
	assert.match(tekst, /Knooppunten werkt op één vorm/, `geen uitleg in beeld:\n${tekst.slice(0, 400)}`);
});

test('met twee vormen gekozen zegt het hoeveel er te veel staan', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	const maat = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;
	await page.getByRole('button', { name: 'Selecteren', exact: true }).click();
	await page.waitForTimeout(250);
	const a = punt(80, 60, maat.width_mm, maat.height_mm);
	const b = punt(200, 60, maat.width_mm, maat.height_mm);
	await page.mouse.click(a.x, a.y);
	await page.waitForTimeout(600);
	await page.keyboard.down('Shift');
	await page.mouse.click(b.x, b.y);
	await page.keyboard.up('Shift');
	await page.waitForTimeout(800);
	await page.getByRole('button', { name: /Knooppunten/ }).click();
	await page.waitForTimeout(1000);

	const tekst = await zichtbaar();
	assert.match(tekst, /er staan er 2\s*gekozen/, `geen telling in beeld:\n${tekst.slice(0, 400)}`);
});

test('met precies één vorm zwijgt de uitleg en staan de punten er', async (t) => {
	if (!bereikbaar) return t.skip(`geen server op ${BASE}`);
	const maat = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;
	// Eerst helemaal los van de vorige selectie: shift-klikken stapelt.
	await page.getByRole('button', { name: 'Selecteren', exact: true }).click();
	await page.waitForTimeout(250);
	const leeg = punt(maat.width_mm - 20, maat.height_mm - 20, maat.width_mm, maat.height_mm);
	await page.mouse.click(leeg.x, leeg.y);
	await page.waitForTimeout(600);
	const a = punt(80, 60, maat.width_mm, maat.height_mm);
	await page.mouse.click(a.x, a.y);
	await page.waitForTimeout(900);
	await page.getByRole('button', { name: /Knooppunten/ }).click();
	await page.waitForTimeout(1800);

	assert.ok((await page.$$eval('.knot', (n) => n.length)) > 0, 'er horen punten te staan');
	const tekst = await zichtbaar();
	// Een uitleg die blijft staan terwijl het gereedschap gewoon werkt, is ruis.
	assert.doesNotMatch(tekst, /Knooppunten werkt op één vorm/);
	assert.doesNotMatch(tekst, /geen losse punten/);
});
