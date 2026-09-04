/**
 * "Send to the machine" is where a hand can reach it, over the whole scroll.
 *
 * It used to be a fold in the footer; it is now the arrow beside the start button, which
 * opens a menu with that one line in it, and the line opens the window with the name
 * field. What is measured is the arrow: that it lies on top at its own middle at every
 * scroll offset, and that a real click on it opens the menu — and, at rest, that the
 * menu's line opens the window.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/upload-reach.test.ts
 *
 * Skips itself without a reachable server. It never starts a job and never sends one:
 * the fold is opened and looked at, nothing is pressed inside it.
 *
 * That skip is the weak point and it is worth naming: this is the guard that caught
 * the worst mistake of this round — a control a hand could not reach — and by default
 * it is off, because by default there is no server. A skip is at least visible in the
 * output where a green tick would not be. To make it enforceable, set
 * `OK_REQUIRE_SERVER=1`: an unreachable server is then a failure rather than a skip,
 * which is what a run that claims to have checked this should use. That switch lives
 * in `no-server.ts` now, and every server-backed test in this directory goes through
 * it — this file is where the shape was tried before it was spread.
 *
 * Why it exists. The fold sat in the column just above the sticky footer, which is the
 * one place in that column where a control cannot be seen: the footer floats up over
 * whatever is last in the flow as soon as the column is longer than the panel is high.
 * Measured at 1440 x 900 with the panel as it opens — the fold at y=738 with the
 * footer's top at y=705, `elementFromPoint` in the middle of the summary answering `LI`,
 * a line of the checklist, and a real mouse click on those coordinates leaving
 * `details.open` false. At 1280 x 800 the same click landed on `DIV.pf-actions`; only at
 * 1920 x 1080 did it answer `SUMMARY` and open.
 *
 * The footer is `position: sticky`, so it is bounded by its own containing block,
 * `.preflight`, and it travels with that block once the block leaves the bottom of the
 * scrollport. Measured on the layout as it stands, `.preflight`'s bottom against the
 * footer's top and the summary's own y:
 *
 *   1440 x 900, with a raster layer (range 750)   without one (range 728)
 *     scrollTop   0: bottom 925, strip 681, summary 694   903 / 681 / 694
 *     halfway     : bottom 550, strip 363, summary 376   539 / 352 / 365
 *     scrollTop max: bottom 175, strip -12, summary   1   175 / -12 /   1
 *   1280 x 800, with a raster layer (range 850)   without one (range 828)
 *     scrollTop   0: bottom 925, strip 581, summary 594   903 / 581 / 594
 *     halfway     : bottom 500, strip 313, summary 326   489 / 302 / 315
 *     scrollTop max: bottom  75, strip -112, summary -99    75 / -112 / -99
 *
 * At the end of the range the pre-flight has scrolled off the top and takes the footer
 * with it — the summary is above the scrollport, not behind anything, which is what all
 * of that card does and what the sections below it are for. What matters is the rest:
 * over the whole range, at both sizes and in both states, the summary is the topmost
 * thing at its own middle at **every** offset where it lies inside the scrollport. That
 * is what the second test below measures, offset by offset, and it is the property the
 * first one only checks at rest.
 *
 * **`locator.click()` cannot measure any of this**, and that is why nothing saw it:
 * Playwright scrolls the element into view before clicking, so it clicks a control under
 * a sticky footer perfectly happily. The click here is `page.mouse.click` on the
 * coordinates the summary actually occupies — the same thing a hand does.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

/** The sizes this project measures at; 1440 x 900 is the one the design system uses. */
const SIZES: [number, number][] = [
	[1280, 800],
	[1440, 900],
	[1920, 1080]
];

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/**
 * A design that makes the pre-flight column long, with or without a raster layer.
 *
 * Both, because the two states put the fold in different places: a raster layer adds
 * the "produces nothing headless" warning to the footer, which makes the footer taller
 * and the column shorter, and without it the fold sat 97 px lower — measured at
 * 1440 x 900 on the layout before this, footer 219 px tall with the raster layer and
 * 167 px without, the fold at 694 and at 791. The state that buries a control is the
 * one nobody seeds on purpose, so it is seeded here on purpose.
 */
async function aLongColumn(withRaster: boolean) {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers = [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 },
		withRaster
			? { type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
			: { type: 'cut', label: 'Tabs', speed: 15, power_percent: 60 }
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
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
});

after(async () => {
	await browser?.close();
});

/** The box a control really occupies, and what answers at the middle of it. */
async function whatIsOnTop(selector: string) {
	return page.evaluate((selector) => {
		const node = document.querySelector(selector);
		if (!node) return null;
		const box = node.getBoundingClientRect();
		const at = { x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2) };
		const hit = document.elementFromPoint(at.x, at.y);
		return {
			at,
			onScreen: box.top >= 0 && box.bottom <= window.innerHeight,
			self: hit === node || node.contains(hit),
			over: hit ? `${hit.tagName}.${typeof hit.className === 'string' ? hit.className.split(' ')[0] : ''}` : null
		};
	}, selector);
}

for (const withRaster of [true, false]) {
	for (const [width, height] of SIZES) {
		const state = withRaster ? 'with a raster layer' : 'without one';
		test(`at rest the arrow can be pressed by a hand at ${width} x ${height}, ${state}`, async (t) => {
			if (!reachable) return noServer(t, BASE);
			await aLongColumn(withRaster);
			await page.setViewportSize({ width, height });
			await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
			await page.waitForTimeout(3000);

			const summary = await whatIsOnTop('.pf-actions button.pf-more');
			assert.ok(summary, 'there is no arrow beside the start button on the Job tab');
			assert.ok(summary.onScreen, 'the arrow is not on screen without scrolling');
			assert.ok(summary.self, `the arrow lies behind ${summary.over}`);

			// A hand, not a helper: `locator.click()` would scroll it into view first and
			// report success over a control nobody can reach.
			await page.mouse.click(summary.at.x, summary.at.y);
			await page.waitForTimeout(400);
			// The menu is on top and its one line is there.
			const row = await whatIsOnTop('.pf-menu [role="menuitem"]');
			assert.ok(row, 'a click on the middle of the arrow did not open the menu');
			assert.ok(row.self, `the menu's line lies behind ${row.over}`);

			// Whether the line can be pressed is the machine's to say, and this test does
			// not choose the machine: a test that switches the active device would do it
			// on whatever server it is pointed at. So it asks, the way the handbook's
			// picture script does, and checks the promise that goes with the answer — a
			// Ruida opens the window; anything else keeps the line grey and says why.
			// The same route the interface reads, so the test and the button cannot drift.
			const capabilities = await (await fetch(`${BASE}/api/capabilities`)).json();
			const keepsFiles = capabilities?.actions?.upload === true;
			const line = await page.evaluate(() => {
				const node = document.querySelector('.pf-menu [role="menuitem"]') as HTMLButtonElement;
				return { disabled: node.disabled, title: node.title };
			});
			if (!keepsFiles) {
				assert.ok(line.disabled, 'the machine keeps no files, but the line is not greyed out');
				assert.ok(line.title.length > 0, 'the greyed-out line gives no reason');
				await page.keyboard.press('Escape');
				return;
			}
			assert.ok(!line.disabled, `the machine keeps files, but the line is greyed out: ${line.title}`);
			await page.mouse.click(row.at.x, row.at.y);
			await page.waitForTimeout(400);

			// And the window with the name field is there, the field reachable and filled
			// with the name of the sheet.
			const field = await whatIsOnTop('[role="dialog"] input.mono');
			assert.ok(field, 'the menu line did not open the window with the name field');
			assert.ok(field.self, `the name field lies behind ${field.over}`);
			assert.notEqual(
				await page.evaluate(() => (document.querySelector('[role="dialog"] input.mono') as HTMLInputElement).value),
				'',
				'the name field opens empty'
			);
			await page.keyboard.press('Escape');
			await page.waitForTimeout(300);
			assert.equal(
				await page.evaluate(() => document.querySelector('[role="dialog"]') !== null),
				false,
				'Escape did not close the window'
			);

			// The arrow may not have pushed the button that burns out of reach: it shares
			// the footer with it.
			const start = await page.evaluate(() => {
				const button = [...document.querySelectorAll('.pf-actions button')].find((b) =>
					/Start job|Job starten/.test(b.textContent ?? '')
				);
				if (!button) return null;
				const box = button.getBoundingClientRect();
				const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
				return {
					onScreen: box.top >= 0 && box.bottom <= window.innerHeight,
					self: hit === button || button.contains(hit)
				};
			});
			assert.ok(start?.onScreen && start.self, 'the start button is no longer reachable beside the fold');
		});

		test(`and stays reachable all the way down at ${width} x ${height}, ${state}`, async (t) => {
			if (!reachable) return noServer(t, BASE);
			await aLongColumn(withRaster);
			await page.setViewportSize({ width, height });
			await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
			await page.waitForTimeout(3000);

			// One scroll position is one measurement, and the position that matters is not
			// always the one the panel opens at: what buries a control here is a footer
			// that moves. So the whole range, ten pixels at a time — and only where the
			// summary is inside the scrollport, because above or below it the answer is
			// "you have scrolled past it", which is true of every row in the panel.
			const covered = await page.evaluate(async () => {
				const column = document.querySelector('.preflight');
				let scroller: HTMLElement | null = null;
				for (let el = column?.parentElement as HTMLElement | null; el; el = el.parentElement)
					if (el.scrollHeight > el.clientHeight + 4) { scroller = el; break; }
				if (!scroller || !column) return ['no scrolling column'];
				const found: string[] = [];
				const max = scroller.scrollHeight - scroller.clientHeight;
				for (let top = 0; top <= max; top += 10) {
					scroller.scrollTop = top;
					await new Promise((r) => requestAnimationFrame(r));
					const summary = document.querySelector('.pf-actions button.pf-more');
					if (!summary) return ['the arrow is gone'];
					const box = summary.getBoundingClientRect();
					const port = scroller.getBoundingClientRect();
					if (box.top < port.top || box.bottom > port.bottom) continue;
					const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
					if (hit !== summary && !summary.contains(hit))
						found.push(`${top}: ${hit ? hit.tagName + '.' + String(hit.className).split(' ')[0] : 'nothing'}`);
				}
				scroller.scrollTop = 0;
				return found;
			});
			assert.deepEqual(
				covered,
				[],
				`the fold is behind something at these scroll offsets: ${covered.slice(0, 8).join(', ')}`
			);
		});
	}
}
