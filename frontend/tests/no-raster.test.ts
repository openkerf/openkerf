/**
 * The "cannot burn raster layers" block reads the key the API sends.
 *
 * Run: `node --test frontend/tests/no-raster.test.ts`
 * With a live server for the two rendered checks:
 *   OK_BASE=http://127.0.0.1:8122 node --test frontend/tests/no-raster.test.ts
 *
 * Why it exists. `/api/job/layers` and `/api/library/testgrids/preview` answer
 * `engine: {"raster": true|false}` (server.py → drawing.py `engine_report`, and the
 * preview route itself). The pre-flight and the test-grid wizard read `engine.grid`. A
 * key nobody sends is never `false`, so `rasterOff` and `rasterImpossible` could not become
 * true on any server — including the one the block was written for, where a raster
 * layer comes out of the machine blank (CLAUDE.md, first engine row). Measured before the
 * repair on a server whose answer was rewritten to `raster: false`: 0 `.pf-no-raster`
 * elements in the pre-flight, 0 `.waarschuwing.ernstig` in the wizard with Engrave ·
 * raster chosen. `docs.test.ts` guards the sentence word for word; nothing guarded the key.
 *
 * Three checks. The first needs no server: the name read by both components is the name
 * written by both routes, taken from the source on each side. The other two render the
 * block: the server's own answer is rewritten in the browser to say `raster: false` (a
 * fenced server has the rasteriser, and nothing is burned or moved), and the sentence
 * must then stand on the screen, in the pre-flight and in the wizard.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';
import { en } from '../src/lib/i18n/en.ts';

const here = dirname(fileURLToPath(import.meta.url));
const read = (...parts: string[]) => readFileSync(join(here, '..', ...parts), 'utf8');

test('the pre-flight and the wizard read the engine key the API sends', () => {
	const sent = new Set<string>();
	for (const source of [
		read('..', 'api', 'openkerf_api', 'server.py'),
		read('..', 'api', 'openkerf_api', 'drawing.py')
	]) {
		for (const m of source.matchAll(/"engine":\s*\{"(\w+)":/g)) sent.add(m[1]);
		for (const m of source.matchAll(/return \{"(\w+)": raster_supported/g)) sent.add(m[1]);
	}
	assert.deepEqual([...sent], ['raster'], 'the API sends one engine key, `raster`');

	for (const file of ['JobControls.svelte', 'TestGrid.svelte']) {
		const source = read('src', 'lib', 'components', file);
		const readKeys = [...source.matchAll(/engine\?\.(\w+)\s*===\s*false/g)].map((m) => m[1]);
		assert.ok(readKeys.length >= 1, `${file} reads an engine key`);
		for (const key of readKeys) {
			assert.ok(sent.has(key), `${file} reads engine.${key}, which the API never sends`);
		}
	}
});

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** A design with a cut layer and a raster layer, each holding one shape. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers = [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
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

test('the pre-flight says the server cannot burn raster layers when the API says so', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		// The server has a rasteriser; the one the block is for has not. Its answer is
		// rewritten on the way in, as that server would give it.
		await page.route('**/api/job/layers', async (route) => {
			const response = await route.fetch();
			const body = await response.json();
			body.engine = { raster: false };
			for (const layer of body.layers) if (layer.type === 'op raster') layer.burns = false;
			await route.fulfill({ response, json: body });
		});
		await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.pf-actions .btn.primary', { timeout: 20000 });
		await page.waitForSelector('.pf-blind', { timeout: 20000 });
		const block = page.locator('.pf-no-raster');
		assert.equal(await block.count(), 1, 'one block under the layer table');
		const text = (await block.textContent()) ?? '';
		assert.ok(text.includes(en['job.noRaster.title']), `block says "${en['job.noRaster.title']}"`);
		assert.ok(text.includes('Logo area'), 'the block names the layer that produces nothing');
	} finally {
		await context.close();
	}
});

test('the test-grid wizard says so for a raster board when the API says so', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.route('**/api/library/testgrids/preview', async (route) => {
			const response = await route.fetch();
			if (!response.ok()) return route.fulfill({ response });
			const body = await response.json();
			body.engine = { raster: false };
			await route.fulfill({ response, json: body });
		});
		await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.rail', { timeout: 20000 });
		await page.getByRole('button', { name: en['testgrid.title'], exact: true }).first().click();
		const operation = page.locator('.wizard select').filter({ has: page.locator('option[value="graveren-raster"]') });
		await operation.waitFor({ timeout: 20000 });
		await operation.selectOption('graveren-raster');
		const block = page.locator('.wizard .waarschuwing.ernstig', { hasText: en['job.noRaster.title'] });
		await block.waitFor({ timeout: 20000 });
		assert.equal(await block.count(), 1, 'one block in the wizard');
		assert.ok(((await block.textContent()) ?? '').includes(en['grid.noRaster.body']));
	} finally {
		await context.close();
	}
});
