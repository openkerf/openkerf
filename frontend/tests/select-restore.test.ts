/**
 * What a reload does to the selection in the URL.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8123 node --test frontend/tests/select-restore.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`. Without a
 * reachable server it skips itself.
 *
 * Why it exists: selecting a group writes both members into `?select=`, and the
 * restore in `+page.svelte` replayed them as `select(first)` followed by
 * `toggle(second)`. `select` expands a member to the whole group, so the toggle
 * found every member already inside and took them all away again. Measured on a
 * group of two: 2 shapes selected before the reload, 0 after, and the parameter
 * dropped from the URL. A single shape and an ungrouped pair survived the same
 * reload, which is what made it look like a group problem rather than a restore
 * problem.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let bed = { x: 0, y: 0, w: 0, h: 0, wideMm: 1, highMm: 1 };
/** The four rectangles in the order they were placed: A and B grouped, C and D loose. */
let ids: string[] = [];

const post = (path: string, body: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

const at = (xMm: number, yMm: number) => ({
	x: bed.x + (bed.w * xMm) / bed.wideMm,
	y: bed.y + (bed.h * yMm) / bed.highMm
});

const selected = () =>
	page.evaluate(() =>
		[...document.querySelectorAll('[data-el]')]
			.filter((n) => n.getAttribute('aria-pressed') === 'true')
			.map((n) => n.getAttribute('data-el') ?? '')
	);

/** Wait for the selection to settle rather than guessing how long a reload takes. */
async function selectionAfterReload(): Promise<string[]> {
	await page.reload({ waitUntil: 'domcontentloaded' });
	let now: string[] = [];
	for (let step = 0; step < 40; step++) {
		await page.waitForTimeout(250);
		now = await selected();
		if (now.length > 0) return now;
	}
	return now;
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Restore test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	// Four rectangles side by side, so every click lands on one contour only.
	for (const x of [20, 50, 80, 110]) {
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: x,
			y_mm: 30,
			width_mm: 20,
			height_mm: 20
		});
	}
	const design = await (await fetch(`${BASE}/api/design`)).json();
	ids = design.elements.map((e: { id: string }) => e.id);
	await post('/api/design/group', { ids: [ids[0], ids[1]] });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	const box = await page.$eval('.bed > svg', (node) => {
		const rect = node.getBoundingClientRect();
		return { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
	});
	const devices: { active: boolean; bed: { width_mm: number; height_mm: number } }[] = await (
		await fetch(`${BASE}/api/devices`)
	).json();
	const size = devices.find((d) => d.active)!.bed;
	bed = { ...box, wideMm: size.width_mm, highMm: size.height_mm };
});

after(async () => {
	await browser?.close();
});

test('a selected group is still selected after a reload', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const onGroup = at(30, 30); // the top edge of the first rectangle
	await page.mouse.click(onGroup.x, onGroup.y);
	await page.waitForTimeout(700);
	const before = await selected();
	assert.equal(before.length, 2, `clicking a group member selected ${before.length}, expected 2`);
	assert.match(page.url(), /select=/, 'the group selection did not reach the URL');

	const after = await selectionAfterReload();
	assert.deepEqual(
		[...after].sort(),
		[...before].sort(),
		`after the reload ${after.length} of the group's 2 shapes were selected`
	);
	assert.match(page.url(), /select=/, 'the reload dropped the select parameter');
});

test('a single shape is still selected after a reload', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.mouse.click(at(90, 30).x, at(90, 30).y);
	await page.waitForTimeout(700);
	const before = await selected();
	assert.equal(before.length, 1, `expected one shape, got ${JSON.stringify(before)}`);

	assert.deepEqual(await selectionAfterReload(), before);
});

test('an ungrouped pair is still selected after a reload', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.mouse.click(at(90, 30).x, at(90, 30).y);
	await page.waitForTimeout(500);
	await page.keyboard.down('Shift');
	await page.mouse.click(at(120, 30).x, at(120, 30).y);
	await page.keyboard.up('Shift');
	await page.waitForTimeout(700);
	const before = await selected();
	assert.equal(before.length, 2, `expected two shapes, got ${JSON.stringify(before)}`);

	const after = await selectionAfterReload();
	assert.deepEqual([...after].sort(), [...before].sort());
});
