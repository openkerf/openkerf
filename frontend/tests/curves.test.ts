/**
 * Curves: the pen draws them and the node tool edits them (P1).
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/curves.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`.
 *
 * Why it exists: before this the pen could only click corners and the node tool could only
 * drag a point, so a curve could be imported into OpenKerf but never drawn or repaired.
 * The two halves that are easy to get wrong and impossible to see in a unit test are
 * whether a *drag* really makes a curve (and not a corner with a stray handle), and
 * whether the handles the node tool shows are the ones that belong to the piece you
 * picked.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';
// The working record, not the repository: this writes five PNGs on every run with a
// live server, and at the old path they landed in the public tree — twice they were
// swept into a commit by a `git add -A`. `workshop/` is ignored here and is where the
// evidence of a round belongs. It is made if it is not there, so a checkout without the
// record still runs.
const SHOTS = new URL('../../workshop/screenshots/parity/', import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let bed: { x: number; y: number; w: number; h: number };
let size: { width_mm: number; height_mm: number };

/**
 * The bed's place on screen, measured again.
 *
 * Picking up a tool that explains itself puts a line of text under the bed, and the bed is
 * then refitted: measured, 1018 x 610 px becomes 986 x 591 with the node tool's hint under
 * it. A point in millimetres computed against the old measurement misses the shape by up
 * to sixteen pixels.
 */
async function remeasure() {
	bed = await page.$eval('.bed > svg', (n) => {
		const r = n.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height };
	});
}

/** A point on the bed in millimetres, as a place on the screen. */
const at = (xmm: number, ymm: number) => ({
	x: bed.x + (bed.w * xmm) / size.width_mm,
	y: bed.y + (bed.h * ymm) / size.height_mm
});

const design = async () => (await (await fetch(`${BASE}/api/design`)).json()) as {
	elements: { id: string; type: string; path: string; operation_ids: string[] }[];
};

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await fetch(`${BASE}/api/machines`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ info: 'ruida-beta', label: 'Curves test bench' })
		});
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	bed = await page.$eval('.bed > svg', (n) => {
		const r = n.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height };
	});
	size = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;
});

after(async () => {
	await browser?.close();
});

test('a drag with the pen pulls a curve out of the point', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.getByRole('button', { name: /^Pen/ }).click();
	await page.waitForTimeout(500);
	await remeasure();

	// A corner.
	const first = at(40, 60);
	await page.mouse.click(first.x, first.y);
	await page.waitForTimeout(200);

	// And a curve: press on the second point and pull downwards.
	const second = at(120, 60);
	await page.mouse.move(second.x, second.y);
	await page.mouse.down();
	await page.mouse.move(second.x + 60, second.y + 90, { steps: 8 });
	await page.waitForTimeout(150);
	// The handle and its mirror are both on screen while pulling; that mirror is what
	// bends the piece already laid down.
	assert.equal(await page.$$eval('.pen-grip', (n) => n.length), 2);
	// And the line under construction says what the keys do.
	assert.match(await page.evaluate(() => document.body.innerText), /drag for a curve/);
	await page.screenshot({ path: `${SHOTS}P1-pen-drag.png` });
	await page.mouse.up();
	await page.waitForTimeout(200);

	const third = at(200, 60);
	await page.mouse.click(third.x, third.y);
	await page.waitForTimeout(200);
	await page.keyboard.press('Enter');
	await page.waitForTimeout(1200);

	const drawn = (await design()).elements.filter((e) => e.type === 'elem path');
	assert.equal(drawn.length, 1, 'the pen should have drawn one path');
	assert.match(drawn[0].path, / C /, `no cubic in the path data: ${drawn[0].path}`);
	// A drawn shape lands in a layer, or it burns nothing.
	assert.ok(drawn[0].operation_ids.length, 'the drawn path has no layer');
});

test('Backspace takes back the last point instead of throwing the line away', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const before = (await design()).elements.length;
	const one = at(60, 200);
	const two = at(140, 200);
	const three = at(220, 200);
	await page.mouse.click(one.x, one.y);
	await page.waitForTimeout(150);
	await page.mouse.click(two.x, two.y);
	await page.waitForTimeout(150);
	await page.mouse.click(three.x, three.y);
	await page.waitForTimeout(150);
	assert.equal(await page.$$eval('.pen-dot', (n) => n.length), 3);

	await page.keyboard.press('Backspace');
	await page.waitForTimeout(300);
	assert.equal(await page.$$eval('.pen-dot', (n) => n.length), 2);
	// And nothing was deleted from the bed by that same key.
	assert.equal((await design()).elements.length, before);

	await page.keyboard.press('Escape');
	await page.waitForTimeout(400);
	assert.equal(await page.$$eval('.pen-dot', (n) => n.length), 0);
	assert.equal((await design()).elements.length, before, 'Escape must leave nothing behind');
});

type NodeRead = {
	closed: boolean;
	points: { index: number; x_mm: number; y_mm: number }[];
	segments: {
		index: number;
		kind: string;
		start: number;
		end: number;
		controls: { which: number; x_mm: number; y_mm: number }[];
	}[];
};

/** The shape's own reading of itself. Snapping moves a drawn point, so the only honest
 *  way to aim at a piece of the line is to ask where it actually ended up. */
const nodesOf = async (id: string) =>
	(await (await fetch(`${BASE}/api/design/elements/${id}/nodes`)).json()) as NodeRead;

/**
 * A line of three corners, put down through the API.
 *
 * Not drawn with the pen: a pen drag leaves a smooth node, and a smooth node bends the
 * piece on *both* sides of it — so a line drawn with one drag has no straight piece left
 * whose middle can be aimed at. Seeding keeps the aiming honest, and the pen itself is
 * already measured in the first test.
 */
async function seedCorners() {
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	const made = await (
		await fetch(`${BASE}/api/design/path`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ points: [[40, 100], [140, 100], [240, 100]] })
		})
	).json();
	await page.waitForTimeout(1500);
	return made.ids[0] as string;
}

/** Halfway along a piece — safely inside the twelve-pixel band you click a contour by,
 *  where an end point sits right on its edge (measured: 0.6 px outside, and the click
 *  missed). */
const midOf = (read: NodeRead, segment: { start: number; end: number }) =>
	at(
		(read.points[segment.start].x_mm + read.points[segment.end].x_mm) / 2,
		(read.points[segment.start].y_mm + read.points[segment.end].y_mm) / 2
	);

async function pickWithNodes(id: string, read: NodeRead) {
	await page.getByRole('button', { name: 'Select', exact: true }).click();
	await page.waitForTimeout(400);
	await remeasure();
	const grab = midOf(read, read.segments[0]);
	await page.mouse.click(grab.x, grab.y);
	await page.waitForTimeout(900);
	await page.getByRole('button', { name: /Nodes/ }).click();
	await page.waitForTimeout(1500);
	await remeasure();
}

test('a double-click on the line puts a node there, and Delete takes it away', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const id = await seedCorners();
	const read = await nodesOf(id);
	await pickWithNodes(id, read);
	assert.equal(await page.$$eval('.knot', (n) => n.length), 3, 'three nodes to start with');

	const middle = midOf(read, read.segments[1]);
	await page.mouse.dblclick(middle.x, middle.y);
	await page.waitForTimeout(1600);
	assert.equal(await page.$$eval('.knot', (n) => n.length), 4, 'the double-click added a node');
	const grown = await nodesOf(id);
	assert.equal(grown.points.length, 4);
	// And it landed where the click was, not somewhere along the line.
	const added = grown.points.find(
		(point) => Math.abs(point.x_mm - 190) < 2 && Math.abs(point.y_mm - 100) < 2
	);
	assert.ok(added, `no node near 190,100: ${JSON.stringify(grown.points)}`);

	// The node just added is the one in hand, so Delete removes exactly it.
	await page.keyboard.press('Delete');
	await page.waitForTimeout(1600);
	assert.equal(await page.$$eval('.knot', (n) => n.length), 3, 'Delete removed the node');
	assert.equal(
		(await design()).elements.filter((e) => e.type === 'elem path').length,
		1,
		'Delete on a node must not delete the shape'
	);
});

test('a piece can be curved, and then it has a handle to pull', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const id = await seedCorners();
	const read = await nodesOf(id);
	await pickWithNodes(id, read);

	// Take the first node in hand and curve the piece after it.
	const first = at(read.points[0].x_mm, read.points[0].y_mm);
	await page.mouse.click(first.x, first.y);
	await page.waitForTimeout(700);
	assert.equal(
		await page.$$eval('.handle-square', (n) => n.length),
		0,
		'a straight piece has no handle'
	);
	await page.keyboard.press('Shift+U');
	await page.waitForTimeout(1600);

	const bent = await nodesOf(id);
	assert.equal(bent.segments[0].kind, 'quad', 'the piece should be a curve now');
	assert.ok(
		(await page.$$eval('.handle-square', (n) => n.length)) > 0,
		'a node next to a curve should show its handle'
	);
	assert.ok(
		(await page.$$eval('.tether', (n) => n.length)) > 0,
		'a handle without its tether is a dot in the air'
	);
	assert.match(await page.evaluate(() => document.body.innerText), /Double-click the line/);
	await page.screenshot({ path: `${SHOTS}P1-node-handles.png` });

	// Dragging that handle bends the piece. The square sits on the chord, halfway between
	// the two nodes, because a fresh curve is the straight line it came from.
	const square = await page.$eval('.handle-square', (n) => {
		const r = n.getBoundingClientRect();
		return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
	});
	await page.mouse.move(square.x, square.y);
	await page.mouse.down();
	await page.mouse.move(square.x, square.y - 120, { steps: 8 });
	await page.mouse.up();
	await page.waitForTimeout(1600);
	const pulled = await nodesOf(id);
	const handle = pulled.segments[0].controls?.[0];
	assert.ok(handle, 'the curve lost its handle');
	// 120 px up is about 59 mm on this bed (986 px for 500 mm), and the anchors are at
	// y = 100.
	assert.ok(
		handle.y_mm < 60,
		`the handle should have come up, and it is at ${handle.y_mm} mm`
	);
	assert.equal(pulled.points.length, 3, 'a handle moves the curve, not the nodes');
	await page.screenshot({ path: `${SHOTS}P1-curve-pulled.png` });

	// And back, with the other key.
	await page.keyboard.press('Shift+L');
	await page.waitForTimeout(1600);
	assert.equal((await nodesOf(id)).segments[0].kind, 'line');
});

test('the menu on a node offers the verbs, and says why one cannot run', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const id = await seedCorners();
	const read = await nodesOf(id);
	await pickWithNodes(id, read);

	// The last node of an open line: nothing leaves it, so there is no piece to add a node
	// to and none to bend. That is the refusal the menu has to carry.
	const last = read.points.find(
		(point) => !read.segments.some((seg) => seg.start === point.index)
	);
	assert.ok(last, 'an open line has a last node');
	const where = at(last.x_mm, last.y_mm);
	await page.mouse.click(where.x, where.y);
	await page.waitForTimeout(600);
	await page.mouse.click(where.x, where.y, { button: 'right' });
	await page.waitForTimeout(700);

	const rows = await page.$$eval('[role="menu"] button, [role="menuitem"]', (nodes) =>
		nodes.map((n) => ({
			text: (n.textContent ?? '').trim(),
			off: (n as HTMLButtonElement).disabled,
			why: n.getAttribute('title') ?? ''
		}))
	);
	const find = (pattern: RegExp) => rows.find((r) => pattern.test(r.text));
	assert.ok(find(/Add a node here/), `no add row in the menu: ${JSON.stringify(rows)}`);
	assert.ok(find(/Remove this node/), 'no remove row in the menu');
	assert.equal(find(/Add a node here/)!.off, true, 'the last node has no piece after it');
	assert.match(find(/Add a node here/)!.why, /no piece after it/);
	// Removing it is exactly what you do want with a node like that.
	assert.equal(find(/Remove this node/)!.off, false);
	await page.screenshot({ path: `${SHOTS}P1-node-menu.png` });
	await page.keyboard.press('Escape');
});

test('a path of several subpaths opens in the node tool', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// Text turned into outlines: the shape the node tool exists for, and the one it could
	// not open. Measured before this: `GET .../nodes` answered HTTP 500 (`nan` is not
	// JSON), the bed showed 0 knots and the line under it advised making it a path first —
	// about something that already is `elem path`.
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	const made = await (
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ type: 'text', x_mm: 40, y_mm: 80, text: 'Hi' })
		})
	).json();
	const id = made.ids[0] as string;
	const answer = await fetch(`${BASE}/api/design/elements/${id}/nodes`);
	assert.equal(answer.status, 200);
	const read = (await answer.json()) as NodeRead & { closed: boolean };
	assert.ok(read.points.length > 4, `only ${read.points.length} anchors`);
	assert.ok(
		read.points.every((p) => Number.isFinite(p.x_mm) && Number.isFinite(p.y_mm)),
		'an anchor that is not a number'
	);
	// Every letter closes, so the shape closes.
	assert.equal(read.closed, true);

	await pickWithNodes(id, read);
	assert.equal(
		await page.$$eval('.knot', (n) => n.length),
		read.points.length,
		'the bed does not show the nodes the route reports'
	);
	assert.doesNotMatch(
		await page.evaluate(() => document.body.innerText),
		/Make it a path first/,
		'the advice for a shape that is not a path, on a shape that is one'
	);
	await page.screenshot({ path: `${SHOTS}P1-nodes-text-path.png` });
});

test('a drag on the contour with the node tool keeps the selection', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const id = await seedCorners();
	const read = await nodesOf(id);
	await pickWithNodes(id, read);
	assert.equal(await page.$$eval('.knot', (n) => n.length), 3);

	// A press on the line that misses a node, dragged away. Measured before this: nothing
	// moved (correct) but the panel then read "Nothing selected.", every knot was gone and
	// the only way back was clicking the shape again.
	const from = midOf(read, read.segments[0]);
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x + 60, from.y + 60, { steps: 6 });
	await page.mouse.up();
	await page.waitForTimeout(1200);

	assert.equal(await page.$$eval('.knot', (n) => n.length), 3, 'the nodes are gone');
	assert.doesNotMatch(
		await page.evaluate(() => document.body.innerText),
		/Nothing selected/,
		'the drag threw the selection away'
	);
	// And it really moved nothing.
	assert.equal((await nodesOf(id)).points.length, 3);
});

test('a node can be taken in hand from the keyboard, and then the verbs work', async (t) => {
	if (!reachable) return noServer(t, BASE);
	const id = await seedCorners();
	const read = await nodesOf(id);
	await pickWithNodes(id, read);

	// Measured before this: 70 Tab presses from a fresh load reached none of the four
	// grips, because every one of them was `tabindex="-1"`. So every verb was pointer-only.
	let reached = -1;
	for (let i = 0; i < 60 && reached < 0; i++) {
		await page.keyboard.press('Tab');
		reached = await page.evaluate(() => {
			const el = document.activeElement;
			return el?.classList?.contains('grip') ? 1 : -1;
		});
	}
	assert.equal(reached, 1, 'Tab never reaches a node');

	await page.keyboard.press('Enter');
	await page.waitForTimeout(400);
	assert.equal(
		await page.$$eval('.knot.picked', (n) => n.length),
		1,
		'Enter did not take the node in hand'
	);

	// And the menu on that node opens from the keyboard too. Measured before this:
	// Shift+F10 with the canvas focused opened nothing at all.
	await page.keyboard.press('Shift+F10');
	await page.waitForTimeout(600);
	assert.ok(
		(await page.$$eval('[role="menu"]', (n) => n.length)) > 0,
		'Shift+F10 on a node opens no menu'
	);
	await page.keyboard.press('Escape');
	await page.waitForTimeout(400);

	// And with it in hand a verb runs — the same key the menu row carries.
	const before = (await nodesOf(id)).segments.map((s) => s.kind);
	await page.keyboard.press('Shift+U');
	await page.waitForTimeout(1600);
	const after = (await nodesOf(id)).segments.map((s) => s.kind);
	assert.notDeepEqual(after, before, `the verb did nothing: ${before} → ${after}`);
	assert.ok(after.includes('quad'), `no curve among ${after}`);
});
