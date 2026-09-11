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
 * What is measured, at four viewports and once more with a rotary fitted: the material
 * row, every warning in the column, the "Show cut path" button (`.pf-order`) and — with
 * no rotary — the first two rows of the layer table are each the topmost element at their
 * own middle and lie wholly above the footer's top edge. The place they are in is not pinned — only
 * that the one screen you read before you burn does not hide what it has to say.
 *
 * With a rotary fitted the table is left out of the opening measurement and held at the
 * foot instead: measured at 1024 x 768, the rotary's two sentences leave 462 px between
 * the material row and the footer's top at 654 for 566 px of warnings, button and table,
 * and the table's own header then stands at 647. What is asserted there is the order of
 * the sacrifice — every warning readable, the one control pressable, the rows scrolled to.
 *
 * And the tail. What the footer does lie over as the panel opens is the drawing, whose
 * own captions and notices sit under it at the two smallest sizes; a picture is prose,
 * and prose you can scroll to. The second half of each test scrolls the foot of the
 * pre-flight into view and requires that the drawing *and* the button inside it (the
 * picture is the enlarge control) then stand clear of the footer and answer for
 * themselves. `.preflight` is not the last block in `.panel-scroll`, so the footer
 * un-sticks at its foot and nothing in the pre-flight is unreachable — that is the
 * property, and it is measured rather than assumed.
 *
 * The rotary case is the state P7 lists last, and it is the longest column the pre-flight
 * has: two more sentences above the table. Its two paragraphs are put into the DOM here
 * with the words `job.rotary.chuck`, `job.rotary.frame` and `rotary.overlap` actually
 * render, instead of switching the machine's rotary on over the API: that setting is
 * stored on the device and lands in the shared `MeerK40t.cfg` (see CLAUDE.md), and a
 * rotary left on there rescales the Y of the next real job on this computer. A test may
 * only press what it measures.
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
		test(`the pre-flight's numbers clear the footer at ${width} x ${height}${what}`, async (t) => {
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
						if (withRotary) {
							// Where the component puts them: under the material row, above
							// everything the table says.
							const anchor = preflight.querySelector('.pf-time.sheet')!.nextElementSibling;
							(lines as string[]).forEach((text, i) => {
								const line = document.createElement('p');
								line.className = i === 0 ? 'pf-warn strong' : 'pf-warn';
								line.textContent = text;
								preflight.insertBefore(line, anchor);
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
						const read = (nodes: { what: string; node: Element }[]) => ({
							stickTop: Math.round(document.querySelector('.pf-stick')!.getBoundingClientRect().top),
							stickHeight: Math.round(
								document.querySelector('.pf-stick')!.getBoundingClientRect().height
							),
							items: nodes.map(({ what, node }) => ({ what, ...box(node) }))
						});

						const wanted: { what: string; node: Element }[] = [];
						const material = document.querySelector('.pf-time.sheet');
						if (material) wanted.push({ what: 'the material row', node: material });
						for (const warning of document.querySelectorAll('.preflight > .pf-warn')) {
							wanted.push({
								what: `the warning "${(warning.textContent ?? '').trim().slice(0, 34)}…"`,
								node: warning
							});
						}
						if (!withRotary) {
							// Not with the rotary: at 1024 x 768 its two extra sentences push the
							// table's own header to 647, past a footer top of 654, and there is no
							// arrangement of this column that fits 566 px of it into 462 px. The
							// table is rows you work down; it is held at the foot instead.
							const rows = [
								...document.querySelectorAll('.pf-layers thead tr, .pf-layers tbody tr')
							].slice(0, 3);
							rows.forEach((row, i) =>
								wanted.push({ what: i === 0 ? 'the table header' : `table row ${i}`, node: row })
							);
						}
						// A button behind the footer is the harder half of this: prose you can
						// scroll to, a control you cannot press at all. The seed always hands
						// `onCutPath` in, so its absence is itself the bug and is asserted.
						const order = document.querySelector('.pf-order');
						if (order) wanted.push({ what: 'the "Show cut path" button', node: order });
						const asOpened = read(wanted);

						// Now the foot of the column: scroll until the pre-flight's own bottom
						// edge meets the bottom of the scroller, which is where the sticky
						// footer lets go.
						scroller.scrollTop +=
							preflight.getBoundingClientRect().bottom - scroller.getBoundingClientRect().bottom;
						const tail: { what: string; node: Element }[] = [];
						const table = document.querySelector('.pf-layers');
						if (table) tail.push({ what: 'the layer table', node: table });
						const drawing = document.querySelector('.pf-beeld');
						if (drawing) tail.push({ what: 'the drawing', node: drawing });
						const enlarge = document.querySelector('.pf-beeld button');
						if (enlarge) tail.push({ what: 'the drawing you press to enlarge', node: enlarge });
						const atFoot = read(tail);
						scroller.scrollTop = 0;
						return { asOpened, atFoot, hasOrder: Boolean(order), hasDrawing: Boolean(drawing) };
					},
					[rotary, ROTARY_LINES] as [boolean, string[]]
				);
				assert.ok(measured.asOpened.items.length >= 4, 'the pre-flight did not open with its numbers');
				assert.ok(
					measured.hasOrder,
					'the "Show cut path" button is not on the pre-flight at all — the seed hands `onCutPath` in'
				);
				assert.ok(measured.hasDrawing, 'the pre-flight opened without its drawing');
				for (const item of measured.asOpened.items) {
					assert.ok(
						item.bottom <= measured.asOpened.stickTop,
						`${item.what} runs to y ${item.bottom}, past the footer's top edge at ${measured.asOpened.stickTop}`
					);
					assert.ok(item.self, `${item.what} lies behind ${item.over}`);
				}
				for (const item of measured.atFoot.items) {
					assert.ok(
						item.bottom <= measured.atFoot.stickTop,
						`with the foot of the pre-flight in view, ${item.what} still runs to y ${item.bottom}, past the footer's top edge at ${measured.atFoot.stickTop}`
					);
					assert.ok(item.self, `with the foot of the pre-flight in view, ${item.what} lies behind ${item.over}`);
				}
			} finally {
				await context.close();
			}
		});
	}
}
