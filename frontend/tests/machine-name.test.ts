/**
 * Two machines with the same name.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/machine-name.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`.
 *
 * Why it exists: walking through the wizard twice gave two machines both called
 * "Workshop 5030" (`/api/machines` gave `ruida` and `ruida1`, the same label),
 * without a word about it. The top bar holds only that name, and the top bar is
 * the only thing that says where your job is about to go. Sheets already know
 * this rule (`sheets.py`, `add`); machines did not.
 *
 * The test cleans up its own machines, so that it can be run again.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';
const NAME = 'Name trial bench';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const machines = async (): Promise<{ path: string; label: string }[]> =>
	(await fetch(`${BASE}/api/machines`)).json();

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
	if (!reachable) return;
	// First away from the trial machine: the active machine cannot be deleted
	// (409), and the one created last is now the active one.
	const all = await machines();
	const other = all.find((m) => !m.label.startsWith(NAME));
	if (other) {
		await fetch(`${BASE}/api/machines/${encodeURIComponent(other.path)}/activate`, {
			method: 'POST'
		});
	}
	for (const m of all) {
		if (m.label.startsWith(NAME)) {
			await fetch(`${BASE}/api/machines/${encodeURIComponent(m.path)}`, { method: 'DELETE' });
		}
	}
});

async function name(label: string) {
	await page.goto(`${BASE}/setup/name?type=ruida-beta`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1800);
	await page.fill('input[type=text]', label);
	await page.waitForTimeout(500);
}

test('the first machine with this name goes through without complaint', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await name(NAME);
	assert.equal(await page.getByRole('alert').count(), 0);
	await page.getByRole('button', { name: 'Create the machine' }).click();
	await page.waitForTimeout(2500);
	assert.ok((await machines()).some((m) => m.label === NAME));
});

test('the second with the same name is reported, with a way out', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await name(NAME);

	const notice = page.getByRole('alert');
	assert.equal(await notice.count(), 1, 'a duplicate machine name should be reported');
	const text = await notice.innerText();
	assert.match(text, new RegExp(NAME), `the notice does not name the machine: ${text}`);
	assert.match(text, /top bar/, `the notice does not say *why* it matters: ${text}`);

	// And it offers a name that does tell them apart.
	await page.getByRole('button', { name: /Make it/ }).click();
	await page.waitForTimeout(400);
	assert.equal(await page.inputValue('input[type=text]'), `${NAME} (2)`);
	assert.equal(await page.getByRole('alert').count(), 0, 'the notice should be gone');
});

test('the suggested name is free of clashes straight away', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await page.getByRole('button', { name: 'Create the machine' }).click();
	await page.waitForTimeout(2500);
	const labels = (await machines()).map((m) => m.label).filter((l) => l.startsWith(NAME));
	assert.deepEqual([...labels].sort(), [NAME, `${NAME} (2)`]);

	// And the default name on a fresh screen no longer clashes either.
	await page.goto(`${BASE}/setup/name?type=ruida-beta`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1800);
	assert.equal(await page.getByRole('alert').count(), 0);
});
