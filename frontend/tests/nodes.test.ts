/**
 * The node tool has three quiet states. Does it say which one it is in?
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/nodes.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more
 * than one file at a time goes wrong: use `--test-concurrency=1`.
 *
 * Why it exists: with nothing selected, or with more than one shape, the tool
 * draws no points. It does look pressed. Measured with two shapes selected: the
 * right-hand panel showed the ordinary multiple selection and the word "node"
 * appeared nowhere on screen — the tool looks broken while it is simply waiting
 * for one shape.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;
let bed: { x: number; y: number; w: number; h: number };

/** Converting a point on the bed in millimetres to the screen. */
const point = (xmm: number, ymm: number, wide: number, high: number) => ({
	x: bed.x + (bed.w * xmm) / wide,
	y: bed.y + (bed.h * ymm) / high
});

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
			body: JSON.stringify({ info: 'ruida-beta', label: 'Nodes test bench' })
		});
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
});

after(async () => {
	await browser?.close();
});

const onScreen = () => page.evaluate(() => document.body.innerText);

test('with no selection the tool says what it needs', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	await page.waitForTimeout(2500);
	const box = await page.$eval('.bed > svg', (n) => {
		const r = n.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height };
	});
	bed = box;
	const size = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;

	// Two shapes to work with.
	for (const [tool, x, y] of [
		['Rectangle', 80, 60],
		['Circle', 200, 60]
	] as const) {
		await page.getByRole('button', { name: tool, exact: true }).click();
		await page.waitForTimeout(300);
		const p = point(x, y, size.width_mm, size.height_mm);
		await page.mouse.click(p.x, p.y);
		await page.waitForTimeout(1000);
	}

	// Deselect and pick up the node tool.
	await page.getByRole('button', { name: 'Select', exact: true }).click();
	await page.waitForTimeout(250);
	const empty = point(size.width_mm - 20, size.height_mm - 20, size.width_mm, size.height_mm);
	await page.mouse.click(empty.x, empty.y);
	await page.waitForTimeout(600);
	await page.getByRole('button', { name: /Nodes/ }).click();
	await page.waitForTimeout(1000);

	const text = await onScreen();
	assert.match(text, /Nodes works on one shape/, `no explanation on screen:\n${text.slice(0, 400)}`);
});

test('with two shapes selected it says how many too many there are', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const size = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;
	await page.getByRole('button', { name: 'Select', exact: true }).click();
	await page.waitForTimeout(250);
	const a = point(80, 60, size.width_mm, size.height_mm);
	const b = point(200, 60, size.width_mm, size.height_mm);
	await page.mouse.click(a.x, a.y);
	await page.waitForTimeout(600);
	await page.keyboard.down('Shift');
	await page.mouse.click(b.x, b.y);
	await page.keyboard.up('Shift');
	await page.waitForTimeout(800);
	await page.getByRole('button', { name: /Nodes/ }).click();
	await page.waitForTimeout(1000);

	const text = await onScreen();
	assert.match(text, /2 are selected/, `no count on screen:\n${text.slice(0, 400)}`);
});

test('with exactly one shape the explanation goes quiet and the points are there', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);
	const size = (await (await fetch(`${BASE}/api/devices`)).json()).find(
		(d: { active: boolean }) => d.active
	).bed;
	// First right away from the previous selection: shift-clicking stacks.
	await page.getByRole('button', { name: 'Select', exact: true }).click();
	await page.waitForTimeout(250);
	const empty = point(size.width_mm - 20, size.height_mm - 20, size.width_mm, size.height_mm);
	await page.mouse.click(empty.x, empty.y);
	await page.waitForTimeout(600);
	const a = point(80, 60, size.width_mm, size.height_mm);
	await page.mouse.click(a.x, a.y);
	await page.waitForTimeout(900);
	await page.getByRole('button', { name: /Nodes/ }).click();
	await page.waitForTimeout(1800);

	assert.ok((await page.$$eval('.knot', (n) => n.length)) > 0, 'there should be points');
	const text = await onScreen();
	// An explanation that stays up while the tool simply works is noise.
	assert.doesNotMatch(text, /Nodes works on one shape/);
	assert.doesNotMatch(text, /no loose points/);
});
