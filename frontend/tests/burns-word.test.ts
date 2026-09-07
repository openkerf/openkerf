/**
 * Whether a shape burns is decided in one place and said in one word.
 *
 * Run the part that needs no server:
 *   node --test frontend/tests/burns-word.test.ts
 * And the measured part against a running OpenKerf:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/burns-word.test.ts
 *
 * Why it exists (pattern P11). A shape in a layer with "burn along" off was said
 * three ways and half the time not at all. Measured on main at 1440 x 900: the
 * selection card showed `Rectangle · Fine lines` in plain grey with no word about
 * not burning; the Layers row beside it showed the same layer dashed and tagged
 * "does not burn"; the pre-flight table left the layer out altogether (2 rows for
 * 3 layers); and the drawing under it said "2 shapes sit in no layer that burns",
 * which is what the app calls a shape nobody assigned. On top of that the chip was
 * the first thing squeezed out of the header: for a long text `.in-layers` was
 * 0 px wide against a `scrollWidth` of 59, so the only place that named the layer
 * was not on the screen at all.
 *
 * What is held here: one decider (`burnVerdict`), one word (`panel.tag.doesNotBurn`)
 * in the selection card and in the pre-flight, a sentence under the drawing that
 * names the switched-off layer, and a chip that keeps a width whatever the name
 * beside it does.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { burnVerdict } from '../src/lib/design.svelte.ts';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8126';

// ── the decider ──────────────────────────────────────────────────────────────

const ops = [
	{ id: 'a', output: true },
	{ id: 'b', output: false }
];

test('a shape in no layer at all is "noLayer"', () => {
	assert.equal(burnVerdict([], ops), 'noLayer');
	assert.equal(burnVerdict(undefined, ops), 'noLayer');
});

test('a shape whose only layer is gone from the design is "noLayer"', () => {
	assert.equal(burnVerdict(['ghost'], ops), 'noLayer');
});

test('a shape in a layer that is switched off is "layerOff", not "noLayer"', () => {
	assert.equal(burnVerdict(['b'], ops), 'layerOff');
});

test('one layer that burns is enough', () => {
	assert.equal(burnVerdict(['a'], ops), 'burns');
	assert.equal(burnVerdict(['b', 'a'], ops), 'burns');
});

// ── the three surfaces ───────────────────────────────────────────────────────

let reachable = false;
let browser: Browser | null = null;
/** The shapes and the switched-off layer the surfaces below are measured on. */
let scene: { offLabel: string; rectInOff: string; longText: string; loose: string } = {
	offLabel: '',
	rectInOff: '',
	longText: '',
	loose: ''
};

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/**
 * Three layers, the third switched off, and four shapes: one per layer, a long
 * text in the switched-off one and one shape in no layer at all — so the two
 * cases the app used to say with the same sentence are both on the bed.
 */
async function aBed() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 }
	])
		await post('/api/design/operations', layer);
	for (let i = 0; i < 3; i++)
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 40,
			y_mm: 20,
			width_mm: 30,
			height_mm: 30
		});
	await post('/api/design/elements', {
		type: 'text',
		x_mm: 20,
		y_mm: 80,
		text: 'A much longer caption that somebody typed for a nameplate on the workshop door',
		size_mm: 5
	});
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const layers = design.operations.filter((o: { grid?: unknown }) => !o.grid);
	const elements = design.elements as { id: string }[];
	for (let i = 0; i < elements.length; i++) {
		for (const op of layers)
			await post('/api/design/unassign', { ids: [elements[i].id], operation_id: op.id });
		// The last two go into the third layer; the first rectangle keeps no layer.
		if (i > 0)
			await post('/api/design/assign', {
				ids: [elements[i].id],
				operation_id: layers[Math.min(i, 2)].id
			});
	}
	await fetch(`${BASE}/api/design/operations/${layers[2].id}`, {
		method: 'PATCH',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ output: false })
	});
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	scene = {
		offLabel: layers[2].label,
		loose: elements[0].id,
		rectInOff: elements[2].id,
		longText: elements[3].id
	};
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

/** The header of the selection card, as it stands for one shape. */
async function header(id: string, width: number) {
	const context = await browser!.newContext({ viewport: { width, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${id}`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.selected .head', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
			timeout: 20000
		});
		await page.waitForTimeout(1000);
		return await page.evaluate(() => {
			const card = document.querySelector('.selected')!;
			const head = card.querySelector('.head')!;
			const chips = head.querySelector('.in-layers');
			const chip = head.querySelector('.laagchip, .geenlaag');
			return {
				// The card, not the header: the word sits under the name, where the
				// Layers row keeps it too — in the header there was no room for it.
				text: (card.textContent ?? '').replace(/\s+/g, ' ').trim(),
				headText: (head.textContent ?? '').replace(/\s+/g, ' ').trim(),
				chipsWidth: Math.round(chips?.getBoundingClientRect().width ?? -1),
				chipWidth: Math.round(chip?.getBoundingClientRect().width ?? -1)
			};
		});
	} finally {
		await context.close();
	}
}

for (const width of [1440, 1024]) {
	test(`the header of a shape in a switched-off layer says it does not burn (${width})`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const head = await header(scene.rectInOff, width);
		assert.match(
			head.text,
			/does not burn/,
			`the selection card said "${head.text}" and not the Layers row's own word`
		);
		assert.ok(head.chipWidth > 0, `the layer chip is ${head.chipWidth} px wide`);
	});

	test(`a long name does not squeeze the layer chip off the header (${width})`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const head = await header(scene.longText, width);
		assert.ok(
			head.chipsWidth >= 40,
			`the chips beside a long name are ${head.chipsWidth} px wide`
		);
		assert.ok(head.chipWidth > 0, `the layer chip is ${head.chipWidth} px wide`);
		assert.match(head.text, /does not burn/, `the card said "${head.text}"`);
		// And the chip itself is whole, not clipped to make room for the word.
		assert.match(
			head.headText,
			/Fine lines/,
			`the header lost the layer name: "${head.headText}"`
		);
	});
}

test('the pre-flight names the switched-off layer, in the same word', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser!.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.pf-layers tbody tr', { timeout: 20000 });
		// The drawing and its sentence come with the overview, not with the clock;
		// wait for the sentence itself rather than for a guess about how long it takes.
		await page.waitForSelector('.notice.silent', { timeout: 20000 });
		const seen = await page.evaluate(() => ({
			rows: [...document.querySelectorAll('.pf-layers tbody tr')].map((row) =>
				(row.textContent ?? '').replace(/\s+/g, ' ').trim()
			),
			notices: [...document.querySelectorAll('.notice.silent')].map((n) =>
				(n.textContent ?? '').replace(/\s+/g, ' ').trim()
			)
		}));
		const row = seen.rows.find((r) => r.includes(scene.offLabel));
		assert.ok(row, `the table has no row for "${scene.offLabel}": ${JSON.stringify(seen.rows)}`);
		assert.match(row!, /does not burn/, `the row read "${row}"`);
		const off = seen.notices.find((n) => n.includes(scene.offLabel));
		assert.ok(
			off,
			`no sentence named the switched-off layer: ${JSON.stringify(seen.notices)}`
		);
		assert.doesNotMatch(
			off!,
			/in no layer/,
			`a shape in a switched-off layer was called unassigned: "${off}"`
		);
		assert.ok(
			seen.notices.some((n) => /in no layer/.test(n)),
			`the shape that really is in no layer lost its own sentence: ${JSON.stringify(seen.notices)}`
		);
	} finally {
		await context.close();
	}
});
