/**
 * Bridges (tabs) in a cut line, driven the way a person drives them.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/bridges.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`. Without a
 * reachable server it skips itself.
 *
 * Why it exists: the engine cuts the gaps by itself once two attributes are on the
 * shape, so nothing about this feature can be checked by the plan — the plan was
 * always right. What can go wrong is everything around it: the gaps were invisible
 * on the bed (the snapshot draws from `as_geometry()`, and that is the ideal path),
 * the engine refuses nothing worth the name, and the two fields have to be
 * independent — measured before that fix: with six bridges on a shape, typing a
 * length of 30 mm was refused with a sentence about four.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let bed = { x: 0, y: 0, w: 0, h: 0, wideMm: 1, highMm: 1 };
/** The rectangle and the circle, in the order they were placed. */
let shapes: string[] = [];

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

type Snapshot = {
	elements: {
		id: string;
		path: string;
		bridges: {
			count: number;
			length_mm: number;
			path_length_mm: number;
			path: string;
		} | null;
	}[];
};

const snapshot = async (): Promise<Snapshot> => (await fetch(`${BASE}/api/design`)).json();
const panel = () =>
	page.evaluate(() => document.querySelector('.bridges')?.textContent?.replace(/\s+/g, ' ').trim());

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Bridge test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	// A rectangle of 60 × 40 mm — a 200 mm perimeter, so a percentage is a round number of
	// millimetres — a circle beside it, and a line, which carries no bridges at all.
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 20,
		y_mm: 20,
		width_mm: 60,
		height_mm: 40
	});
	await post('/api/design/elements', { type: 'circle', cx_mm: 140, cy_mm: 40, r_mm: 20 });
	await post('/api/design/elements', { type: 'line', x1_mm: 20, y1_mm: 100, x2_mm: 120, y2_mm: 100 });
	shapes = (await snapshot()).elements.map((e) => e.id);
	// In a cut layer, because that is the only place bridges mean anything.
	await post('/api/design/single-layer', { ids: shapes.slice(0, 2), type: 'cut' });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	await clearAlarm();
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

/**
 * Get the machine's alarm card out of the way.
 *
 * A laser that is not answering puts "No connection to the machine" over the top left
 * of the canvas, and it outranks everything on purpose. Measured on this bench: the
 * card occupies 68,133 to 688,244, and the click on the rectangle at 20,20 mm lands at
 * 307,233 — inside it. Every click in this file then hit the card, ten of the eleven
 * tests failed, and none of them said why. It is dismissible in the app, so it is
 * dismissed here; without a card the click is a no-op.
 */
async function clearAlarm() {
	await page
		.locator('.alarm .seen')
		.first()
		.click({ timeout: 500 })
		.catch(() => {});
}

/** Click the top edge of the rectangle — an outline is a line, not a surface. */
async function pickRectangle() {
	await clearAlarm();
	const p = at(50, 20);
	await page.mouse.click(p.x, p.y);
	await page.waitForTimeout(800);
}

test('a shape without bridges says so, in the panel', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await pickRectangle();

	const text = await panel();
	assert.match(text ?? '', /No bridges/, `the panel says "${text}"`);
	assert.match(text ?? '', /comes loose/, 'it does not say what that means for the part');
});

test('the right-click menu puts sensible bridges on in one go', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await pickRectangle();
	const p = at(50, 20);
	await page.mouse.click(p.x, p.y, { button: 'right' });
	await page.waitForTimeout(600);

	const row = page.getByRole('menuitem', { name: /Add bridges/ }).first();
	assert.equal(await row.count(), 1, 'no bridges row in the menu');
	// The number is on the row: "bridges" without one does not say what you get.
	assert.match((await row.textContent()) ?? '', /4 × 2 mm/);
	await row.click();
	await page.waitForTimeout(1400);

	const rect = (await snapshot()).elements.find((e) => e.id === shapes[0])!;
	assert.equal(rect.bridges?.count, 4);
	assert.ok(Math.abs((rect.bridges?.length_mm ?? 0) - 2) < 0.01);
	assert.match((await panel()) ?? '', /4 gaps of 2 mm/);
});

test('the canvas draws the gaps, and keeps the whole contour for clicking', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const rect = (await snapshot()).elements.find((e) => e.id === shapes[0])!;

	// Four gaps in a closed contour leave five pieces; the ideal path is one.
	assert.equal(rect.bridges!.path.split('M').length - 1, 5);
	assert.equal(rect.path.split('M').length - 1, 1);

	// And that carved path really is what is stroked on the bed, as a path of its own —
	// the fill and the hit zone stay on the whole contour.
	const drawn = await page.evaluate(
		(d) => [...document.querySelectorAll('.bed svg path')].filter((n) => n.getAttribute('d') === d).length,
		rect.bridges!.path
	);
	assert.equal(drawn, 1, 'the gapped contour is not on the canvas');

	// The shape is still selectable on the piece of contour a gap took away: the hit zone
	// is the ideal path, so a 2 mm gap does not make a hole you fall through. The first
	// bridge of four sits 25 mm along a 200 mm perimeter, so at x = 45 on the top edge.
	await page.mouse.click(at(200, 200).x, at(200, 200).y);
	await page.waitForTimeout(500);
	const p = at(45, 20);
	await page.mouse.click(p.x, p.y);
	await page.waitForTimeout(700);
	const chosen = await page.evaluate(() =>
		[...document.querySelectorAll('[data-el]')]
			.filter((n) => n.getAttribute('aria-pressed') === 'true')
			.map((n) => n.getAttribute('data-el'))
	);
	assert.deepEqual(chosen, [shapes[0]], 'the shape could not be clicked in a gap');
});

test('the two numbers are independent: a length does not reset the count', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await pickRectangle();

	const count = page.locator('.bridges .stepper input').first();
	const length = page.locator('.bridges .stepper input').nth(1);
	await count.fill('6');
	await count.press('Enter');
	await page.waitForTimeout(1300);
	await length.fill('3');
	await length.press('Enter');
	await page.waitForTimeout(1300);

	const rect = (await snapshot()).elements.find((e) => e.id === shapes[0])!;
	assert.equal(rect.bridges?.count, 6, 'the count was levelled by the length');
	assert.ok(Math.abs((rect.bridges?.length_mm ?? 0) - 3) < 0.01);
});

test('a refusal appears beside the field that caused it', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await pickRectangle();

	// Six of 30 mm is 180 mm of a 200 mm contour: at most half of it may be bridge.
	const length = page.locator('.bridges .stepper input').nth(1);
	await length.fill('30');
	await length.press('Enter');
	await page.waitForTimeout(1300);

	const text = (await panel()) ?? '';
	assert.match(text, /at most half of it may be bridge/, `the panel says "${text}"`);
	// The number in it is the one on the shape, not a default the user never typed.
	assert.match(text, /6 bridges of 30 mm/);
	const rect = (await snapshot()).elements.find((e) => e.id === shapes[0])!;
	assert.equal(rect.bridges?.count, 6, 'the refused value landed anyway');
});

test('after a refusal the two fields show the shape again, not the refused numbers', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await post('/api/design/bridges', { ids: [shapes[0]], count: 12, length_mm: 2 });
	await page.waitForTimeout(1200);
	await pickRectangle();

	const fields = () => page.$$eval('.bridges .stepper input', (els) => els.map((e) => (e as HTMLInputElement).value));
	assert.deepEqual(await fields(), ['12', '2'], 'the fields do not start from the shape');

	// Above the maximum, so the write is refused and nothing on the shape changes.
	const count = page.locator('.bridges .stepper input').nth(0);
	await count.fill('999');
	await count.press('Enter');
	await page.waitForTimeout(1400);

	const text = (await panel()) ?? '';
	assert.match(text, /More than 200 bridges/, `the panel says "${text}"`);
	// Measured before this fix: the fields kept 999 and 9 while the sentence six pixels
	// below still read "12 gaps of 2 mm", so the panel read back a state that was nowhere.
	assert.deepEqual(await fields(), ['12', '2'], 'the refused number stayed in the field');
	assert.equal((await snapshot()).elements.find((e) => e.id === shapes[0])!.bridges?.count, 12);
});

test('the shortcut obeys the reason the menu row gives', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await clearAlarm();
	const p = at(70, 100); // the line, which carries no bridges
	await page.mouse.click(p.x, p.y);
	await page.waitForTimeout(800);

	const tried: string[] = [];
	const watch = (request: { url: () => string }) => {
		if (request.url().includes('/api/design/bridges')) tried.push(request.url());
	};
	page.on('request', watch);
	await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Shift+B' : 'Control+Shift+B');
	await page.waitForTimeout(1200);
	page.off('request', watch);

	// Measured before this: the same key posted anyway and came back 409 with a console
	// error, while the menu row beside it was greyed out and said why.
	assert.deepEqual(tried, [], 'the key posted a request the menu row already refuses');
});

test('a shape whose type carries no bridges says that, and the menu row says why', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await clearAlarm();
	const p = at(70, 100); // the line
	await page.mouse.click(p.x, p.y);
	await page.waitForTimeout(800);

	const text = (await panel()) ?? '';
	assert.match(text, /carries no bridges/, `the panel says "${text}"`);
	// And the note from the previous shape is gone: a refusal belongs to the shapes it
	// was about.
	assert.doesNotMatch(text, /at most half/);

	await page.mouse.click(p.x, p.y, { button: 'right' });
	await page.waitForTimeout(600);
	const row = page.getByRole('menuitem', { name: /bridge/i }).first();
	assert.equal(
		await row.getAttribute('title'),
		'A line, text or an image carries no bridges',
		'a grey row without a reason is a riddle'
	);
	await page.keyboard.press('Escape');
});

test('the switch and the two numbers are reachable and usable from the keyboard', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await pickRectangle();

	await page.focus('.bridges input[type=checkbox]');
	const walk: string[] = [];
	for (let i = 0; i < 2; i++) {
		await page.keyboard.press('Tab');
		walk.push(
			await page.evaluate(() => {
				// The name comes from the `<label for>` NumberField writes, not from an
				// aria-label — see the note there about a wrapping label grabbing the − button.
				const el = document.activeElement as HTMLInputElement | null;
				const label = el?.labels?.[0]?.textContent?.replace(/\s+/g, ' ').trim();
				return label ?? el?.getAttribute('aria-label') ?? el?.tagName ?? '?';
			})
		);
	}
	assert.deepEqual(walk, ['Number', 'Length per bridge (mm)']);

	// The steppers' own buttons are out of the tab order on purpose, so the arrows have to
	// do their work (see NumberField).
	await page.focus('.bridges .stepper input');
	const before = (await snapshot()).elements.find((e) => e.id === shapes[0])!.bridges!.count;
	await page.keyboard.press('ArrowUp');
	await page.keyboard.press('Enter');
	await page.waitForTimeout(1300);
	const after = (await snapshot()).elements.find((e) => e.id === shapes[0])!.bridges!.count;
	assert.equal(after, before + 1);
});

test('the shortcut puts them on and takes them off again', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	// The circle, so this does not lean on whatever the rectangle ended up with. ⌘⇧B is
	// Chrome's bookmarks-bar toggle and *is* interceptable — this is where that is verified.
	await clearAlarm();
	const p = at(140, 20);
	await page.mouse.click(p.x, p.y);
	await page.waitForTimeout(800);
	await post('/api/design/bridges/clear', { ids: [shapes[1]] });
	await page.waitForTimeout(1200);

	const key = process.platform === 'darwin' ? 'Meta+Shift+B' : 'Control+Shift+B';
	await page.keyboard.press(key);
	await page.waitForTimeout(1400);
	assert.equal(
		(await snapshot()).elements.find((e) => e.id === shapes[1])!.bridges?.count,
		4,
		'the shortcut did not reach the engine'
	);

	await page.keyboard.press(key);
	await page.waitForTimeout(1400);
	assert.equal((await snapshot()).elements.find((e) => e.id === shapes[1])!.bridges?.count, 0);
});

test('a selection with a line in it says how many shapes got them', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await post('/api/design/bridges/clear', { ids: shapes });
	const answer = await post('/api/design/bridges', { ids: shapes, count: 4, length_mm: 2 });
	const outcome = await answer.json();

	assert.equal(outcome.bridged, 2, 'the rectangle and the circle');
	assert.equal(outcome.skipped, 1, 'the line');
});
