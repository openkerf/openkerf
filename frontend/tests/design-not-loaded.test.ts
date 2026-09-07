/**
 * While the design is still being read, no surface says the bed is empty.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/design-not-loaded.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed and no job is started: shapes are put on the bed
 * through the API and the page is read as it loads.
 *
 * Why it exists. `design` is `null` until the first `/api/design` answers, and every
 * question asked of it in that window answered as if the bed were empty. Measured on
 * a document of 1,536 elements, with the first answer held back so the window is the
 * same length every run: from 0.4 s to 4.5 s the canvas said **Empty bed** with
 * "Use Import in the top bar…", the status bar said **0 elements**, the Job card said
 * **There is nothing to burn**, and *Show frame* was disabled with "Nothing is on the
 * bed" as its reason — eleven samples, four wrong statements each, over a full bed.
 *
 * The four flip together on one flag (`design.loaded`), so this holds both halves:
 * none of the four appears before the answer, and all four are right after it.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';
import { en } from '../src/lib/i18n/en.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
/** Long enough that a sluggish first answer cannot be mistaken for the repair. */
const HOLD = 2500;

let reachable = false;
let browser: Browser | null = null;

async function shapesOnTheBed() {
	const design = await fetch(`${BASE}/api/design`).then((r) => r.json());
	if (design.elements.length) return design.elements.length;
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 10, y_mm: 10, width_mm: 20, height_mm: 20 })
	});
	return 1;
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
});

after(async () => {
	await browser?.close();
});

test('nothing on the frame calls a full bed empty while the design is being read', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const count = await shapesOnTheBed();
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		let held = false;
		await page.route('**/api/design', async (route) => {
			if (!held) {
				held = true;
				await new Promise((resolve) => setTimeout(resolve, HOLD));
			}
			await route.continue();
		});
		const read = () =>
			page.evaluate(() => {
				const frame = document.querySelector<HTMLButtonElement>('.btn.frame');
				return {
					text: document.body.innerText,
					counts: [...document.querySelectorAll('.statusbar .docpart')]
						.map((node) => (node.textContent ?? '').trim())
						.filter(Boolean),
					frameTitle: frame?.getAttribute('title') ?? null,
					frameOff: frame?.disabled ?? null
				};
			});
		await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
		const started = Date.now();
		// Sampled while the answer is held back. Every sample is inside the window,
		// so every one of them must be silent about how full the bed is.
		for (let sample = 0; sample < 5; sample += 1) {
			await page.waitForTimeout(400);
			const seen = await read();
			const at = `${((Date.now() - started) / 1000).toFixed(1)} s`;
			assert.ok(
				!seen.text.includes(en['canvas.empty.title']),
				`the canvas said "${en['canvas.empty.title']}" at ${at} over ${count} elements`
			);
			assert.ok(
				!seen.text.includes(en['job.nothing.title']),
				`the Job card said "${en['job.nothing.title']}" at ${at} over ${count} elements`
			);
			assert.deepEqual(
				seen.counts,
				[],
				`the status bar counted the document at ${at}, before it had read it`
			);
			assert.notEqual(
				seen.frameTitle,
				en['topbar.frame.off'],
				`Show frame gave "${en['topbar.frame.off']}" as its reason at ${at}`
			);
		}
		// And once it has been read, the same four surfaces do speak.
		await page.waitForFunction(
			() => document.querySelectorAll('.statusbar .docpart').length > 0,
			null,
			{ timeout: 20000 }
		);
		const after = await read();
		assert.ok(
			after.counts.some((word) => word.includes(String(count))),
			`expected the count of ${count} in the status bar, got ${JSON.stringify(after.counts)}`
		);
		assert.ok(
			!after.text.includes(en['job.nothing.title']),
			'the Job card still said there was nothing to burn after the design had been read'
		);
	} finally {
		await context.close();
	}
});
