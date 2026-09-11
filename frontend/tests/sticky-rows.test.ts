/**
 * The two sticky button rows end where the body they scroll in ends.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/sticky-rows.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed that reaches the machine: both windows are opened,
 * measured and closed with Escape.
 *
 * Why it exists. Two windows carry a row that stays in view while the form under it
 * scrolls, and they did it two ways. Measured at 1440 x 900 with the form filled to
 * 1,647 px in a body of 665: the test grid's row stopped at 793 while its body ended at
 * 809 — a 16 px slit, the body's own padding, in which the form went on scrolling under
 * an opaque row, and the field above it was 19.3 px behind that row. The series' row,
 * with `bottom: calc(-1 * var(--space-4))`, ended exactly at its body's bottom. So the
 * test grid gets the same rule, and this test holds both to it.
 *
 * What is measured: with the body scrolled to the top, the row's bottom edge and the
 * body's bottom edge are the same line, in both windows.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8126';

let reachable = false;
let browser: Browser | null = null;

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

/**
 * The row's bottom against the bottom of the body it scrolls in.
 *
 * The body is found by walking up from the row rather than by a selector on the
 * dialog: Svelte hangs a hash on every class, and the row sits two components deep
 * inside the window it belongs to.
 */
const measure = (rowSelector: string) => {
	const dialog = document.querySelector('[role="dialog"]');
	if (!dialog) return null;
	const row = dialog.querySelector(rowSelector);
	if (!row) return null;
	let body: Element | null = row.parentElement;
	while (body && !body.classList.contains('body')) body = body.parentElement;
	if (!body) return null;
	body.scrollTop = 0;
	const rowBox = row.getBoundingClientRect();
	const bodyBox = body.getBoundingClientRect();
	return {
		rowBottom: Math.round(rowBox.bottom * 10) / 10,
		bodyBottom: Math.round(bodyBox.bottom * 10) / 10,
		slit: Math.round((bodyBox.bottom - rowBox.bottom) * 10) / 10,
		scrollHeight: body.scrollHeight,
		clientHeight: body.clientHeight
	};
};

type Seen = ReturnType<typeof measure>;

async function inWindow(tool: string, rowSelector: string, prepare?: (page: import('playwright').Page) => Promise<void>): Promise<Seen> {
	const context = await browser!.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
		await page.locator(`.rail button.tool[title${tool}]`).click();
		await page.waitForSelector('[role="dialog"]', { timeout: 20000 });
		if (prepare) await prepare(page);
		// The preview is debounced and then comes back from the server; the row's place
		// only settles once the form under it has its full height.
		await page.waitForTimeout(2500);
		return await page.evaluate(measure, rowSelector);
	} finally {
		await context.close();
	}
}

test('the test grid’s sticky row reaches the bottom of its body', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const seen = await inWindow('="Test grid"', '.actions', async (page) => {
		// Picking a material is what turns the empty form into a plan, and the plan is
		// what makes the body long enough to scroll at all.
		const material = page.locator('[role="dialog"] label:has(span:text-is("Material")) select').first();
		const values = await material
			.locator('option')
			.evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value).filter((v) => v && v !== 'null'));
		if (values.length) await material.selectOption(values[0]);
	});
	assert.ok(seen, 'no sticky row found in the test grid window');
	assert.ok(
		seen.scrollHeight > seen.clientHeight,
		`the body does not scroll (${seen.scrollHeight} in ${seen.clientHeight}), so the row was not measured where it sticks`
	);
	assert.equal(
		seen.slit,
		0,
		`the row ends ${seen.slit} px above the body it scrolls in (row ${seen.rowBottom}, body ${seen.bodyBottom})`
	);
});

test('the series’ sticky row reaches the bottom of its body', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const seen = await inWindow('^="Series"', '.knoppen');
	assert.ok(seen, 'no sticky row found in the series window');
	assert.equal(
		seen.slit,
		0,
		`the row ends ${seen.slit} px above the body it scrolls in (row ${seen.rowBottom}, body ${seen.bodyBottom})`
	);
});
