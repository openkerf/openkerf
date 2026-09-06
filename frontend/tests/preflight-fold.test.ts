/**
 * The pre-flight opens with its numbers above the sticky footer, not under it.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8122 node --test frontend/tests/preflight-fold.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` makes that a failure).
 * Nothing is pressed here: the panel is measured as it opens, and the laser is never
 * touched.
 *
 * Why it exists. The footer is sticky, so whatever is last in the column is what the
 * footer lies over — and the footer was 211.6 px at 1440 x 900 and 230.5 px at
 * 1024 x 768, a quarter to a third of the panel. Measured on this seed (four layers on
 * unverified presets, no machine attached, which is the state the app opens in), with
 * the footer's top at 660 / 528 / 560 / 493 at the four sizes below: the "4 layers use
 * presets that were not verified" warning lay under the footer at 1366 x 768
 * (`elementFromPoint` on its middle answered `SPAN.pf-head`) and at 1024 x 768
 * (`BUTTON.btn`), the "machine is not responding" warning at 1024 x 768 (`LI`), and the
 * layer table at every size but 1440, where only its header row was clear.
 *
 * What is measured: at four viewports the material row, every warning in the column and
 * the first two rows of the layer table are each the topmost element at their own middle
 * and lie wholly above the footer's top edge. The place they are in is not pinned — only
 * that the one screen you read before you burn does not hide what it has to say.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const SIZES: [number, number][] = [
	[1440, 900],
	[1366, 768],
	[1280, 800],
	[1024, 768]
];

let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Four layers with a shape in each: the table plus the "not measured" warning is what
 *  makes the column longer than the panel, not the number of shapes. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers = [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 },
		{ type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
	];
	for (const layer of layers) await post('/api/design/operations', layer);
	for (let i = 0; i < layers.length; i++) {
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
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	await aDesign();
});

after(async () => {
	await browser?.close();
});

for (const [width, height] of SIZES) {
	test(`the pre-flight's numbers clear the footer at ${width} x ${height}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width, height } });
		const page = await context.newPage();
		try {
			await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.pf-actions .btn.primary', { timeout: 20000 });
			// The estimate lands after the page; wait for the answer, not for a guess
			// about how long it takes.
			await page.waitForSelector('.pf-actions .pf-start-time', { timeout: 20000 });
			await page.waitForSelector('.pf-layers tbody tr', { timeout: 20000 });
			await page.waitForTimeout(500);
			const measured = await page.evaluate(() => {
				const stick = document.querySelector('.pf-stick')!.getBoundingClientRect();
				const wanted: { what: string; node: Element }[] = [];
				const material = document.querySelector('.pf-time.sheet');
				if (material) wanted.push({ what: 'the material row', node: material });
				for (const warning of document.querySelectorAll('.preflight > .pf-warn')) {
					wanted.push({
						what: `the warning "${(warning.textContent ?? '').trim().slice(0, 34)}…"`,
						node: warning
					});
				}
				const rows = [
					...document.querySelectorAll('.pf-layers thead tr, .pf-layers tbody tr')
				].slice(0, 3);
				rows.forEach((row, i) =>
					wanted.push({ what: i === 0 ? 'the table header' : `table row ${i}`, node: row })
				);
				return {
					stickTop: Math.round(stick.top),
					stickHeight: Math.round(stick.height),
					items: wanted.map(({ what, node }) => {
						const box = node.getBoundingClientRect();
						const hit = document.elementFromPoint(box.left + 6, box.top + box.height / 2);
						return {
							what,
							top: Math.round(box.top),
							bottom: Math.round(box.bottom),
							self: Boolean(hit && (hit === node || node.contains(hit))),
							over: hit
								? `${hit.tagName}.${typeof hit.className === 'string' ? hit.className.split(' ')[0] : ''}`
								: null
						};
					})
				};
			});
			assert.ok(measured.items.length >= 5, 'the pre-flight did not open with its table');
			for (const item of measured.items) {
				assert.ok(
					item.bottom <= measured.stickTop,
					`${item.what} runs to y ${item.bottom}, past the footer's top edge at ${measured.stickTop}`
				);
				assert.ok(item.self, `${item.what} lies behind ${item.over}`);
			}
		} finally {
			await context.close();
		}
	});
}
