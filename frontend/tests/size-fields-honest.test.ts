/**
 * The W/H/X/Y and angle fields never show a number the shape does not have.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/size-fields-honest.test.ts
 *
 * One engine is shared with the other e2e tests, so use `--test-concurrency=1`.
 * Without a reachable server the file skips itself. Nothing is burned and the head is
 * never moved: only the panel is typed into.
 *
 * Why it exists. Two ways the panel came to disagree with the design, both measured on
 * the gauntlet's seeded bed at 1440 x 900:
 *
 *  - A locked shape's five number fields carried no `disabled` at all, while the bridges
 *    checkbox eight rows below was disabled with "This shape is locked". Typing 50 into W
 *    on a 60.0 mm ellipse gave a red toast ("This shape is locked, so it was not
 *    resized") and left **50** standing in the field over a shape that is 60.0.
 *  - Typing 0 into W of a 120.0 x 80.0 mm rectangle: `commitSize` returned on `value <= 0`
 *    without a request, without a sentence and without touching the field, so the box kept
 *    **0** while the canvas label under the shape read 120.0 x 80.0 mm.
 *
 * What is measured: with a locked shape selected all five fields are disabled and say
 * why, and a refused width puts the shape's own width back in the box with one sentence
 * beside it.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8121';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

const design = async () => (await fetch(`${BASE}/api/design`)).json();

/** The first element's size in millimetres, straight from the API. */
async function sizeMm() {
	const snapshot = await design();
	const perMm = snapshot.units_per_mm as number;
	const [x0, y0, x1, y1] = (snapshot.elements[0].bounds as number[]).map((v) => v / perMm);
	return { width: x1 - x0, height: y1 - y0 };
}

/**
 * Every notice card out of the way.
 *
 * The fenced server carries a standing "No connection to the machine" alarm — it has no
 * machine on the other end — and that card hangs under the top bar over the first
 * 244 px of the page. An earlier version of this file picked the rectangle up by
 * clicking its top edge at (75, 15) mm, which lands at y 137: the click went to the
 * card, nothing was selected, and the test reported the pattern absent because it never
 * got to look. The selection now comes through the URL, and the card is dismissed
 * anyway so it cannot sit over what is measured.
 */
async function dismissNotices() {
	for (let i = 0; i < 3; i++) {
		const seen = page.getByRole('button', { name: 'Seen', exact: true });
		if ((await seen.count()) === 0) return;
		await seen.first().click().catch(() => {});
		await page.waitForTimeout(200);
	}
}

/** One rectangle of 120 x 80 mm on an otherwise empty bed, selected. */
async function aRectangle() {
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	const made = await (
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 15,
			y_mm: 15,
			width_mm: 120,
			height_mm: 80
		})
	).json();
	const id = made?.ids?.[0];
	assert.ok(id, 'the rectangle was not made');
	await page.goto(`${BASE}/?tab=design&select=${encodeURIComponent(id)}`, {
		waitUntil: 'domcontentloaded'
	});
	await page.waitForTimeout(2500);
	await dismissNotices();
	// The selection really happened before anything is read off the panel: a card over
	// the canvas or a slow first paint used to look exactly like the fields being absent.
	await page.waitForSelector('.selected', { timeout: 20000 });
	await page.waitForSelector('.selected .figures input[type=number]', { timeout: 20000 });
	await page.waitForTimeout(900);
}

/** The five number fields of the selection card, in the order they stand. */
const fields = () =>
	page.$$eval('.selected .figures input[type=number]', (nodes) =>
		nodes.map((node) => {
			const input = node as HTMLInputElement;
			return {
				label: input.getAttribute('aria-label') ?? '',
				value: input.value,
				disabled: input.disabled,
				title: input.getAttribute('title') ?? ''
			};
		})
	);

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);
});

after(async () => {
	await browser?.close();
});

test('a width of 0 is refused with a sentence and the shape’s own width comes back', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await aRectangle();

	const width = page.locator('.selected .figures input[aria-label*="Width"]');
	await width.fill('0');
	await width.press('Enter');
	await page.waitForTimeout(900);

	assert.equal(
		await width.inputValue(),
		'120.0',
		'the field kept the refused 0 while the shape is 120.0 mm wide'
	);
	const said = await page.textContent('.selected .refused');
	assert.ok(
		said && /more than 0 mm/i.test(said),
		`a refused width said nothing: ${JSON.stringify(said)}`
	);
	assert.equal(
		Math.round((await sizeMm()).width),
		120,
		'the refused width reached the design'
	);
});

test('a locked shape has its five number fields switched off, with the reason on them', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await aRectangle();

	await page.keyboard.press('Meta+l');
	await page.waitForTimeout(1000);

	const five = await fields();
	assert.equal(five.length, 5, `expected W, H, X, Y and the angle, saw ${five.length} fields`);
	for (const field of five) {
		assert.ok(field.disabled, `"${field.label}" is still typeable on a locked shape`);
		assert.match(
			field.title,
			/locked/i,
			`"${field.label}" is off without saying why: ${JSON.stringify(field.title)}`
		);
	}

	// And it stays honest: the values are the shape's own.
	const own = await sizeMm();
	assert.equal(five[0].value, own.width.toFixed(1));
	assert.equal(five[1].value, own.height.toFixed(1));

	// The sixth control in the grid, the ratio chain, is off with them — and looks it.
	// Measured before: disabled with the reason on it, but opacity 1, rgb(12, 112, 121)
	// on its teal pressed background and cursor: pointer, beside five fields at 0.6.
	const chain = await page.$eval('.selected .figures .link', (node) => {
		const style = getComputedStyle(node);
		return {
			disabled: (node as HTMLButtonElement).disabled,
			title: node.getAttribute('title') ?? '',
			opacity: Number(style.opacity),
			cursor: style.cursor,
			background: style.backgroundColor
		};
	});
	assert.ok(chain.disabled, 'the ratio chain is still pressable on a locked shape');
	assert.match(chain.title, /locked/i, 'the ratio chain is off without saying why');
	assert.ok(
		chain.opacity <= 0.6,
		`the ratio chain is off but reads as live: opacity ${chain.opacity}`
	);
	assert.equal(chain.cursor, 'not-allowed', 'the ratio chain still invites a click');
	assert.match(
		chain.background,
		/rgba\(0, 0, 0, 0\)|transparent/,
		`the ratio chain keeps its pressed background while off: ${chain.background}`
	);
});

test('an X that is not a number puts the shape\u2019s own position back', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await aRectangle();

	// A browser hands `<input type=number>` an empty string for anything it cannot read,
	// and `Number('')` is 0 — measured on the baseline, emptying X moved the rectangle
	// from 15.0 to 0.0 mm. X and Y take any number, so there is no rule to say out loud
	// here; what they owe is the same as W and H: never a number the shape does not have.
	const x = page.locator('.selected .figures input[aria-label*="X"]');
	await x.fill('');
	await x.press('Enter');
	await page.waitForTimeout(900);

	const where = await design();
	const leftMm = (where.elements[0].bounds as number[])[0] / (where.units_per_mm as number);
	assert.equal(leftMm.toFixed(1), '15.0', 'an unreadable X moved the shape');
	assert.equal(await x.inputValue(), '15.0', 'the field kept a position the shape has not');
});
