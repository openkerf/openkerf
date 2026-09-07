/**
 * Every row of the compact layer list shows its name.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/compact-layer-names.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed: compact mode is switched on through the same
 * localStorage key the toggle writes, and the rows are measured as they open.
 *
 * Why it exists. The compact rule read `.layer.compact .out, .layer.compact .ident
 * { flex: 1 1 12ch }`, and a `.layer.compact .out` outweighs the `flex: none` on `.out`
 * itself — so the burn switch took the room meant for the name, in both directions.
 * Measured on the five layers below before the fix: at 1440 x 900 the switch ran 45.2 to
 * 114.3 px wide where the roomy list gives it 28, and at 1024 x 768, where every target
 * has to be 44 px for a finger, it was squeezed to between 105 and 2 px — two pixels, on
 * the row with passes. The name was 0 px wide on nine of the ten rows and 20.7 px, one
 * letter and an ellipsis, on the tenth. The comment above the rule promised the name
 * "may be truncated"; the screen removed it, so the one mode in which a long list fits
 * was a list of anonymous coloured numbers.
 *
 * The floor is paid for by a wrap. At 1440 that is the deal: three of these five rows put
 * their value line underneath (57.9 to 60.8 px against 38 for the other two) and get the
 * whole name for it, 104 px instead of the floor. At the tablet width the same wrap costs
 * a second 44 px touch line and the mode stops being a mode: measured before the tablet
 * rules, four of the five rows were 102 px tall and the five together 462 px against
 * 579.8 for the roomy list — a fifth saved, with a compact row taller than a roomy row at
 * 1440 (75.9 px). There the value string is cut instead, and that is what the height
 * assertion below pins: at 1024 every row whose value line is numbers only is one line
 * high (54 px; the five together 317.5 px, 45 % under roomy). The row that does not burn
 * carries a word beside its numbers and keeps its second line, 101.5 px.
 *
 * What is measured, per row and at both widths: the name is at least as wide as its 5ch
 * floor (measured after the fix: a 39 px floor at 1440, where the names are 47.2, 40.6
 * and three times 104, so none stands on it; a 45 px floor at 1024, where four of the
 * five sit exactly on it and only Outline, 49.6, is whole), the
 * burn switch is exactly the width the roomy list gives it (28 px with a mouse, 44 px at
 * the tablet width), and the ⋯ does not paint over the values. That last one is what a
 * first fix got wrong: with the switch back at 28 px but no floor under the name, the
 * identity block still shrank under its own contents and the ⋯ ran 3 px into the values
 * on the row whose numbers are widest. And at the tablet width: the height above.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
/**
 * Viewport, the switch width the media query at the foot of the panel gives it, and
 * whether a row of numbers has to stay on one line at that width.
 */
const SIZES: [number, number, number, boolean][] = [
	[1440, 900, 28, false],
	[1024, 768, 44, true]
];

let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/**
 * Five named layers, and the three rows that leave the name least room are all in it:
 * one at 1000 mm/s (the widest speed), one that does not burn and one with passes — the
 * last two carry a fourth item in the value line and are the rows the gauntlet's own
 * screenshot shows at their worst.
 *
 * `output` and `passes` go on with a PATCH: `POST /api/design/operations` reads only
 * type, label, speed and power from the body and drops the rest silently, so seeding
 * them in the create call measures the easy rows and calls it a pass.
 */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers: [Record<string, unknown>, Record<string, unknown>][] = [
		[{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 }, {}],
		[{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 }, {}],
		[{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 }, { output: false }],
		[{ type: 'raster', label: 'Logo area', speed: 1000, power_percent: 30 }, {}],
		[{ type: 'cut', label: 'Inner cuts', speed: 12, power_percent: 65 }, { passes: 3 }]
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

for (const [width, height, switchWidth, oneLine] of SIZES) {
	test(`every compact layer row shows its name at ${width} x ${height}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width, height } });
		await context.addInitScript(() => localStorage.setItem('openkerf.lagen-compact', 'aan'));
		const page = await context.newPage();
		try {
			await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
			// `attached`, not visible: a 0 px name — the very thing measured here — is not visible.
			await page.waitForSelector('.layer.compact .layer-name', {
				state: 'attached',
				timeout: 20000
			});
			await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
				timeout: 20000
			});
			await page.waitForTimeout(500);
			const rows = await page.evaluate(() =>
				[...document.querySelectorAll('.layer.compact')].map((row) => {
					const name = row.querySelector('.layer-name') as HTMLElement;
					const out = row.querySelector('.out') as HTMLElement | null;
					const more = row.querySelector('.more') as HTMLElement | null;
					const vals = row.querySelector('.vals') as HTMLElement | null;
					// The floor in the name's own font, measured rather than derived from the size.
					const probe = document.createElement('span');
					probe.style.cssText = 'position:absolute;visibility:hidden;width:5ch;display:block';
					name.appendChild(probe);
					const floor = Math.floor(probe.getBoundingClientRect().width);
					probe.remove();
					// A value line of numbers only, or one that also carries a word ("does
					// not burn", "hidden", air assist): the second may keep a line of its
					// own, the first may not.
					const words = row.querySelectorAll('.vals .tag, .vals .pill').length;
					// One line of this row: the tallest thing in it that cannot wrap,
					// plus the row's own padding and border.
					const box = getComputedStyle(row);
					const unwrappable = [
						...row.querySelectorAll('.chip, .layer-name, .out, .more, .short')
					].map((e) => e.getBoundingClientRect().height);
					const oneLineHeight =
						Math.max(...unwrappable) +
						parseFloat(box.paddingTop) +
						parseFloat(box.paddingBottom) +
						parseFloat(box.borderTopWidth) +
						parseFloat(box.borderBottomWidth);
					return {
						label: (name.textContent ?? '').trim(),
						words,
						oneLine: Math.round(oneLineHeight * 10) / 10,
						height: Math.round(row.getBoundingClientRect().height * 10) / 10,
						nameWidth: Math.round(name.getBoundingClientRect().width * 10) / 10,
						floor,
						outWidth: out ? Math.round(out.getBoundingClientRect().width * 10) / 10 : null,
						// How far the ⋯ reaches into the values, and only when the two share a
						// line: -1 once the values have wrapped underneath.
						overlap:
							more && vals && more.getBoundingClientRect().bottom > vals.getBoundingClientRect().top
								? Math.round(more.getBoundingClientRect().right - vals.getBoundingClientRect().left)
								: -1
					};
				})
			);
			assert.ok(rows.length >= 5, `expected the five seeded rows, got ${rows.length}`);
			for (const row of rows) {
				assert.ok(
					row.nameWidth >= row.floor,
					`"${row.label}" has ${row.nameWidth} px for its name, under the ${row.floor} px of 5ch`
				);
				assert.equal(
					row.outWidth,
					switchWidth,
					`the burn switch on "${row.label}" is ${row.outWidth} px wide, not ${switchWidth}`
				);
				assert.ok(
					row.overlap <= 0,
					`on "${row.label}" the ⋯ runs ${row.overlap} px into the values`
				);
			}
			if (oneLine) {
				// What one line is, taken from the things in the row that cannot wrap —
				// chip, name, switch, ⋯ and the value button, all `white-space: nowrap`
				// — plus the row's own padding and border. Not the shortest row in the
				// list: a change that wrapped every numbers-only row would make that
				// minimum the wrapped height, and the assertion would pass on exactly
				// the bug it exists to catch. Derived rather than named, so the
				// assertion survives a move in the type scale (measured: 54 px at 1024,
				// 38 at 1440).
				for (const row of rows) {
					if (row.words) continue;
					assert.equal(
						row.height,
						row.oneLine,
						`"${row.label}" is ${row.height} px tall where one line of it is ${row.oneLine}: its values wrapped underneath`
					);
				}
			}
		} finally {
			await context.close();
		}
	});
}
