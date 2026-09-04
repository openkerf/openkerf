/**
 * The safety checklist is readable at the moment you need it.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/checklist-reach.test.ts
 *
 * Skips itself without a reachable server. It never starts a job.
 *
 * Measured at 1440 x 900 with a seeded design, the Job tab open and nothing scrolled:
 * the sticky footer carrying "Start job" began at y 803, and of the three checklist
 * items only "Lid closed" (781.6-799.5) was clear of it. `elementFromPoint` in the
 * middle of "Extraction and air assist on" answered `DIV.pf-stick`, and in the middle
 * of "Workpiece is clamped and flat" it answered `BUTTON.btn` — the start button
 * itself. Three lines you are meant to work down before you press, and two of them lay
 * under the thing you press.
 *
 * They are in the footer now, above the buttons, so they cannot be scrolled away from
 * the button they belong to. What this test pins is the property, not the place: every
 * item of the checklist is the topmost thing at its own middle.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Checklist test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	// Enough work that the preparation is longer than the panel is high; that is the
	// state in which the footer starts covering what lies above it. Four layers and a
	// shape in each: the layer table plus the "not measured with a test grid" warning
	// is what makes the column long, not the number of shapes.
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 },
		{ type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
	]) {
		await post('/api/design/operations', layer);
	}
	for (let i = 0; i < 4; i++) {
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 40,
			y_mm: 20,
			width_mm: 30,
			height_mm: 30
		});
	}
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const ops = design.operations.filter((o: { grid?: unknown }) => !o.grid);
	const elements = design.elements as { id: string }[];
	for (let i = 0; i < Math.min(ops.length, elements.length); i++) {
		for (const op of ops) {
			await post('/api/design/unassign', { ids: [elements[i].id], operation_id: op.id });
		}
		await post('/api/design/assign', { ids: [elements[i].id], operation_id: ops[i].id });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);
});

after(async () => {
	await browser?.close();
});

test('every line of the checklist is readable where it stands', async (t) => {
	if (!reachable) return noServer(t, BASE);

	const items = await page.evaluate(() => {
		const found = [...document.querySelectorAll('li')].filter((n) =>
			/Lid closed|Extraction and air|Workpiece is clamped/.test(n.textContent ?? '')
		);
		return found.map((n) => {
			const box = n.getBoundingClientRect();
			const hit = document.elementFromPoint(box.x + 5, box.y + box.height / 2);
			return {
				text: (n.textContent ?? '').trim().slice(0, 32),
				onScreen: box.top >= 0 && box.bottom <= window.innerHeight,
				self: hit === n || n.contains(hit),
				over: hit ? `${hit.tagName}.${typeof hit.className === 'string' ? hit.className.split(' ')[0] : ''}` : null
			};
		});
	});

	assert.equal(items.length, 3, 'the checklist does not have its three lines');
	for (const item of items) {
		assert.ok(item.onScreen, `"${item.text}" is not on screen without scrolling`);
		assert.ok(item.self, `"${item.text}" lies behind ${item.over}`);
	}
});
