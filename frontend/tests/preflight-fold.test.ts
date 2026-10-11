/**
 * The pre-flight reads top to bottom: what it burns on, what is wrong with it, the one
 * action, and then the evidence — and nothing covers anything.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8122 node --test frontend/tests/preflight-fold.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` makes that a failure).
 * Nothing is pressed here: the panel is measured as it opens, and the laser is never
 * touched.
 *
 * Why it exists. The action row (`.pf-stick`) used to be a sticky footer at the end of
 * the column, and whatever stood last was what it lay over: warnings and table rows at
 * 1366 x 768 and 1024 x 768 answered the footer under `elementFromPoint`. The row now
 * stands directly after the warnings and stays sticky only as a guard, so the promise
 * is in two halves:
 *
 * - As opened, at four viewports and once more with a rotary fitted: the material row
 *   and every warning lie wholly above the action row and are each the topmost element
 *   at their own middle, and the start button is on screen and answers for itself.
 * - Below it, the "Show cut path" button, the first rows of the layer table and the
 *   drawing (the picture is the enlarge control) each stand clear when scrolled to.
 *
 * The rotary case is the longest column the pre-flight has: two more sentences among the
 * warnings. They are put into the DOM here with the words `job.rotary.chuck`,
 * `job.rotary.frame` and `rotary.overlap` actually render, instead of switching the
 * machine's rotary on over the API: that setting is stored on the device and lands in
 * the shared `MeerK40t.cfg` (see CLAUDE.md), and a rotary left on there rescales the Y
 * of the next real job on this computer. A test may only press what it measures.
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

/** The two sentences the rotary adds above the table, word for word from `en.ts`. */
const ROTARY_LINES = [
	'The rotary is on: a chuck of 80 mm, Y scaled by 1.036269. Show frame, in the top bar, turns the object rather than crossing the bed.',
	'The work is 300 mm tall and once round is 251.3 mm, so the end burns over the beginning.'
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

for (const rotary of [false, true]) {
	for (const [width, height] of SIZES) {
		const what = rotary ? ' with a rotary fitted' : '';
		test(`the pre-flight's warnings stand above the action row at ${width} x ${height}${what}`, async (t) => {
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
				const measured = await page.evaluate(
					([withRotary, lines]) => {
						const preflight = document.querySelector('.preflight')!;
						const stick = document.querySelector('.pf-stick')!;
						if (withRotary) {
							// Where the component puts them: with the other warnings, above the
							// action row.
							(lines as string[]).forEach((text) => {
								const line = document.createElement('div');
								line.className = 'notice warn';
								line.textContent = text;
								preflight.insertBefore(line, stick);
							});
						}
						const scroller = document.querySelector('.panel-scroll') as HTMLElement;
						const box = (node: Element) => {
							const rect = node.getBoundingClientRect();
							const hit = document.elementFromPoint(rect.left + 6, rect.top + rect.height / 2);
							return {
								top: Math.round(rect.top),
								bottom: Math.round(rect.bottom),
								self: Boolean(hit && (hit === node || node.contains(hit))),
								over: hit
									? `${hit.tagName}.${typeof hit.className === 'string' ? hit.className.split(' ')[0] : ''}`
									: null
							};
						};

						// As opened: the material row and every warning stand above the action
						// row, and the start button itself is on screen and answers for itself.
						const above: { what: string; node: Element }[] = [];
						const material = document.querySelector('.pf-time.sheet');
						if (material) above.push({ what: 'the material row', node: material });
						for (const warning of document.querySelectorAll('.preflight > .notice, .preflight > .help.warn')) {
							above.push({
								what: `the warning "${(warning.textContent ?? '').trim().slice(0, 34)}…"`,
								node: warning
							});
						}
						const stickTop = Math.round(stick.getBoundingClientRect().top);
						const start = document.querySelector('.pf-split .btn.primary')!;
						const asOpened = {
							stickTop,
							items: above.map(({ what, node }) => ({ what, ...box(node) })),
							start: { ...box(start), viewport: window.innerHeight }
						};

						// Below the action row: the cut-path button, the table and the drawing.
						// Each, scrolled to, stands clear of the row — sticky or not, the row
						// never lies over what you scroll to.
						const below: { what: string; node: Element }[] = [];
						const order = document.querySelector('.pf-order');
						if (order) below.push({ what: 'the "Show cut path" button', node: order });
						[...document.querySelectorAll('.pf-layers thead tr, .pf-layers tbody tr')]
							.slice(0, 3)
							.forEach((row, i) =>
								below.push({ what: i === 0 ? 'the table header' : `table row ${i}`, node: row })
							);
						const drawing = document.querySelector('.pf-beeld button');
						if (drawing) below.push({ what: 'the drawing you press to enlarge', node: drawing });
						const scrolledTo = below.map(({ what, node }) => {
							node.scrollIntoView({ block: 'center' });
							return { what, ...box(node) };
						});
						scroller.scrollTop = 0;
						return { asOpened, scrolledTo, hasOrder: Boolean(order), hasDrawing: Boolean(drawing) };
					},
					[rotary, ROTARY_LINES] as [boolean, string[]]
				);
				assert.ok(measured.asOpened.items.length >= 1, 'the pre-flight did not open with its material row');
				assert.ok(
					measured.hasOrder,
					'the "Show cut path" button is not on the pre-flight at all — the seed hands `onCutPath` in'
				);
				assert.ok(measured.hasDrawing, 'the pre-flight opened without its drawing');
				for (const item of measured.asOpened.items) {
					assert.ok(
						item.bottom <= measured.asOpened.stickTop,
						`${item.what} runs to y ${item.bottom}, past the action row's top edge at ${measured.asOpened.stickTop}`
					);
					assert.ok(item.self, `${item.what} lies behind ${item.over}`);
				}
				const start = measured.asOpened.start;
				assert.ok(start.bottom <= start.viewport, `the start button runs to y ${start.bottom}, off the screen`);
				assert.ok(start.self, `the start button lies behind ${start.over}`);
				for (const item of measured.scrolledTo) {
					assert.ok(item.self, `scrolled to, ${item.what} lies behind ${item.over}`);
				}
			} finally {
				await context.close();
			}
		});
	}
}
