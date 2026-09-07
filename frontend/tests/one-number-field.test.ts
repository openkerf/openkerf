/**
 * A number you can edit in the selection card looks the same wherever it stands.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/one-number-field.test.ts
 *
 * One engine is shared with the other e2e tests, so use `--test-concurrency=1`. Skips
 * itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a failure).
 * Nothing is started and the head is never moved: a rectangle is turned and given
 * bridges over the API, and the card is measured as it stands.
 *
 * Why it exists. The Edit card carried three kinds of number field at once. Measured at
 * 1440 x 900 on a rectangle turned to 137.5° with bridges on:
 *
 *   - W, H, X, Y and the angle: a bare `<input type=number>` with the browser's spinner
 *     hidden, 27.9 px tall, 11 px mono, no − and no +;
 *   - Number and Length per bridge, twelve lines lower in the same card: a `NumberField`
 *     stepper, 36.8 px tall, 13 px, with two 38 px buttons and its label above it;
 *   - and in the Image fold a third, `DPI` with its label to the left in 4.5em.
 *
 * At 1024 the same card had them at 44 px against 44 px but 76.7 px wide against 177,
 * and 13 px against 15. The angle was the worst of it: its row was five columns wide for
 * one field and two buttons, so at 137.5° the input had 23.4 px for a number that needs
 * 33 and showed "∠137." — a truncated angle that you believe, because there is nothing
 * to say it is truncated.
 *
 * What is measured, at 1024 and 1440: every editable number in the selection card — with
 * a shape selected and with an image selected — sits in one and the same component, with
 * a − and a +, at one height and one type size, and the angle at 137.5° is on screen
 * whole. The other half of the same decision is measured too: a value in a *row* of the
 * Layers list reads as text and only draws its box under the pointer, so the numbers you
 * compare down the list are not fifteen boxes.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8121';
const WIDTHS = [1024, 1440];

let reachable = false;
let browser: Browser | null = null;
let rectangleId = '';
let imageId = '';

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** A 2 x 2 greyscale PNG, written here so the file carries no fixture. */
function aPng(): Uint8Array<ArrayBuffer> {
	const chunk = (type: string, data: Uint8Array) => {
		const body = new Uint8Array(4 + data.length);
		body.set(new TextEncoder().encode(type), 0);
		body.set(data, 4);
		const length = new Uint8Array(4);
		new DataView(length.buffer).setUint32(0, data.length);
		let crc = 0xffffffff;
		for (const byte of body) {
			crc ^= byte;
			for (let i = 0; i < 8; i++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
		}
		const tail = new Uint8Array(4);
		new DataView(tail.buffer).setUint32(0, (crc ^ 0xffffffff) >>> 0);
		return [length, body, tail];
	};
	const header = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
	const ihdr = new Uint8Array([0, 0, 0, 2, 0, 0, 0, 2, 8, 0, 0, 0, 0]);
	const raw = new Uint8Array([0, 0x20, 0x80, 0, 0xc0, 0x40]);
	let adler = 1;
	let sum2 = 0;
	for (const byte of raw) {
		adler = (adler + byte) % 65521;
		sum2 = (sum2 + adler) % 65521;
	}
	const zlib = new Uint8Array(2 + 5 + raw.length + 4);
	zlib.set([
		0x78,
		0x01,
		0x01,
		raw.length & 0xff,
		raw.length >> 8,
		~raw.length & 0xff,
		(~raw.length >> 8) & 0xff
	]);
	zlib.set(raw, 7);
	new DataView(zlib.buffer).setUint32(7 + raw.length, ((sum2 << 16) | adler) >>> 0);
	const parts = [
		header,
		...chunk('IHDR', ihdr),
		...chunk('IDAT', zlib),
		...chunk('IEND', new Uint8Array(0))
	];
	const total = parts.reduce((n, p) => n + p.length, 0);
	const out = new Uint8Array(new ArrayBuffer(total));
	let at = 0;
	for (const part of parts) {
		out.set(part, at);
		at += part.length;
	}
	return out;
}

/**
 * The bed this file measures: a cut layer with a rectangle in it, turned to 137.5° and
 * carrying bridges, plus an imported image and a raster layer to open in the Layers tab.
 *
 * 137.5 is not a round number by accident — it is the angle at which the old row clipped
 * its own value, and one decimal is the most the field ever shows.
 */
async function aBed() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	await post('/api/design/operations', {
		type: 'cut',
		label: 'Outline',
		speed: 12,
		power_percent: 65
	});
	await post('/api/design/operations', {
		type: 'raster',
		label: 'Logo area',
		speed: 300,
		power_percent: 30
	});
	const made = await (
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20,
			y_mm: 20,
			width_mm: 120,
			height_mm: 80
		})
	).json();
	rectangleId = made?.ids?.[0] ?? '';
	assert.ok(rectangleId, 'the rectangle was not made');
	const snapshot = await (await fetch(`${BASE}/api/design`)).json();
	const cut = snapshot.operations.find(
		(op: { grid?: unknown; type: string }) => !op.grid && op.type === 'op cut'
	);
	assert.ok(cut, 'no cut layer to put the rectangle in');
	await post('/api/design/assign', { ids: [rectangleId], operation: cut.id });
	await post('/api/design/rotate', { ids: [rectangleId], angle_deg: 137.5, absolute: true });
	await post('/api/design/bridges', { ids: [rectangleId], count: 6, length_mm: 2 });

	const form = new FormData();
	form.append('file', new Blob([aPng()], { type: 'image/png' }), 'photo.png');
	const loaded = await (await fetch(`${BASE}/api/job/load`, { method: 'POST', body: form })).json();
	imageId = loaded.added?.[0] ?? '';
	assert.ok(imageId, 'the PNG was not imported');
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	await aBed();
});

after(async () => {
	await browser?.close();
});

type Field = {
	name: string;
	height: number;
	fontSize: number;
	steps: number;
	stepper: boolean;
	width: number;
	needs: number;
};

/** Every number you can type in the selection card, as it stands on the screen. */
async function numbersInCard(id: string, width: number): Promise<Field[]> {
	const context = await browser!.newContext({ viewport: { width, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${encodeURIComponent(id)}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.selected', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		// The Image fold is closed until it is opened, and the DPI field lives in it.
		const fold = page.locator('.selected details.fold').filter({ hasText: 'Image' }).first();
		if (await fold.count()) await fold.locator('summary').click().catch(() => {});
		await page.waitForTimeout(700);
		return await page.$$eval('.selected', (cards) => {
			const round = (v: number) => Math.round(v * 10) / 10;
			const card = cards[0];
			const found: Field[] = [];
			for (const node of card.querySelectorAll('input')) {
				const input = node as HTMLInputElement;
				const numeric =
					input.type === 'number' ||
					input.inputMode === 'decimal' ||
					input.inputMode === 'numeric';
				if (!numeric) continue;
				const field = input.closest('.field');
				const box = input.getBoundingClientRect();
				found.push({
					name:
						input.getAttribute('aria-label') ||
						(field?.querySelector('label')?.textContent ?? '').trim() ||
						(input.closest('label')?.textContent ?? '').trim(),
					height: round(box.height),
					fontSize: round(parseFloat(getComputedStyle(input).fontSize)),
					steps: field ? field.querySelectorAll('button').length : 0,
					stepper: Boolean(field),
					width: round(box.width),
					needs: input.scrollWidth
				});
			}
			return found;
		});
	} finally {
		await context.close();
	}
}

for (const width of WIDTHS) {
	test(`every number in the selection card is the same field at ${width}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const onShape = await numbersInCard(rectangleId, width);
		const onImage = await numbersInCard(imageId, width);
		assert.ok(
			onShape.length >= 7,
			`expected W, H, X, Y, the angle and the two bridge fields, saw ${onShape.length}: ` +
				onShape.map((f) => f.name).join(', ')
		);
		assert.ok(
			onImage.length >= 5,
			`expected W, H, X, Y and the image DPI, saw ${onImage.length}: ` +
				onImage.map((f) => f.name).join(', ')
		);

		for (const field of [...onShape, ...onImage]) {
			assert.ok(
				field.stepper,
				`"${field.name}" is a bare number field: ${field.height} px, ${field.fontSize} px type`
			);
			assert.equal(field.steps, 2, `"${field.name}" has no − and + of its own`);
		}
	});

	test(`the card holds one height and one type size for its numbers at ${width}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		for (const [what, fields] of [
			['a shape', await numbersInCard(rectangleId, width)],
			['an image', await numbersInCard(imageId, width)]
		] as [string, Field[]][]) {
			const heights = [...new Set(fields.map((f) => f.height))];
			const sizes = [...new Set(fields.map((f) => f.fontSize))];
			assert.equal(
				heights.length,
				1,
				`the card around ${what} shows ${heights.length} field heights: ` +
					fields.map((f) => `${f.name} ${f.height}`).join(', ')
			);
			assert.equal(
				sizes.length,
				1,
				`the card around ${what} shows ${sizes.length} type sizes: ` +
					fields.map((f) => `${f.name} ${f.fontSize}`).join(', ')
			);
		}
	});

	test(`the angle shows 137.5 whole at ${width}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const fields = await numbersInCard(rectangleId, width);
		const angle = fields.find((f) => /angle|hoek/i.test(f.name));
		assert.ok(angle, `no angle field found among ${fields.map((f) => f.name).join(', ')}`);
		assert.ok(
			angle!.needs <= Math.ceil(angle!.width) + 1,
			`the angle needs ${angle!.needs} px and has ${angle!.width}`
		);
	});
}

/**
 * The other half of the decision.
 *
 * Speed, power and passes stand fifteen to a list of five layers. They are read far more
 * often than they are changed, so they read as text and take their box under the pointer
 * or on focus — that is why they are *not* a stepper, and this file says so out loud so
 * that the next repair does not turn them into one.
 */
test('a value in a Layers row reads as text until you point at it', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.layer .val input', { timeout: 20000 });
		await page.waitForTimeout(500);
		const rest = await page.$eval('.layer .val', (node) => {
			const style = getComputedStyle(node);
			return { border: style.borderTopColor, background: style.backgroundColor };
		});
		const transparent = (colour: string) => /rgba\(0, 0, 0, 0\)|transparent/.test(colour);
		assert.ok(
			transparent(rest.border) && transparent(rest.background),
			`a row value draws a box while nobody points at it: border ${rest.border}, background ${rest.background}`
		);
	} finally {
		await context.close();
	}
});

/**
 * Home and End belong to the caret, not to the shape.
 *
 * The field is `type="text"` with `inputmode="decimal"`, so Home is what it is in every
 * other text box on the machine: put the caret before the first digit — which is exactly
 * what you press to correct the 1 of "142.5". The component answered it by writing its
 * own minimum into the field and committing it. Measured at 1440 on a 60 x 40 mm
 * rectangle, before this fix: one Home in the width left the field at 0.1 and the shape
 * really 0.1 x 0.067 mm, with no refusal and no sentence. There is no undo of a
 * keystroke you did not know you had given.
 *
 * So the two keys write nothing any more. The arrows still step, which is all an
 * `<input type=number>` ever gave them.
 */
test('Home in the width leaves the shape the size it was', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const made = await (
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 200,
			y_mm: 150,
			width_mm: 60,
			height_mm: 40
		})
	).json();
	const id: string = made?.ids?.[0] ?? '';
	assert.ok(id, 'the rectangle was not made');

	const size = async () => {
		const snapshot = await (await fetch(`${BASE}/api/design`)).json();
		const element = snapshot.elements.find((e: { id: string }) => e.id === id);
		assert.ok(element, 'the rectangle is gone');
		const [x0, y0, x1, y1] = element.bounds as number[];
		const perMm = snapshot.units_per_mm as number;
		return {
			width: Math.round(((x1 - x0) / perMm) * 100) / 100,
			height: Math.round(((y1 - y0) / perMm) * 100) / 100
		};
	};

	const before = await size();
	assert.deepEqual(before, { width: 60, height: 40 });

	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${encodeURIComponent(id)}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.selected', { timeout: 20000 });
		const width = page.locator('.selected input[aria-label*="Width" i]').first();
		await width.click();
		await page.keyboard.press('Home');
		await page.keyboard.press('End');
		await page.keyboard.press('Tab');
		// The commit goes over the API and comes back into the card; wait for the answer,
		// not for a guess about how long it takes.
		await page.waitForTimeout(3000);
		assert.equal(await width.inputValue(), '60.0', 'the field itself changed');
	} finally {
		await context.close();
	}
	assert.deepEqual(await size(), before, 'Home resized the shape');
});

/**
 * The unit stands with the label, and nowhere else.
 *
 * It used to stand in four places at once in this one card: an "mm" column three columns
 * from the number it belonged to, a "°" inside the box, a "(mm)" in a label and a DPI
 * with nothing at all. Two remain, and one rule decides which: where the label is a
 * letter (W, H, X, Y, ∠) there is no room beside it and the unit is a cap in the box;
 * where the label is a word it stands in the label. What may not come back is a unit
 * loose in the grid, away from its number.
 */
test('every unit in the card stands with its own number', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${encodeURIComponent(rectangleId)}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.selected', { timeout: 20000 });
		await page.waitForTimeout(500);
		const fields = await page.$$eval('.selected .field', (nodes) =>
			nodes.map((node) => ({
				label: (node.querySelector('label')?.textContent ?? '').trim(),
				compact: node.classList.contains('compact'),
				cap: (node.querySelector('.suffix')?.textContent ?? '').trim()
			}))
		);
		assert.ok(fields.length >= 7, `only ${fields.length} fields in the card`);
		for (const field of fields) {
			const inLabel = /\((.+)\)/.exec(field.label)?.[1] ?? '';
			assert.ok(
				!(inLabel && field.cap),
				`"${field.label}" writes its unit twice: "(${inLabel})" and a cap "${field.cap}"`
			);
			if (field.compact)
				assert.equal(inLabel, '', `the narrow field "${field.label}" keeps its unit in the label`);
			else
				assert.equal(field.cap, '', `the roomy field "${field.label}" keeps a cap "${field.cap}"`);
		}
		// Nothing that looks like a unit stands loose in the block of measures.
		const loose = await page.$$eval('.selected .figures > *', (nodes) =>
			nodes
				.filter((n) => !n.classList.contains('field') && n.tagName !== 'BUTTON')
				.map((n) => (n.textContent ?? '').trim())
		);
		assert.deepEqual(loose, [], `something else stands between the measures: ${loose.join(' · ')}`);
	} finally {
		await context.close();
	}
});
