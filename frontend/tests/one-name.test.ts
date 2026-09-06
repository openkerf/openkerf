/**
 * A thing is called what it is, and a layer is numbered once.
 *
 * Run the part that needs no server:
 *   node --test frontend/tests/one-name.test.ts
 * And the measured part against a running OpenKerf:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/one-name.test.ts
 *
 * Why it exists (pattern P12). Measured on main at 1440 x 900, on a bed with five
 * layers you draw in and a 4 x 4 test grid:
 *
 * - The library's "Apply to" offered **21 layers** where the panel shows 5, because
 *   it numbered `index + 1` over the raw `design.operations` — sixteen grid cells
 *   included. The layer the panel calls 5 · Board labels was offered as
 *   "Layer 21 · Board labels": the same layer, sixteen apart, two clicks from each
 *   other.
 * - A generated QR (`QR — OK1:7X4MQB2K`) was called **"Path"**.
 * - Two rectangles in one group were called **"2 shapes"**, while the menu over
 *   them offered *Ungroup*.
 * - A PNG import made a layer called **"Image=B2T 250mm/s @1000"** — the engine's
 *   own formatter — in the chip, the layer list and the pre-flight table. That half
 *   and the refusal below it sit on the engine side, and are held in
 *   `api/tests/test_layer_names.py`.
 * - The chip in the selection card said **"Engrave"** with no number; that it was
 *   layer 3 stood in a tooltip.
 * - `PATCH /api/design/operations/{id}` with `label: "   "` answered **200** and the
 *   layer was left with no name at all, while the library refuses the same act with
 *   "A material needs a name."
 *
 * What is held here: one list of the layers you draw in (`drawnLayers`), one number
 * over that list (`layerNumber`), one wording for naming a layer away from its own
 * row (`layerNamed`), one name for a shape (`elementName` / `selectionName`), and a
 * refusal for a layer with no name.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import {
	drawnLayers,
	layerNumber,
	layerNamed,
	elementName,
	selectionName
} from '../src/lib/design.svelte.ts';
import { objectMenu, type Context, type Handlers, type Menu } from '../src/lib/actions.ts';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8126';

// ── one list, one number ─────────────────────────────────────────────────────

/** Three layers you draw in with four grid cells wedged between them. */
const OPS = [
	{ id: 'a', label: 'Outline', grid: null },
	{ id: 'c1', label: '5 mm/s · 30%', grid: { id: 1 } },
	{ id: 'c2', label: '5 mm/s · 50%', grid: { id: 1 } },
	{ id: 'c3', label: '10 mm/s · 30%', grid: { id: 1 } },
	{ id: 'c4', label: '10 mm/s · 50%', grid: { id: 1 } },
	{ id: 'b', label: 'Engrave', grid: null },
	{ id: 'c', label: 'Board labels', grid: null }
];

test('the layers you draw in are the ones without a grid cell behind them', () => {
	assert.deepEqual(
		drawnLayers(OPS).map((o) => o.id),
		['a', 'b', 'c']
	);
});

test('a layer has one number, whichever surface asks for it', () => {
	const design = { operations: OPS } as never;
	// The number the panel puts on the chip is the index in `drawnLayers`.
	for (const [index, op] of drawnLayers(OPS).entries())
		assert.equal(
			layerNumber(design, op.id),
			index + 1,
			`${op.label} is numbered two ways: ${layerNumber(design, op.id)} against ${index + 1}`
		);
	// And a grid cell is not a layer you can number at all.
	assert.equal(layerNumber(design, 'c3'), null);
});

test('a layer named away from its own row carries its number', () => {
	assert.match(layerNamed(3, 'Engrave'), /3/);
	assert.match(layerNamed(3, 'Engrave'), /Engrave/);
	// Two layers of the same kind are told apart by that number and nothing else.
	assert.notEqual(layerNamed(2, 'Engrave'), layerNamed(3, 'Engrave'));
});

// ── the layer submenu ────────────────────────────────────────────────────────

const NOTHING = () => {};
const HANDLERS = new Proxy({}, { get: () => NOTHING }) as Handlers;

function context(over: Partial<Context> = {}): Context {
	return {
		count: 1,
		inGroup: false,
		lockedCount: 0,
		isImage: false,
		isText: false,
		isCropped: false,
		filled: false,
		bridges: { carries: true, has: false },
		clipboard: 0,
		busy: false,
		may: true,
		offline: false,
		layers: [],
		sheets: [],
		snap: true,
		layerNumbers: true,
		empty: false,
		splittable: { shapes: 0, pieces: 0 },
		under: [],
		columns: [],
		once: false,
		...over
	} as Context;
}

function submenu(menu: Menu, id: string): { label: string }[] {
	for (const group of menu)
		for (const item of group.items)
			if (item !== 'separator' && 'items' in item && item.id === id) return item.items;
	throw new Error(`no submenu ${id}`);
}

test('the Layer submenu tells two layers of the same kind apart', () => {
	const layers = [
		{ id: 'a', number: 1, label: 'Outline', inside: false },
		{ id: 'b', number: 2, label: 'Engrave', inside: false },
		{ id: 'c', number: 3, label: 'Engrave', inside: true }
	];
	const rows = submenu(objectMenu(context({ layers }), HANDLERS), 'layer')
		.slice(0, 3)
		.map((r) => r.label);
	assert.equal(new Set(rows).size, 3, `the submenu reads ${JSON.stringify(rows)}`);
	for (const layer of layers)
		assert.equal(rows[layer.number - 1], layerNamed(layer.number, layer.label));
});

// ── what a shape is called ───────────────────────────────────────────────────

const bare = { text: null, label: '' };

test('a shape without a name of its own is called what it is', () => {
	assert.equal(elementName({ ...bare, type: 'elem rect', label: 'Rect meerk40t:5 #0000ff' }), 'Rectangle');
	assert.equal(elementName({ ...bare, type: 'elem path', label: 'Path meerk40t:9 #e5484d' }), 'Path');
});

test('a shape a generator here laid down keeps the name it was given', () => {
	const qr = { ...bare, type: 'elem path', label: 'QR — OK1:7X4MQB2K' };
	assert.notEqual(elementName(qr), 'Path');
	assert.match(elementName(qr), /^QR/);
	const hinge = { ...bare, type: 'elem path', label: 'Living hinge — staggered' };
	assert.match(elementName(hinge), /hinge/i);
	// And the internal id and the colour code do not come with it.
	assert.doesNotMatch(
		elementName({ ...bare, type: 'elem path', label: 'Box — front meerk40t:12 #0000ff' }),
		/meerk40t|#0000ff/
	);
});

test('a group is called a group, not a heap of shapes', () => {
	const two = [
		{ type: 'elem rect', text: null, label: '', group_id: 'g1' },
		{ type: 'elem rect', text: null, label: '', group_id: 'g1' }
	];
	assert.match(selectionName(two), /group/i);
	assert.match(selectionName(two), /2/);
	// Two shapes that are not one group stay two shapes.
	const apart = [
		{ type: 'elem rect', text: null, label: '', group_id: 'g1' },
		{ type: 'elem rect', text: null, label: '', group_id: null }
	];
	assert.doesNotMatch(selectionName(apart), /group/i);
	// One shape is named after itself, group or no group.
	assert.equal(selectionName([two[0]]), 'Rectangle');
});

// ── what the running app shows ───────────────────────────────────────────────

let reachable = false;
let browser: Browser | null = null;
/** The bed everything below is measured on. */
let scene: { qr: string; grouped: string; layers: { id: string; label: string }[] } = {
	qr: '',
	grouped: '',
	layers: []
};

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/**
 * Five layers you draw in — two of them of the same kind — a 4 x 4 test grid whose
 * sixteen cells are layers in the engine, a generated QR and two grouped rectangles.
 */
async function aBed() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', speed: 250, power_percent: 22 },
		{ type: 'engrave', speed: 400, power_percent: 15 }
	])
		await post('/api/design/operations', layer);
	await post('/api/library/testgrids', {
		operation: 'snijden',
		speed_min: 5,
		speed_max: 20,
		speed_steps: 4,
		power_min: 30,
		power_max: 90,
		power_steps: 4,
		origin_x_mm: 10,
		origin_y_mm: 120
	});
	// The window shows its filters — and its "Apply to" — only when there is something
	// to apply; an empty library is a welcome page instead.
	const material = await post('/api/library/materials', { name: 'Birch plywood' });
	const id = material.ok ? (await material.json()).id : null;
	if (id)
		for (const preset of [
			{ material_id: id, operation: 'snijden', thickness_mm: 3, speed_mm_s: 12, power_percent: 65 },
			{ material_id: id, operation: 'graveren-vector', thickness_mm: 3, speed_mm_s: 250, power_percent: 22 }
		])
			await post('/api/library/presets', preset);
	await post('/api/design/generate/qrcode', {
		text: 'OK1:7X4MQB2K',
		x_mm: 150,
		y_mm: 20,
		size_mm: 25
	});
	for (let i = 0; i < 2; i++)
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 40,
			y_mm: 20,
			width_mm: 30,
			height_mm: 30
		});
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const loose = design.elements.filter(
		(e: { type: string; group_id: string | null }) => e.type === 'elem rect' && !e.group_id
	);
	await post('/api/design/group', { ids: loose.map((e: { id: string }) => e.id) });
	const after = await (await fetch(`${BASE}/api/design`)).json();
	const qr = after.elements.find((e: { label: string }) => (e.label ?? '').startsWith('QR'));
	const group = after.elements
		.filter((e: { type: string; group_id: string | null }) => e.type === 'elem rect' && e.group_id)
		.at(-1);
	scene = {
		qr: qr?.id ?? '',
		grouped: group?.id ?? '',
		layers: after.operations.filter((o: { grid?: unknown }) => !o.grid)
	};
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

/** The header of the selection card, as it stands for one selection. */
async function card(id: string) {
	const context_ = await browser!.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context_.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${id}`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.selected .head', { timeout: 20000 });
		await page.waitForTimeout(1200);
		return await page.evaluate(() => ({
			name:
				document.querySelector('.selected .head .name')?.textContent?.replace(/\s+/g, ' ').trim() ??
				'',
			chips: [...document.querySelectorAll('.selected .laagchip')].map((c) =>
				(c.textContent ?? '').replace(/\s+/g, ' ').trim()
			)
		}));
	} finally {
		await context_.close();
	}
}

test('the library applies to the layers you draw in, numbered as the panel numbers them', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context_ = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context_.newPage();
	try {
		await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.palette', { timeout: 20000 });
		await page.getByRole('button', { name: 'Material library' }).click();
		await page.waitForSelector('label.target', { timeout: 20000 });
		const options = await page.evaluate(() =>
			[...document.querySelectorAll('label.target select option')].map((o) =>
				(o.textContent ?? '').trim()
			)
		);
		assert.equal(
			options.length,
			scene.layers.length,
			`"Apply to" offers ${options.length} layers where the panel shows ${scene.layers.length}: ${JSON.stringify(options)}`
		);
		for (const [index, layer] of scene.layers.entries())
			assert.equal(
				options[index],
				layerNamed(index + 1, layer.label),
				`the library calls the panel's layer ${index + 1} "${options[index]}"`
			);
	} finally {
		await context_.close();
	}
});

test('a generated QR is not called "Path" in the panel', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const head = await card(scene.qr);
	assert.notEqual(head.name, 'Path', 'the panel calls a QR a path');
	assert.match(head.name, /^QR/, `the panel calls it "${head.name}"`);
});

test('two grouped rectangles are called a group in the panel', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const head = await card(scene.grouped);
	assert.match(head.name, /group/i, `the panel calls them "${head.name}"`);
});

test('the chip in the selection card says which layer, by number', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const head = await card(scene.qr);
	assert.ok(head.chips.length, 'the selection card shows no layer chip at all');
	assert.match(
		head.chips[0],
		/\d/,
		`the chip reads "${head.chips[0]}" — the number is in the tooltip only`
	);
});

/**
 * The badge and the layer list's chip, measured side by side at one width.
 *
 * Both carry the same thing — a burn order on its layer's colour — so both are
 * read at the same size. The type scale shifts at 1200 px and only the tokens
 * know that, so the assertion is against `--text-xs` rather than a number.
 */
async function badgeAndChip(id: string, width: number) {
	const context_ = await browser!.newContext({ viewport: { width, height: 900 } });
	const page = await context_.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${id}`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.selected .stip', { timeout: 20000 });
		await page.waitForTimeout(1200);
		return await page.evaluate(() => {
			const root = getComputedStyle(document.documentElement);
			const badge = document.querySelector('.selected .stip')!;
			const b = getComputedStyle(badge);
			const box = badge.getBoundingClientRect();
			return {
				textXs: root.getPropertyValue('--text-xs').trim(),
				radiusField: root.getPropertyValue('--radius-field').trim(),
				size: b.fontSize,
				radius: b.borderTopLeftRadius,
				w: +box.width.toFixed(1),
				h: +box.height.toFixed(1)
			};
		});
	} finally {
		await context_.close();
	}
}

for (const width of [1440, 1024]) {
	test(`the layer badge beside the selection is on the type scale at ${width}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const seen = await badgeAndChip(scene.qr, width);
		assert.equal(
			seen.size,
			seen.textXs,
			`the badge is ${seen.size} where the smallest size the app has is ${seen.textXs}`
		);
		assert.equal(
			seen.radius,
			seen.radiusField,
			`the badge is rounded ${seen.radius} where a field is ${seen.radiusField}`
		);
		const floor = parseFloat(seen.textXs);
		assert.ok(
			seen.h >= floor && seen.w >= floor,
			`the badge is ${seen.w} x ${seen.h} px around ${seen.textXs} of type`
		);
	});
}
