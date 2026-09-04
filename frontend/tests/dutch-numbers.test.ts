/**
 * One screen, one way of writing a number.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/dutch-numbers.test.ts
 *
 * Skips itself without a reachable server.
 *
 * Measured with the app in Dutch and a layer at 3,5 mm/s: the colour strip under the
 * canvas wrote "3.5 mm/s" and the cut-path window "3,5 mm/s" — in one app, about one
 * layer. The status bar had the mouse position at "241.2, 108.4 mm" ten pixels from a
 * top bar saying "3,5mm". Every one of those came from a template string or a
 * `toFixed()` that went round `Intl`.
 *
 * `CLAUDE.md` puts the reason in one line: 3,5 mm against 3.5 mm is the difference
 * between two values to somebody at a laser. So this walks the surfaces that carry
 * measurements and refuses a decimal point in Dutch.
 *
 * Deliberately not the whole page: a version number, a URL and an id are not
 * measurements, and the canvas draws its own coordinates in an SVG that has nothing to
 * do with the reader's language.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** The surfaces that show a measurement, by the class the component gives them. */
const SURFACES = ['.statusbar', '.palette', '.sheets'];

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	await post('/api/project/new');
	// A layer whose speed has a decimal: with a whole number there is nothing to see.
	await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 });
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const layer = design.operations.find((o: { element_ids: string[] }) => o.element_ids.length);
	if (layer) {
		await fetch(`${BASE}/api/design/operations/${layer.id}`, {
			method: 'PATCH',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ speed: 3.5 })
		});
	}
	browser = await chromium.launch();
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	// The language is a stored choice; setting it before the first paint means the app
	// never renders in English first.
	await context.addInitScript(() => localStorage.setItem('openkerf.language', 'nl'));
	page = await context.newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
});

after(async () => {
	await browser?.close();
});

test('in Dutch no measurement on screen is written with a full stop', async (t) => {
	if (!reachable) return noServer(t, BASE);

	const offenders = await page.evaluate((surfaces) => {
		const found: string[] = [];
		for (const surface of surfaces) {
			for (const root of document.querySelectorAll(surface)) {
				const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
				let node: Node | null;
				while ((node = walker.nextNode())) {
					const text = (node.textContent ?? '').trim();
					// A decimal point between two digits. A thousands separator in Dutch is
					// a full stop as well, but that is three digits after it.
					if (/\d\.\d(?!\d\d)/.test(text)) found.push(`${surface}: ${text.slice(0, 40)}`);
				}
			}
		}
		return found;
	}, SURFACES);

	assert.deepEqual(
		offenders,
		[],
		`a number went round Intl: ${offenders.join(' | ')}`
	);
});
