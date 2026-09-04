/**
 * Print and cut: laying the job over marks that are already on the material.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/printcut.test.ts
 *
 * One engine is shared with the other e2e tests, so use `--test-concurrency=1`.
 * Without a reachable server the file skips itself.
 *
 * Why it exists: the two halves of this feature live on different sides of the
 * wire. The maths is tested in api/tests/test_printcut.py; what cannot be tested
 * there is that the panel offers the steps in an order you can actually walk —
 * that the button is dead until two shapes are picked, that it asks for the second
 * point after the first, and that the alignment reads back as a number you can
 * check with a ruler. A panel that shows an alignment nobody can verify is worse
 * than no alignment.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let marks: string[] = [];

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});

/** The print-and-cut block as one line of text. */
const block = async () => {
	const text = await page.evaluate(() => document.body.innerText);
	const from = text.indexOf('PRINT AND CUT');
	return from < 0 ? '' : text.slice(from, from + 500).replace(/\s+/g, ' ');
};

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Print and cut bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	await post('/api/printcut/clear');
	// Two registration marks far apart, plus some work between them.
	const first = await (
		await post('/api/design/elements', { type: 'circle', cx_mm: 30, cy_mm: 30, r_mm: 2 })
	).json();
	const second = await (
		await post('/api/design/elements', { type: 'circle', cx_mm: 230, cy_mm: 40, r_mm: 2 })
	).json();
	marks = [first.ids[0], second.ids[0]];
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 60,
		y_mm: 60,
		width_mm: 100,
		height_mm: 60
	});

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
});

after(async () => {
	await browser?.close();
});

async function open(selected: string[] = []) {
	const query = selected.length ? `&select=${selected.map(encodeURIComponent).join(',')}` : '';
	await page.goto(`${BASE}/?tab=job${query}`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);
}

test('without two shapes picked, the button says why it cannot', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await open();

	const button = page.getByRole('button', { name: 'Use the two selected shapes' });
	assert.equal(await button.isEnabled(), false, 'the button was live with nothing picked');
	assert.match(
		(await button.getAttribute('title')) ?? '',
		/exactly two shapes/,
		'a dead button without a reason is a riddle'
	);
});

test('two marks picked, and it asks for the second point after the first', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await open(marks);

	await page.getByRole('button', { name: 'Use the two selected shapes' }).click();
	await page.waitForTimeout(1000);
	assert.match(await block(), /Drive the head over a mark/, 'it did not ask for a point');

	// The head cannot be driven from a test, so the point is given as coordinates —
	// the same route the buttons use, with the position filled in.
	await post('/api/printcut/measure', { index: 0, x_mm: 32, y_mm: 31 });
	await open(marks);
	assert.match(
		await block(),
		/One of the two marks has been measured/,
		'after one point it did not ask for the other'
	);
});

test('with both points it reads back an offset you can check', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await post('/api/printcut/measure', { index: 1, x_mm: 232.5, y_mm: 41.2 });
	await open(marks);

	const shown = await block();
	// The offset of the first mark: 32 − 30 and 31 − 30.
	assert.match(shown, /2,.?0?,?\s*1/, `the offset was not shown: ${shown}`);
	assert.match(shown, /sheet lies 0.05° out/, `the angle was not shown: ${shown}`);
	// And it says that the zero point stays out of it, because both would shift twice.
	assert.match(shown, /zero point stays out of it/i);
});

test('forgetting the alignment gives the ordinary job back', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await open(marks);

	await page.getByRole('button', { name: 'Forget the alignment' }).click();
	await page.waitForTimeout(1000);

	assert.match(await block(), /Off\. The work burns where you drew it/);
	assert.equal((await (await fetch(`${BASE}/api/printcut`)).json()).aligned, false);
});
