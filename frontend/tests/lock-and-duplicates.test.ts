/**
 * Locking a shape, and clearing out shapes that lie on top of each other.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/lock-and-duplicates.test.ts
 *
 * One engine is shared with the other e2e tests, so use `--test-concurrency=1`.
 * Without a reachable server the file skips itself.
 *
 * Why it exists: both features are about something you cannot see. A lock is only
 * real if the canvas refuses the drag — a flag that the API knows about and the
 * handles ignore is worse than no lock, because you would trust it. And a duplicate
 * removal changes nothing on screen by definition, so the count in the question and
 * the count in the note afterwards are the whole of the evidence.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let bed = { x: 0, y: 0, w: 0, h: 0, wideMm: 1, highMm: 1 };

const post = (path: string, body: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

/** A point on the bed given in millimetres, as screen coordinates. */
const at = (xMm: number, yMm: number) => ({
	x: bed.x + (bed.w * xMm) / bed.wideMm,
	y: bed.y + (bed.h * yMm) / bed.highMm
});

const design = async () => (await fetch(`${BASE}/api/design`)).json();

/** How many corner handles the canvas is drawing right now. */
const handles = () => page.locator('.handle').count();

/** The visible dialog as one line of text, or null. */
const dialogText = () =>
	page.evaluate(() => {
		const box = [...document.querySelectorAll('dialog,[role=dialog]')].find(
			(node) => (node as HTMLDialogElement).open || (node as HTMLElement).offsetParent !== null
		);
		return box ? (box as HTMLElement).innerText.replace(/\s+/g, ' ').trim() : null;
	});

/** The bed in screen pixels; read again after every reload, because the view fits
 *  itself to what is on the bed and the box moves with it. */
async function measureBed() {
	const box = await page.$eval('.bed > svg', (node) => {
		const rect = node.getBoundingClientRect();
		return { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
	});
	bed = { ...bed, ...box };
}

async function freshBed() {
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	// And throw the autosave away: an empty bed plus a saved state makes the app offer
	// to restore it, and that card sits over the whole canvas.
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	// A clean URL: the reload would otherwise restore a selection of a shape that has
	// just been cleared away.
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	await measureBed();
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Lock test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });

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

test('a locked shape shows no handles and cannot be dragged', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await freshBed();
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 40,
		y_mm: 40,
		width_mm: 60,
		height_mm: 40
	});
	await page.waitForTimeout(1200);

	// Pick it up by its contour: the top edge, not the middle.
	const onEdge = at(70, 40);
	await page.mouse.click(onEdge.x, onEdge.y);
	await page.waitForTimeout(700);
	assert.ok((await handles()) > 0, 'an unlocked shape should have handles to size it by');

	await page.keyboard.press('Meta+l');
	await page.waitForTimeout(900);
	assert.equal(await handles(), 0, 'a locked shape still offered its sizing handles');

	const before = (await design()).elements[0];
	await page.mouse.move(onEdge.x, onEdge.y);
	await page.mouse.down();
	await page.mouse.move(onEdge.x + 90, onEdge.y + 60, { steps: 8 });
	await page.mouse.up();
	await page.waitForTimeout(1000);
	const after = (await design()).elements[0];
	assert.equal(
		Math.round(after.x_mm),
		Math.round(before.x_mm),
		'the locked shape moved when dragged'
	);
	assert.equal(Math.round(after.y_mm), Math.round(before.y_mm));

	// And the panel says what the lock covers, with the way out in it.
	const panel = await page.evaluate(() => document.body.innerText);
	assert.match(panel, /locked/i, 'the panel said nothing about the shape being locked');
	await page.getByRole('button', { name: /^Unlock$/ }).click();
	await page.waitForTimeout(900);
	assert.ok((await handles()) > 0, 'unlocking did not give the handles back');
});

test('the bed menu counts what lies on top of what, and removing says how many went', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await freshBed();
	// Three of one rectangle and two of one circle: two stacks, three shapes too many.
	for (let i = 0; i < 3; i++) {
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 30,
			y_mm: 30,
			width_mm: 60,
			height_mm: 40
		});
	}
	for (let i = 0; i < 2; i++) {
		await post('/api/design/elements', { type: 'circle', cx_mm: 200, cy_mm: 100, r_mm: 25 });
	}
	await page.waitForTimeout(1200);

	const openIt = async () => {
		const empty = at(bed.wideMm * 0.9, bed.highMm * 0.9);
		await page.mouse.click(empty.x, empty.y, { button: 'right' });
		await page.waitForTimeout(700);
		await page
			.getByRole('menuitem', { name: /Remove duplicates/ })
			.first()
			.click();
		await page.waitForTimeout(1000);
	};

	await openIt();
	const question = await dialogText();
	assert.match(
		question ?? '',
		/3 shapes lie on top of another one, in 2 places/,
		`the question did not count the stacks: ${question}`
	);

	await page
		.getByRole('button', { name: /^Remove 3$/ })
		.click();
	await page.waitForTimeout(1500);
	assert.equal((await design()).elements.length, 2, 'the wrong number of shapes was removed');
	const note = await page.evaluate(() => document.body.innerText);
	assert.match(note, /3 duplicates removed/, 'nothing said how many went');

	// Asked again, it says so instead of offering to remove nothing.
	await openIt();
	const second = await dialogText();
	assert.match(second ?? '', /No two shapes in this design lie on top of each other/);
	assert.equal(
		await page.getByRole('button', { name: /^Remove/ }).count(),
		0,
		'a Remove button was offered with nothing to remove'
	);
});
