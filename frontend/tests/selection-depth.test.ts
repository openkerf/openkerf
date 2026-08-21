/**
 * Picking up a shape that lies inside or behind another one.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/selection-depth.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`. Without a
 * reachable server it skips itself.
 *
 * Why it exists: the invisible hit area of every closed shape was
 * `fill="transparent"`, and a transparent fill still catches the pointer. So the
 * whole inside of a rectangle was clickable and everything drawn in it was
 * unreachable — measured: a circle inside a rectangle could not be selected at
 * all, however precisely you clicked its contour.
 *
 * Three ways out, and all three are tested here, because they cover different
 * moments: the contour itself (an outline is a line, not a surface), Alt+click to
 * walk down a pile, and the list in the right-click menu for whoever does not
 * know about Alt — the only way on a touch screen.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
/** The bed in screen pixels, and how many millimetres it is wide. */
let bed = { x: 0, y: 0, w: 0, h: 0, wideMm: 1, highMm: 1 };

const post = (path: string, body: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

/** A point on the bed, in millimetres, as screen coordinates. */
const at = (xMm: number, yMm: number) => ({
	x: bed.x + (bed.w * xMm) / bed.wideMm,
	y: bed.y + (bed.h * yMm) / bed.highMm
});

const selected = () =>
	page.evaluate(() =>
		[...document.querySelectorAll('[data-el]')]
			.filter((n) => n.getAttribute('aria-pressed') === 'true')
			.map((n) => n.getAttribute('data-el'))
	);

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Selection test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	// A big outline rectangle with a circle inside it, and a second rectangle whose
	// left edge crosses the first one's top edge: one shape inside another, and one
	// pile of two contours at a point.
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 40,
		y_mm: 40,
		width_mm: 60,
		height_mm: 60
	});
	await post('/api/design/elements', { type: 'circle', cx_mm: 70, cy_mm: 70, r_mm: 15 });
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 60,
		y_mm: 20,
		width_mm: 60,
		height_mm: 60
	});

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	// The bed in pixels, and how many millimetres that is: every point below is
	// given in millimetres, because that is what the shapes were placed in.
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

test('the inside of an outline is not a surface you can click', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const empty = at(45, 95); // inside the big rectangle, on nothing
	await page.mouse.click(empty.x, empty.y);
	await page.waitForTimeout(600);
	assert.deepEqual(await selected(), [], 'clicking on nothing selected something');
});

test('a shape inside another is picked up by its own contour', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const onCircle = at(70, 85); // the bottom of the circle, inside the rectangle
	await page.mouse.click(onCircle.x, onCircle.y);
	await page.waitForTimeout(700);
	const now = await selected();
	assert.equal(now.length, 1, `expected one shape, got ${JSON.stringify(now)}`);
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const chosen = design.elements.find((e: { id: string }) => e.id === now[0]);
	assert.match(chosen.type, /ellipse|circle/, `picked up ${chosen.type} instead of the circle`);
});

test('Alt+click walks down a pile of contours', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const crossing = at(60, 40); // the two rectangles' edges cross here
	await page.mouse.click(crossing.x, crossing.y);
	await page.waitForTimeout(600);
	const top = await selected();
	assert.equal(top.length, 1, 'the plain click should take the top one');

	const step = async () => {
		await page.keyboard.down('Alt');
		await page.mouse.click(crossing.x, crossing.y);
		await page.keyboard.up('Alt');
		await page.waitForTimeout(600);
		return (await selected())[0];
	};
	const second = await step();
	assert.notEqual(second, top[0], 'Alt+click stayed on the same shape');
	// And from the bottom it starts again at the top: a pile you can only walk down
	// once is a trap.
	assert.equal(await step(), top[0], 'Alt+click did not wrap round');

	// The action bar says where you are, or the second Alt+click on two shapes of
	// the same size looks like nothing happening.
	const bar = await page.evaluate(() => document.querySelector('.actionbar .state')?.textContent);
	assert.match(bar ?? '', /of 2/, `the bar says "${bar}"`);
});

test('the right-click menu lists what lies under the pointer', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const crossing = at(60, 40);
	await page.mouse.click(crossing.x, crossing.y, { button: 'right' });
	await page.waitForTimeout(700);
	const opener = page.getByRole('menuitem', { name: /Under the pointer/ }).first();
	assert.equal(await opener.count(), 1, 'no list of what is under the pointer');
	await opener.hover();
	await page.waitForTimeout(500);

	const rows = await page.evaluate(() =>
		[...document.querySelectorAll('[role=menu] [role=menuitem]')]
			.map((n) => (n.textContent ?? '').trim())
			.filter((text) => /^✓?\s*\d+\./.test(text))
	);
	assert.equal(rows.length, 2, `expected two shapes in the list, got ${JSON.stringify(rows)}`);
	// The measure is on the row: two rectangles of the same kind are otherwise the
	// same word twice.
	assert.match(rows[0], /mm$/, rows[0]);

	// Picking the second row selects exactly that shape.
	const before = (await selected())[0];
	await page.getByRole('menuitem', { name: /^2\./ }).first().click();
	await page.waitForTimeout(700);
	assert.notEqual((await selected())[0], before, 'the list did not change the selection');
});

test('a click on nothing at all clears the selection', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const outside = at(200, 200);
	await page.mouse.click(outside.x, outside.y);
	await page.waitForTimeout(600);
	assert.deepEqual(await selected(), []);
});
