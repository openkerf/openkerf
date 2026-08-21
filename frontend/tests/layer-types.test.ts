/**
 * The layer kinds the interface sends are the ones the engine layer knows.
 *
 * Run: `node --test frontend/tests/layer-types.test.ts`.
 *
 * Why this exists: a rename sweep turned the value `raster` into `grid` in the
 * three places the panel builds a layer kind, and nothing caught it. The types
 * did not: `kind: 'cut' | 'engrave' | 'grid'` is perfectly consistent with
 * itself. The tests did not either: the API tests pass their own values, and the
 * end-to-end tests skip without a server. So changing a layer back to raster gave
 * "Unknown layer type: grid" — on the machine's own screen, in the middle of a
 * job set-up.
 *
 * Hence a test that reads the source and compares the literals with the set in
 * `api/openkerf_api/drawing.py`. It needs no browser and no engine, so it runs
 * everywhere the other unit tests run.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');

/** The keys of `OPERATIONS` in the engine layer — read, not copied. */
function kindsTheApiKnows(): Set<string> {
	const source = readFileSync(join(root, 'api', 'openkerf_api', 'drawing.py'), 'utf8');
	const block = source.match(/^OPERATIONS\s*=\s*\{([\s\S]*?)^\}/m);
	assert.ok(block, 'OPERATIONS not found in drawing.py');
	const keys = [...block[1].matchAll(/"([a-z]+)"\s*:/g)].map((m) => m[1]);
	assert.ok(keys.length >= 4, `too few layer kinds read: ${keys.join(', ')}`);
	return new Set(keys);
}

/** Every layer kind the interface can put in a request. */
function kindsTheUiSends(): { where: string; kind: string }[] {
	const found: { where: string; kind: string }[] = [];
	const read = (...parts: string[]) => readFileSync(join(root, 'frontend', ...parts), 'utf8');

	const panel = read('src', 'lib', 'components', 'DesignPanel.svelte');
	// The dropdown in the layer row, and the fallback for an image layer.
	for (const m of panel.matchAll(/\{\s*value:\s*'([a-z]+)',\s*label:\s*t\('panel\.kind\./g)) {
		found.push({ where: 'DesignPanel LAYER_TYPES', kind: m[1] });
	}
	const image = panel.match(/kind === 'image' \? '([a-z]+)'/);
	assert.ok(image, 'the image fallback in kindOf() has gone');
	found.push({ where: 'DesignPanel kindOf', kind: image[1] });

	// The three "into one layer" actions in the menu and the action bar.
	const actions = read('src', 'lib', 'actions.ts');
	for (const m of actions.matchAll(/onlyLayer\('([a-z]+)'\)/g)) {
		found.push({ where: 'actions onlyLayer', kind: m[1] });
	}

	// And the type unions that carry those values on their way to the store.
	for (const [where, text] of [
		['actions.ts', actions],
		['edits.svelte.ts', read('src', 'lib', 'edits.svelte.ts')],
		['+page.svelte', read('src', 'routes', '+page.svelte')]
	] as const) {
		for (const m of text.matchAll(/'cut' \| 'engrave' \| '([a-z]+)'/g)) {
			found.push({ where: `${where} union`, kind: m[1] });
		}
	}
	assert.ok(found.length >= 8, `too few call sites found: ${found.length}`);
	return found;
}

test('every layer kind the interface sends is one the engine layer knows', () => {
	const known = kindsTheApiKnows();
	for (const { where, kind } of kindsTheUiSends()) {
		assert.ok(
			known.has(kind),
			`${where} sends '${kind}', and the API knows only ${[...known].sort().join(', ')}`
		);
	}
});

test('the panel offers the four kinds a user can choose', () => {
	// `image` is deliberately not in the list: the engine makes an image layer
	// itself when an image is placed, and it appears in the dropdown as raster.
	const offered = kindsTheUiSends()
		.filter((f) => f.where === 'DesignPanel LAYER_TYPES')
		.map((f) => f.kind);
	assert.deepEqual([...offered].sort(), ['cut', 'dots', 'engrave', 'raster']);
});
