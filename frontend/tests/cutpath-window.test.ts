/**
 * The cut-path window in the running app (gap S1).
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/cutpath-window.test.ts
 *
 * Shares one engine with the other e2e tests, so `--test-concurrency=1`; without a
 * reachable server it skips itself.
 *
 * The arithmetic behind the drawing is pinned in `cutpath.test.ts`. What is pinned
 * *here* is what only the running window can show, and every line of it is a defect
 * that was measured on screen before it was fixed:
 *
 * - the numbers stacked. Three passes numbered the same rectangle three times, at
 *   the identical box (x 406.0, y 192.9), and the eighteen letters of a caption all
 *   fell inside 96 x 29 px: 59 of 276 pairs overlapped, the worst pair completely.
 * - the scrubber could not reach the end. `max` was 297.72 with a step of 0.29772,
 *   so dragging the thumb fully right gave 297.42 and the first press of Play
 *   replayed 0.3 s and stopped.
 * - every open flashed "The path cannot be fetched while the server is away" — for
 *   215 ms, on 127.0.0.1, on a cached answer, because `null` meant both "not asked
 *   yet" and "unreachable".
 * - Alt+P opened the window on an empty bed while the menu row beside it was
 *   disabled and said "Nothing is on the bed".
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Alt+P with the page itself focused, the way a user presses it. */
async function pressAltP() {
	await page.mouse.click(700, 400);
	await page.waitForTimeout(300);
	await page.keyboard.press('Alt+p');
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Cut path test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
});

test('on an empty bed the key obeys the row that says why not', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' });
	await post('/api/project/new');
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);

	await pressAltP();
	await page.waitForTimeout(700);

	assert.equal(
		await page.$$eval('[role="dialog"]', (n) => n.length),
		0,
		'Alt+P opened a window the menu calls unavailable'
	);
	// And the row it disobeyed really is disabled, with the reason on it.
	await page.mouse.click(700, 400, { button: 'right' });
	await page.waitForTimeout(400);
	const row = await page.$$eval('[role="menu"] button', (nodes) =>
		(nodes as HTMLButtonElement[])
			.filter((n) => n.textContent?.includes('Show cut path'))
			.map((n) => ({ off: n.disabled, why: n.title }))
	);
	assert.equal(row.length, 1, 'no cut-path row in the canvas menu');
	assert.equal(row[0].off, true);
	assert.match(row[0].why, /bed/);
	await page.keyboard.press('Escape');
});

test('the way in never claims the server is away', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	// A design with passes on its layer: the case that numbered one rectangle three
	// times, and the case a preview is opened for most often.
	await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 });
	await post('/api/design/elements', { type: 'rect', x_mm: 120, y_mm: 20, width_mm: 60, height_mm: 40 });
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const layer = design.operations.find((o: { element_ids: string[] }) => o.element_ids.length);
	await fetch(`${BASE}/api/design/operations/${encodeURIComponent(layer.id)}`, {
		method: 'PATCH',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ passes: 3 })
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);

	// Sample the dialog on a 5 ms tick from before the key is pressed: the false
	// message lasted 215 ms, which no screenshot after the fact would catch.
	await page.evaluate(() => {
		(window as unknown as { __seen: string[] }).__seen = [];
		(window as unknown as { __timer: number }).__timer = window.setInterval(() => {
			const text = document.querySelector('[role="dialog"]')?.textContent;
			if (text) (window as unknown as { __seen: string[] }).__seen.push(text);
		}, 5);
	});
	await pressAltP();
	await page.waitForSelector('[role="dialog"] svg', { timeout: 30000 });
	const seen: string[] = await page.evaluate(() => {
		clearInterval((window as unknown as { __timer: number }).__timer);
		return (window as unknown as { __seen: string[] }).__seen;
	});

	assert.ok(seen.length > 0, 'the window never appeared');
	assert.equal(
		seen.filter((text) => /server is away|server weg/.test(text)).length,
		0,
		'the window claimed the server was away'
	);
});

test('every contour is numbered once, and no number lies on another', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await page.waitForTimeout(500);
	const numbers = await page.$$eval('[role="dialog"] text.order', (nodes) =>
		nodes.map((n) => {
			const r = n.getBoundingClientRect();
			return { label: n.textContent ?? '', x: r.x, y: r.y, w: r.width, h: r.height };
		})
	);

	// Two rectangles over three passes: two numbers, not six.
	assert.deepEqual(
		numbers.map((n) => n.label),
		['1', '2']
	);
	for (let i = 0; i < numbers.length; i++)
		for (let j = i + 1; j < numbers.length; j++) {
			const a = numbers[i];
			const b = numbers[j];
			const over =
				Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0 &&
				Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0;
			assert.equal(over, false, `numbers ${a.label} and ${b.label} lie on each other`);
		}
	// And the same order in words, so it is not graphics-only.
	const lines = await page.$$eval('[role="dialog"] .order-list li', (n) =>
		n.map((x) => x.textContent?.trim() ?? '')
	);
	assert.equal(lines.length, 2);
	assert.match(lines[0], /1: .*60 × 40 mm.*20, 20.*3/);
});

test('the scrubber reaches the end, and Play there starts over', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const clock = () =>
		page.$eval('[role="dialog"] .clock', (n) => (n.textContent ?? '').trim());
	const range = (await page.$('[role="dialog"] input[type=range]'))!;
	const box = (await range.boundingBox())!;

	await page.mouse.move(box.x + 2, box.y + box.height / 2);
	await page.mouse.down();
	await page.mouse.move(box.x + box.width + 60, box.y + box.height / 2, { steps: 6 });
	await page.mouse.up();
	const [at, total] = (await clock()).split('/').map((part) => part.trim());
	assert.equal(at, total, `dragged fully right and the clock read ${at} of ${total}`);

	// One press, not two: the guard beside `toggle()` exists for exactly this.
	await page.click('[role="dialog"] .transport .btn');
	await page.waitForTimeout(400);
	const [running] = (await clock()).split('/').map((part) => part.trim());
	assert.notEqual(running, total, 'Play at the end did nothing on the first press');

	// The keyboard has to be able to move it too, in steps somebody can read.
	await page.click('[role="dialog"] .transport .btn'); // pause
	await range.focus();
	await page.keyboard.press('Home');
	const start = await clock();
	await page.keyboard.press('ArrowRight');
	const stepped = await clock();
	assert.notEqual(stepped, start, 'one arrow press moved less than the clock can show');
	assert.equal(
		await range.getAttribute('aria-valuetext'),
		stepped.split('/')[0].trim(),
		'the scrubber announces raw seconds instead of the clock'
	);
});
