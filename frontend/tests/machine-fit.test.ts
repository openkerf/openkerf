/**
 * The machine controls fit the Job panel, print and cut included, in every language.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8092 node --test frontend/tests/machine-fit.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed but the fold's own summary; the alignment is answered in
 * the browser, as handbook shot 34 answers it, because the real one needs a head driven
 * over two marks.
 *
 * Why it exists. The print-and-cut summary carried the whole sentence "mark 1 has moved
 * that far, and the sheet lies 0.3° out" in a badge that may not wrap: 311 px. The
 * machine controls are one grid column sized to its widest child, so the whole block —
 * jog pad, step sizes, Hold, the zero point, "Forget the alignment" — came out 385 px
 * wide in a panel of 359, at 1280, 1440 and 1920 px alike, and the panel clips what runs
 * over. Measured: every right edge in the block 26 px past the panel's.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8092';
const SIZES: [number, number][] = [
	[1280, 800],
	[1440, 900],
	[1920, 1080]
];
const LANGUAGES = ['en', 'nl'];

let reachable = false;
let browser: Browser | null = null;
let marks: string[] = [];

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
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const [cx, cy] of [
		[30, 30],
		[260, 40]
	]) {
		const made = await (
			await post('/api/design/elements', { type: 'circle', cx_mm: cx, cy_mm: cy, r_mm: 3 })
		).json();
		marks.push(made.ids[0]);
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	browser = await chromium.launch();
});

after(async () => {
	await browser?.close();
});

for (const language of LANGUAGES) {
	for (const [width, height] of SIZES) {
		test(`the machine controls fit the panel in ${language} at ${width} x ${height}`, async (t) => {
			if (!reachable || !browser) return noServer(t, BASE);
			const context = await browser.newContext({ viewport: { width, height } });
			await context.addInitScript(
				(lang: string) => localStorage.setItem('openkerf.language', lang),
				language
			);
			const page = await context.newPage();
			await page.route('**/api/printcut', (route) =>
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({
						marks: [
							{ id: marks[0], drawn: { x_mm: 30, y_mm: 30 }, measured: { x_mm: 32.5, y_mm: 31.2 } },
							{ id: marks[1], drawn: { x_mm: 260, y_mm: 40 }, measured: { x_mm: 262.5, y_mm: 42.4 } }
						],
						offset_mm: { x_mm: 2.5, y_mm: 1.2 },
						aligned: true,
						angle_deg: 0.3,
						dx_mm: 2.5,
						dy_mm: 1.2,
						distance_error_mm: 0.01,
						tolerance_mm: 2,
						max_angle_deg: 3,
						lapsed: null
					})
				})
			);
			try {
				await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
				await page.waitForSelector('.machinevouw > summary', { timeout: 20000 });
				await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
					timeout: 20000
				});
				await page.locator('.machinevouw > summary').click();
				// The alignment arrives after the page: wait for the block it opens, not
				// for a guess about how long that takes.
				await page.waitForSelector('details.printcut[open] .originPoint', { timeout: 20000 });
				await page.waitForTimeout(300);
				const over = await page.evaluate(() => {
					const fold = document.querySelector('.machinevouw')!;
					const scroller = fold.closest('.panel-scroll') as HTMLElement;
					const edge =
						scroller.getBoundingClientRect().right -
						parseFloat(getComputedStyle(scroller).paddingRight || '0');
					const out = [...fold.querySelectorAll('button, summary, p, .badge')]
						.map((node) => ({
							what: (node as HTMLElement).innerText.trim().replace(/\s+/g, ' ').slice(0, 40),
							over: Math.round(node.getBoundingClientRect().right - edge)
						}))
						.filter((row) => row.over > 0);
					return { out, scrolls: scroller.scrollWidth - scroller.clientWidth };
				});
				assert.deepEqual(over.out, [], 'these run past the panel: ' + JSON.stringify(over.out));
				assert.equal(over.scrolls, 0, `the panel is ${over.scrolls} px wider than it shows`);
			} finally {
				await context.close();
			}
		});
	}
}
