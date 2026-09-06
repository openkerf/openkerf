/**
 * The sentence under the Bridges tick is true for the layer the shape is in.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/bridges-not-cut.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is burned and nothing is moved: three rectangles are drawn through
 * the API, clicked, and the panel is read.
 *
 * Why it exists. The panel keeps the Bridges field on a shape that is not cut — hiding it
 * would hide the reason with it — and then it has to say where it is true. It did not.
 * Measured on the baseline build at 1440 x 900, the line under the tick read "No bridges:
 * this shape comes loose the moment the cut closes" for all three of a rectangle in the
 * cut layer, a rectangle in an engrave layer and a rectangle in no layer at all, and with
 * two shapes selected it still said "this shape". Three of those four readings were
 * false. `bridgesCut` was consulted only when the shape already had bridges.
 *
 * What is checked, in English and in Dutch: a shape that is not in a cut layer never gets
 * the "comes loose" sentence, gets the "not in a cut layer" one instead, and a selection
 * of two says two.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';
import { en } from '../src/lib/i18n/en.ts';
import { nl } from '../src/lib/i18n/nl.ts';

// The same default as the rest of the server-backed tests, so without `OK_BASE` this
// skips instead of seeding a server another test is already seeding: with 8121 as the
// default it shared that server with `size-fields-honest.test.ts` in a whole-suite run,
// and one of the two language cases failed on a design the other had just replaced.
const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
/** The three rectangles: in the cut layer, in the engrave layer, in no layer. */
let shapes: string[] = [];
let bed = { width_mm: 1, height_mm: 1 };

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Three rectangles a bridge could sit on, one per state the sentence has to tell apart. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	await post('/api/design/operations', {
		type: 'cut',
		label: 'Outline',
		speed: 12,
		power_percent: 65
	});
	await post('/api/design/operations', {
		type: 'engrave',
		label: 'Caption',
		speed: 250,
		power_percent: 22
	});
	for (let i = 0; i < 3; i++)
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 100,
			y_mm: 20,
			width_mm: 60,
			height_mm: 40
		});
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const ops = design.operations.filter((o: { grid?: unknown }) => !o.grid);
	shapes = design.elements.map((e: { id: string }) => e.id);
	// Out of every layer first: the engine classifies a new shape by its colour, so
	// without this the third rectangle is not in no layer at all.
	for (const id of shapes)
		for (const op of ops) await post('/api/design/unassign', { ids: [id], operation_id: op.id });
	const cut = ops.find((o: { type: string }) => o.type === 'op cut');
	const engrave = ops.find((o: { type: string }) => o.type === 'op engrave');
	await post('/api/design/assign', { ids: [shapes[0]], operation_id: cut.id });
	await post('/api/design/assign', { ids: [shapes[1]], operation_id: engrave.id });

	const devices: { active: boolean; bed: { width_mm: number; height_mm: number } }[] = await (
		await fetch(`${BASE}/api/devices`)
	).json();
	bed = devices.find((d) => d.active)!.bed;
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


for (const [language, catalogue] of [
	['en', en],
	['nl', nl]
] as const) {
	test(`the panel does not promise a cut that is not there, in ${language}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
		await context.addInitScript(
			(lang: string) => localStorage.setItem('openkerf.language', lang),
			language
		);
		const page = await context.newPage();
		try {
			await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.bed svg', { timeout: 20000 });
			// Wait for the drawing, not for a guess about how long it takes.
			await page.waitForFunction(
				(n) => document.querySelectorAll('.bed svg path.hit').length >= n,
				shapes.length,
				{ timeout: 20000 }
			);
			// The alarm card of a machine that is not answering covers the top left of the
			// canvas, and every click below lands in it. It is what made this test flaky:
			// measured on this build, the three shapes are on screen at 147 ms but the card
			// only appears between 2.2 s and 2.7 s, so a fixed 1200 ms wait dismissed a card
			// that was not there yet and then clicked into it — five of sixteen language
			// cases over eight runs. So wait for the card and see it go, and only then click
			// a shape. `catch` for a server that does answer and never shows one.
			await page
				.locator('.alarm .seen')
				.first()
				.click({ timeout: 15000 })
				.then(() => page.locator('.alarm').waitFor({ state: 'detached', timeout: 5000 }))
				.catch(() => {});
			await page.getByRole('tab', { name: /Edit|Bewerken/ }).first().click();
			await page.waitForTimeout(400);
			const box = (await page.locator('.bed svg').boundingBox())!;
			const empty = {
				x: box.x + (box.width * 400) / bed.width_mm,
				y: box.y + (box.height * 250) / bed.height_mm
			};

			// A rectangle is an outline and not a surface, so the click lands on its top edge,
			// at the place in millimetres the shape was drawn at. Not on the `.hit` element
			// through Playwright: the canvas hit-tests the pointer's own coordinates against
			// the geometry (`Canvas.svelte:1245`), and measured, `getBoundingClientRect` of
			// the hit path reports a rectangle 170 px wide where 60 mm is 122 px here, so a
			// click aimed at the middle of that box selects nothing.
			const topEdge = (index: number) => ({
				x: box.x + (box.width * (50 + index * 100)) / bed.width_mm,
				y: box.y + (box.height * 20) / bed.height_mm
			});
			const clickEdge = async (index: number, shift = false) => {
				const at = topEdge(index);
				if (shift) await page.keyboard.down('Shift');
				await page.mouse.click(at.x, at.y);
				if (shift) await page.keyboard.up('Shift');
			};

			// What the action bar says about the selection. The panel block only exists once
			// something is selected, so a missed click has to fail as a missed click and not
			// as an empty sentence.
			const selected = (n: number) => {
				const count = catalogue['bar.selection.count'] as { one: string; other: string };
				return n === 1 ? count.one : count.other.replace('{n}', String(n));
			};
			const awaitSelection = async (n: number) => {
				const state = page.locator('.actionbar .state');
				try {
					await state.filter({ hasText: selected(n) }).first().waitFor({ timeout: 5000 });
				} catch {
					assert.fail(
						`clicking did not select ${n}: the action bar says "${await state.first().innerText()}"`
					);
				}
			};

			const read = async (index: number, extra?: number) => {
				await page.mouse.click(empty.x, empty.y);
				await page.waitForTimeout(300);
				await clickEdge(index);
				await awaitSelection(1);
				if (extra !== undefined) {
					await clickEdge(extra, true);
					await awaitSelection(2);
				}
				await page.waitForSelector('.bridges', { timeout: 5000 });
				return page.evaluate(
					() => document.querySelector('.bridges')?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
				);
			};

			const off = catalogue['panel.bridges.off'] as { one: string; other: string };
			const notCut = catalogue['panel.bridges.notCut'] as { one: string; other: string };
			// The half of the "comes loose" sentence that makes it a claim about a cut, in
			// whichever language: everything after the aside that says what a bridge is,
			// minus the connective ("so", "dus"). That is word for word what the baseline
			// said under all three shapes, so this assertion fails on the old build too.
			const loose = off.one.split('—').pop()!.trim().split(' ').slice(1).join(' ');

			const inCut = await read(0);
			assert.ok(inCut.includes(loose), `in a cut layer the panel says "${inCut}"`);

			for (const [what, index] of [
				['an engrave layer', 1],
				['no layer', 2]
			] as const) {
				const text = await read(index);
				assert.ok(
					!text.includes(loose),
					`in ${what} the panel still promises a cut: "${text}"`
				);
				assert.ok(
					text.includes(notCut.one),
					`in ${what} the panel does not say where bridges are true: "${text}"`
				);
			}

			const two = await read(1, 2);
			assert.ok(
				two.includes(notCut.other.replace('{n}', '2')),
				`two shapes selected, the panel says "${two}"`
			);
		} finally {
			await context.close();
		}
	});
}
