/**
 * Save as, find it, open it, and a Cancel that changes nothing — against a live server.
 *
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/projects-flow.test.ts
 *
 * Skips without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a failure).
 * The server must have been started with `-r <its own folder>`; this test writes
 * projects. Nothing here touches a machine.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
let reachable = false;
let browser: Browser | null = null;
let page: Page;
const NAME = `Flow ${Date.now() % 100000}`;

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) }).then((r) => r.ok).catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 30, height_mm: 30 })
	});
});
after(async () => {
	await browser?.close();
});

async function openProjectMenu() {
	await page.locator('button.project-button').click();
	await page.waitForSelector('[role="menu"]', { timeout: 5000 });
}

test('Save as… puts the work in the list under its name, and the top bar says so', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Save as…' }).click();
	const field = page.locator('[role="dialog"] input.project-name');
	await field.waitFor({ timeout: 5000 });
	await field.fill(NAME);
	await page.locator('[role="dialog"] button.save').click();
	await page.waitForTimeout(1500);
	const listed = (await (await fetch(`${BASE}/api/projects`)).json()) as { name: string; current: boolean }[];
	const mine = listed.find((e) => e.name === NAME);
	assert.ok(mine, `${NAME} is not in the list`);
	assert.equal(mine.current, true);
	assert.match(await page.locator('button.project-button').innerText(), new RegExp(NAME));
});

test('Open… lists it, and Cancel in the question leaves the work alone', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 60, y_mm: 20, width_mm: 10, height_mm: 10 })
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	const beforeCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Open…' }).click();
	await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
	await page.locator(`[role="dialog"] .row:has-text("${NAME}") button.open`).click();
	// The work is dirty (a rect was added after the save), so the question comes.
	await page.getByRole('button', { name: 'Cancel' }).click();
	await page.waitForTimeout(800);
	const afterCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
	assert.equal(afterCount, beforeCount, 'Cancel changed the design');
});
