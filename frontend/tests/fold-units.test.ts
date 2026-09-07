/**
 * In the compact fold the unit stays beside its number.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/fold-units.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Compact mode is switched on through the same localStorage key the toggle
 * writes, and the fold is opened by the one button that opens it; nothing else is
 * pressed.
 *
 * Why it exists. The three fields of a layer move into the fold in compact mode, and the
 * comment above them promises "same fields, same behaviour — just one line lower". They
 * did not behave the same: `.layer-edit label { display: grid }` (0,1,1) outranks
 * `.val { display: inline-flex }` (0,1,0), and the fold is the only place a `.val` is
 * also a `label` inside `.layer-edit`. So speed, power and passes each broke in two,
 * number over unit. Measured before the fix, on a cut layer with three passes: the unit
 * sat 2 px under its number on all three fields at 1440 x 900 and at 1024 x 768, and the
 * value block was 43.9 px tall on the desktop and 65.7 px on the tablet, against 25.9 and
 * 44.8 px for the same three fields in the roomy row.
 *
 * What is measured, per field and at both widths: the unit's box begins at or after the
 * number's right edge and starts above the number's bottom — beside it, on one line — and
 * the three fields together are no taller than one field's line.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const SIZES: [number, number][] = [
	[1440, 900],
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

/** Two layers, the first with passes, so all three fields carry a value. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers: [Record<string, unknown>, Record<string, unknown>][] = [
		[{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 }, { passes: 3 }],
		[{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 }, {}]
	];
	for (const [layer, rest] of layers) {
		const made = await (await post('/api/design/operations', layer)).json();
		const id = made?.id ?? made?.operation?.id;
		if (Object.keys(rest).length && id)
			await fetch(`${BASE}/api/design/operations/${id}`, {
				method: 'PATCH',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify(rest)
			});
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
	test(`the fold keeps every unit beside its number at ${width} x ${height}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width, height } });
		await context.addInitScript(() => localStorage.setItem('openkerf.lagen-compact', 'aan'));
		const page = await context.newPage();
		try {
			await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.layer.compact .vals .short', { timeout: 20000 });
			await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
				timeout: 20000
			});
			await page.waitForTimeout(400);
			// The one button that opens the fold — the same one the reader presses.
			await page.locator('.layer.compact .vals .short').first().click();
			await page.waitForSelector('.layer-edit .vals .val', { timeout: 20000 });
			await page.waitForTimeout(400);
			const measured = await page.evaluate(() => {
				const edit = document.querySelector('.layer-edit')!;
				const fields = [...edit.querySelectorAll('.vals .val')].map((field) => {
					const number = field.querySelector('input')!.getBoundingClientRect();
					const unit = field.querySelector('span')!.getBoundingClientRect();
					return {
						unit: (field.querySelector('span')!.textContent ?? '').trim(),
						gapLeft: Math.round((unit.left - number.right) * 10) / 10,
						dropBelow: Math.round((unit.top - number.bottom) * 10) / 10,
						lineHeight: Math.round(number.height * 10) / 10
					};
				});
				const block = edit.querySelector('.vals')!.getBoundingClientRect();
				return { fields, blockHeight: Math.round(block.height * 10) / 10 };
			});
			assert.equal(measured.fields.length, 3, 'expected speed, power and passes in the fold');
			for (const field of measured.fields) {
				assert.ok(
					field.gapLeft >= -1,
					`"${field.unit}" starts ${-field.gapLeft} px left of its own number's right edge`
				);
				assert.ok(
					field.dropBelow < 0,
					`"${field.unit}" sits ${field.dropBelow} px under its number instead of beside it`
				);
			}
			const line = Math.max(...measured.fields.map((f) => f.lineHeight));
			assert.ok(
				measured.blockHeight <= line + 8,
				`the three fields are ${measured.blockHeight} px tall, over the ${line} px of one line`
			);
		} finally {
			await context.close();
		}
	});
}
