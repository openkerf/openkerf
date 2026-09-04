/**
 * The buttons at the foot of the pre-flight fit inside the panel, in every language.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/footer-fit.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed: the row is measured as it stands.
 *
 * Why it exists. The row held "Show frame" beside "Start job 0:17", the first not allowed
 * to break and the second given the rest — but the rest is not allowed to be narrower
 * than its own words either, and the panel clips what runs over. Measured with the panel
 * as it opens, at 1280 x 800, 1440 x 900 and 1920 x 1080 alike (the panel has one
 * width): the row is 221 px wide; its content needs 243 px in English and 264 px in Dutch.
 * So the start button ran 9 px past the panel in English, which nobody saw, and 30 px in
 * Dutch, which cut the time off the end of "Job starten" — the one number on that button.
 *
 * What is measured: every button in the row lies inside the panel's box, and the time
 * on the start button is on screen, in English and in Dutch. Dutch is the language with
 * the longest words the app has today; a third language with longer ones would join the
 * list here.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const SIZES: [number, number][] = [
	[1280, 800],
	[1440, 900],
	[1920, 1080]
];
const LANGUAGES = ['en', 'nl'];

let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** A design with four layers, so the pre-flight and its footer are there. */
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

for (const language of LANGUAGES) {
	for (const [width, height] of SIZES) {
		test(`the footer buttons fit the panel in ${language} at ${width} x ${height}`, async (t) => {
			if (!reachable || !browser) return noServer(t, BASE);
			const context = await browser.newContext({ viewport: { width, height } });
			await context.addInitScript(
				(lang: string) => localStorage.setItem('openkerf.language', lang),
				language
			);
			const page = await context.newPage();
			try {
				await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
				await page.waitForSelector('.pf-actions .btn.primary', { timeout: 20000 });
				await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
					timeout: 20000
				});
				// The estimate lands after the page: wait for the time on the button, not
				// for a guess about how long the estimate takes.
				await page.waitForSelector('.pf-actions .pf-start-time', { timeout: 20000 });
				await page.waitForTimeout(500);
				const measured = await page.evaluate(() => {
					const panel = document.querySelector('.preflight')!.getBoundingClientRect();
					const buttons = [...document.querySelectorAll('.pf-actions .btn')].map((node) => {
						const box = node.getBoundingClientRect();
						return {
							label: (node.textContent ?? '').trim(),
							over: Math.round(box.right - panel.right),
							under: Math.round(panel.left - box.left)
						};
					});
					const time = document.querySelector('.pf-actions .pf-start-time')!.getBoundingClientRect();
					return { buttons, timeOver: Math.round(time.right - panel.right) };
				});
				for (const button of measured.buttons) {
					assert.ok(
						button.over <= 0 && button.under <= 0,
						`"${button.label}" runs ${button.over} px past the panel's right edge`
					);
				}
				assert.ok(measured.timeOver <= 0, `the time on the start button is ${measured.timeOver} px off the panel`);
			} finally {
				await context.close();
			}
		});
	}
}
