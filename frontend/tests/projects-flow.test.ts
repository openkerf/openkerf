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

test('after Save as…, the unsaved dot goes out and the server agrees the design is clean', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// Test 1 above just saved as `NAME` with a dirty design on the bed — the exact
	// state that used to leave the dot lit and `/api/design` saying `dirty: true`
	// because neither `saveProject()` nor this window's `onSaved` reloaded the
	// snapshot after a landed save.
	await page.waitForTimeout(300);
	const dot = page.locator('button.project-button .unsaved-dot');
	assert.equal(await dot.count(), 0, 'the unsaved dot is still lit after Save as…');
	const design = (await (await fetch(`${BASE}/api/design`)).json()) as { dirty: boolean };
	assert.equal(design.dirty, false, '/api/design still says dirty after Save as…');
});

test('mod+s from inside a text field still saves, and turns the dot off', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// Measured before the fix: the field bail-out in `sneltoets` returned before the
	// shortcut table was even looked at, so ⌘S from a focused field fell through to
	// the browser's own Save Page instead of running `saveProject()`. The Save-as
	// window's own name field is a plain text input, so it stands in for "any field"
	// here — the fix does not special-case which one.
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 70, y_mm: 20, width_mm: 8, height_mm: 8 })
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);
	assert.equal(await page.locator('button.project-button .unsaved-dot').count(), 1, 'the dot should be lit before ⌘S');
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Save as…' }).click();
	const field = page.locator('[role="dialog"] input.project-name');
	await field.waitFor({ timeout: 5000 });
	await field.click();
	await page.keyboard.press(process.platform === 'darwin' ? 'Meta+S' : 'Control+S');
	await page.waitForTimeout(1200);
	assert.equal(await page.locator('button.project-button .unsaved-dot').count(), 0, 'the dot is still lit after ⌘S from the field');
	const design = (await (await fetch(`${BASE}/api/design`)).json()) as { dirty: boolean };
	assert.equal(design.dirty, false, '/api/design still says dirty after ⌘S from the field');
	// `saveProject()` (what ⌘S runs) never touches this window — it is a leftover
	// from putting the caret in a field, not the reason the save landed — so it is
	// still open behind everything else and has to be closed by hand.
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
});

test('a refused Open says why, in the window, and leaves the bar alone', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// Deliberately not a substring of `NAME` — the row-lookup in the next test
	// matches on `:has-text`, which is a substring match, and this project is
	// deleted before that test runs anyway.
	const GONE = `Vanishes ${Date.now() % 100000}`;
	await fetch(`${BASE}/api/projects/${encodeURIComponent(GONE)}`, { method: 'POST' });
	const before = await page.locator('button.project-button').innerText();
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Open…' }).click();
	await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
	// Deleted from underneath the window, between the list loading and the click.
	await fetch(`${BASE}/api/projects/${encodeURIComponent(GONE)}`, { method: 'DELETE' });
	await page.locator(`[role="dialog"] .row:has-text("${GONE}") button.open`).click();
	const alert = page.locator('[role="dialog"] [role="alert"]');
	await alert.waitFor({ timeout: 5000 });
	// `api.project.missing` in the catalogue (`en.ts`) does not repeat the name —
	// the point of this assertion is that the sentence renders in the window at
	// all, where it used to vanish along with the window itself.
	assert.match(
		await alert.innerText(),
		/no project with that name/i,
		'the refusal did not render into the still-open window'
	);
	assert.ok(await page.locator('[role="dialog"]').isVisible(), 'the window closed on a refused Open');
	assert.equal(await page.locator('button.project-button').innerText(), before, 'the bar changed on a refused Open');
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
	// Creating and deleting `GONE` moved the server's own `current` off `NAME` and
	// then to none, underneath this still-open page — restore it so the tests after
	// this one find things exactly as `NAME`'s own tests left them.
	await fetch(`${BASE}/api/projects/${encodeURIComponent(NAME)}/open`, { method: 'POST' });
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

test('New still asks on untitled, imported work — importing into an empty bed does not mark it saved', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// A fresh, untitled project, then an import — the one case `design.dirty` alone
	// gets wrong: `/api/job/load` calls `document.clean()` when the bed was empty,
	// because the result equals the file on disk. It does not equal anything this
	// screen can get back to, since nothing offers that upload again.
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm"><rect width="10" height="10"/></svg>';
	const form = new FormData();
	form.append('file', new Blob([svg], { type: 'image/svg+xml' }), 'import.svg');
	const uploaded = await fetch(`${BASE}/api/job/load`, { method: 'POST', body: form });
	assert.ok(uploaded.ok, `import failed: ${uploaded.status}`);
	const before = (await (await fetch(`${BASE}/api/design`)).json()) as { dirty: boolean; elements: unknown[] };
	assert.equal(before.dirty, false, 'importing into an empty bed should leave the design clean');
	assert.ok(before.elements.length > 0, 'the import produced no elements');

	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'New project' }).click();
	await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
	await page.getByRole('button', { name: 'Cancel' }).click();
	await page.waitForTimeout(800);
	const after = (await (await fetch(`${BASE}/api/design`)).json()) as { elements: unknown[] };
	assert.equal(after.elements.length, before.elements.length, 'Cancel changed the design');
});

test('a dismissed Save-as leaves no stale continuation for a later, unrelated save', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// Untitled, dirty work: New asks the unsaved-changes question.
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 15, y_mm: 15, width_mm: 15, height_mm: 15 })
	});
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	const beforeCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;

	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'New project' }).click();
	await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
	// Save on an untitled project falls through to Save as…
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await page.waitForSelector('[role="dialog"] input.project-name', { timeout: 5000 });
	// Dismiss the Save-as window without saving — Escape, not Cancel: nothing in
	// this window itself was declined, the window was just closed.
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);

	// A later, unrelated Save as…, under a fresh name, must not fire the dismissed
	// question's old continuation (which would otherwise run "New" and wipe this).
	const LATER = `${NAME} later`;
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Save as…' }).click();
	await page.locator('[role="dialog"] input.project-name').fill(LATER);
	await page.locator('[role="dialog"] button.save').click();
	await page.waitForTimeout(1500);

	const afterCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
	assert.equal(afterCount, beforeCount, 'the dismissed Save-as continuation changed the design');
	const listed = (await (await fetch(`${BASE}/api/projects`)).json()) as { name: string; current: boolean }[];
	const mine = listed.find((e) => e.name === LATER);
	assert.ok(mine, `${LATER} is not in the list`);
	assert.equal(mine.current, true, `${LATER} is not the current project`);
});
