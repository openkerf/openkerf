/**
 * "Send to the machine" is where a hand can reach it.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/upload-reach.test.ts
 *
 * Skips itself without a reachable server. It never starts a job and never sends one:
 * the fold is opened and looked at, nothing is pressed inside it.
 *
 * Why it exists. The fold sat in the column just above the sticky footer, which is the
 * one place in that column where a control cannot be seen: the footer floats up over
 * whatever is last in the flow as soon as the column is longer than the panel is high.
 * Measured at 1440 x 900 with the panel as it opens — the fold at y=738 with the
 * footer's top at y=705, `elementFromPoint` in the middle of the summary answering `LI`,
 * a line of the checklist, and a real mouse click on those coordinates leaving
 * `details.open` false. At 1280 x 800 the same click landed on `DIV.pf-actions`; only at
 * 1920 x 1080 did it answer `SUMMARY` and open. Scrolling reached it — the summary is on
 * top from 60 px of scroll onwards, over 600 of the 763 px the panel scrolls — but a
 * control nobody can see at rest is a control nobody scrolls for, and the route behind it
 * then has a caller that does not exist for the user.
 *
 * **`locator.click()` cannot measure this**, and that is why nothing saw it: Playwright
 * scrolls the element into view before clicking, so it clicks a control under a sticky
 * footer perfectly happily. The click here is `page.mouse.click` on the coordinates the
 * summary actually occupies — the same thing a hand does.
 *
 * What this pins is the property and not the place: at every size this project measures,
 * the summary of the fold is the topmost thing at its own middle, a real click opens it,
 * and the button that burns is still reachable beside it.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

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
		test(`the fold can be opened by a hand at ${width} x ${height}, ${state}`, async (t) => {
			if (!reachable) return t.skip(`no server on ${BASE}`);
			await aLongColumn(withRaster);
			await page.setViewportSize({ width, height });
			await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
			await page.waitForTimeout(3000);

			const summary = await whatIsOnTop('details.pf-upload > summary');
			assert.ok(summary, 'there is no "Send to the machine" fold on the Job tab');
			assert.ok(summary.onScreen, 'the fold is not on screen without scrolling');
			assert.ok(summary.self, `the fold lies behind ${summary.over}`);

			// A hand, not a helper: `locator.click()` would scroll it into view first and
			// report success over a control nobody can reach.
			await page.mouse.click(summary.at.x, summary.at.y);
			await page.waitForTimeout(400);
			assert.equal(
				await page.evaluate(
					() => (document.querySelector('details.pf-upload') as HTMLDetailsElement | null)?.open ?? null
				),
				true,
				'a click on the middle of the summary did not open the fold'
			);

			// And the name field inside it is reachable too, not just the summary.
			const field = await whatIsOnTop('details.pf-upload input');
			assert.ok(field?.self, `the name field lies behind ${field?.over}`);

			// The fold may not have pushed the button that burns out of reach: it shares
			// the footer with it, and a footer that grows takes the primary action with it.
			const start = await page.evaluate(() => {
				const button = [...document.querySelectorAll('.pf-actions button')].find((b) =>
					/Start job/.test(b.textContent ?? '')
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
	}
}
