/**
 * Importing replaces the sheet. Does it ask first?
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/import-asks-first.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`. Without a
 * reachable server the test skips itself — it belongs to a running engine, not
 * to a bundling step.
 *
 * Why it exists: the question hung off `design.dirty`. A freshly imported drawing
 * is at `dirty === false` (`/api/job/load` calls `document.clean()`) and has no
 * autosave at that moment either. Behaviour measured before the fix: import
 * trial.svg (5 shapes), then import logo.svg (1 shape), and there is 1 shape on
 * the bed — no question, no message, no way back.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

const FIVE_SHAPES = `<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm" viewBox="0 0 200 150">
  <rect x="10" y="10" width="80" height="40" fill="none" stroke="#ff0000" stroke-width="0.5"/>
  <rect x="10" y="60" width="30" height="30" fill="none" stroke="#ff0000" stroke-width="0.5"/>
  <circle cx="130" cy="30" r="20" fill="none" stroke="#0000ff" stroke-width="0.5"/>
  <polygon points="100,60 160,60 130,110" fill="none" stroke="#00aa00" stroke-width="0.5"/>
  <line x1="10" y1="120" x2="170" y2="120" stroke="#0000ff" stroke-width="0.5"/>
</svg>`;
const ONE_SHAPE = `<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" viewBox="0 0 50 50">
  <circle cx="25" cy="25" r="20" fill="none" stroke="#ff00ff" stroke-width="0.5"/>
</svg>`;

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let folder = '';

const design = async () => (await fetch(`${BASE}/api/design`)).json();

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	// Without a machine set up, `/` shows the welcome screen and there is no
	// import button; then you measure the setup instead of the import.
	const machines: { path: string; configured?: boolean }[] = await (
		await fetch(`${BASE}/api/machines`)
	).json();
	if (!machines.some((m) => m.configured)) {
		await fetch(`${BASE}/api/machines`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ info: 'ruida-beta', label: 'Import test bench' })
		});
	}
	folder = mkdtempSync(join(tmpdir(), 'openkerf-import-'));
	writeFileSync(join(folder, 'five.svg'), FIVE_SHAPES);
	writeFileSync(join(folder, 'one.svg'), ONE_SHAPE);
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
});

async function startClean() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
}

async function importFile(name: string) {
	await page.setInputFiles('input[aria-label="Import file into this sheet"]', join(folder, name));
	await page.waitForTimeout(3000);
}

const dialogues = () =>
	page.evaluate(() =>
		[...document.querySelectorAll('dialog, [role=dialog], [role=alertdialog]')]
			.filter((n) => n.getBoundingClientRect().width > 0)
			.map((n) => (n as HTMLElement).innerText.replace(/\n+/g, ' | '))
	);

test('a second import asks first, even when the first file was never edited', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await startClean();

	await importFile('five.svg');
	const first = await design();
	assert.equal(first.elements.length, 5, 'the first file should simply come in');
	assert.equal(first.dirty, false, 'a freshly loaded file is by definition not dirty');

	await importFile('one.svg');
	const asked = await dialogues();
	assert.equal(asked.length, 1, `there should be one question, seen: ${JSON.stringify(asked)}`);
	assert.match(asked[0], /replaces/i, `the question has to say something disappears: ${asked[0]}`);

	// And as long as it has not been answered, the work is still there.
	const between = await design();
	assert.equal(between.elements.length, 5, 'nothing replaced before the question is answered');
});

test('cancelling leaves the existing work alone', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await page.getByRole('button', { name: 'Cancel' }).click();
	await page.waitForTimeout(1200);
	assert.equal((await design()).elements.length, 5);
	assert.deepEqual(await dialogues(), []);
});

test('going ahead does replace, because that is what opening does', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await importFile('one.svg');
	// The button is called "Do not save" — the cancel / do-not-save /
	// save-and-open triptych every operating system uses for this question. This
	// test was still waiting for an older name and so sat in a thirty-second
	// timeout.
	await page.getByRole('button', { name: 'Do not save' }).click();
	await page.waitForTimeout(3000);
	const after_ = await design();
	assert.equal(after_.elements.length, 1);
	assert.equal(after_.elements[0].stroke, '#ff00ff');
});

test('on an empty bed no question gets in the way', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await startClean();
	await importFile('five.svg');
	assert.deepEqual(await dialogues(), [], 'an empty bed has nothing to lose');
	assert.equal((await design()).elements.length, 5);
});
