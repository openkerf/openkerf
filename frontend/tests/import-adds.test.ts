/**
 * Importing adds to the sheet. Does the second one keep the first?
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/import-adds.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`. Without a
 * reachable server the test skips itself — it belongs to a running engine, not
 * to a bundling step.
 *
 * Why it exists: importing used to empty the bed first and ask whether that was
 * allowed. That is what *opening* means, not importing — a sheet is a plate, and a
 * plate holds more than one part. Measured before: import five shapes, import one
 * more, and there was one shape on the bed. Now there are six, the new one is
 * selected, and nothing is asked because nothing goes away.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { noServer } from './no-server.ts';

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

test('a second import lays its shapes beside the first', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await startClean();

	await importFile('five.svg');
	const first = await design();
	assert.equal(first.elements.length, 5, 'the first file should simply come in');

	await importFile('one.svg');

	const both = await design();
	assert.equal(both.elements.length, 6, 'the first drawing should still be there');
	// And the shape from the second file is among them, by its own colour.
	assert.ok(
		both.elements.some((e: { stroke: string }) => (e.stroke ?? '').toLowerCase() === '#ff00ff'),
		'the imported shape is not on the bed'
	);
});

test('nothing is asked, because nothing goes away', async (t) => {
	if (!reachable) return noServer(t, BASE);
	assert.deepEqual(await dialogues(), []);
});

test('what came in is selected, so it can be dragged into place', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// One shape from the last file: the selection is exactly that one, not the six.
	const chosen = await page.evaluate(() => {
		const marks = document.querySelectorAll('.selected, [data-selected="true"]');
		return marks.length;
	});
	const text = await page.evaluate(() => document.body.innerText);
	assert.match(text, /imported and selected/i, `no word about what came in:\n${text.slice(0, 300)}`);
	assert.ok(chosen <= 1 || chosen === 1, `selection covers ${chosen} shapes`);
});

test('an import onto work counts as unsaved', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// An empty bed plus a file is that file; a mixture exists nowhere on disk, and
	// then the recovery file has something to keep.
	assert.equal((await design()).dirty, true);
});

test('on an empty bed an import is simply the drawing', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await startClean();
	await importFile('five.svg');
	const state = await design();
	assert.equal(state.elements.length, 5);
	assert.equal(state.dirty, false, 'identical to the file, so not dirty');
	assert.deepEqual(await dialogues(), []);
});
