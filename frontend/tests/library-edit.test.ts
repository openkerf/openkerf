/**
 * Editing the library you already have: the sum behind the removal question, and
 * the doors that verb needs to have.
 *
 * Run: `node --test frontend/tests/library-edit.test.ts`
 *
 * Three things are pinned here, and all three have a measurement behind them.
 *
 * **What would go.** `DELETE /api/library/materials/{id}` is `preset` CASCADE,
 * `grid_recipe` CASCADE and `test_grid.material_id` SET NULL. Measured on a copy of
 * the author's library, removing `Berkentriplex` took six settings with it — two of
 * them measured, with photographs — orphaned two boards and answered `{"removed": 6}`.
 * So the question that comes first has to name the count, and it must name only what
 * is really there: "0 test boards" beside a material that does carry one is a half
 * truth, and a reader who catches the interface out once stops reading its warnings.
 *
 * **The routes that have a caller.** Every material verb existed on the engine side
 * before this round and `DELETE .../materials/{id}` had zero callers in the whole
 * frontend — which is exactly why a reader concluded a material could not be removed.
 * A route nobody calls is a feature nobody has, so the table is walked here rather
 * than trusted.
 *
 * **The door that stays shut.** The library window used to hold a form that could
 * create a machine profile with a tube power and no machine behind it. It is the only
 * writer in the app that could, and therefore the only thing that can have made the
 * phantom `5030 CO2` — the app's own placeholder text — that carries twenty-seven
 * settings for a laser nobody runs. Deleting it is not enough; nothing may quietly put
 * it back.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { wouldGoWith, type MaterialUsage } from '../src/lib/library.svelte.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const store = readFileSync(join(root, 'frontend/src/lib/library.svelte.ts'), 'utf8');
const window_ = readFileSync(
	join(root, 'frontend/src/lib/components/MaterialLibrary.svelte'),
	'utf8'
);

/** What the engine's `material_usage` hands back, with everything at nothing. */
function usage(over: Partial<MaterialUsage> = {}): MaterialUsage {
	return {
		material_id: 3,
		name: 'Berkentriplex',
		presets: 0,
		test_grids: 0,
		grid_recipes: 0,
		photos: 0,
		sheets: 0,
		...over
	};
}

test('the removal question names what is there and nothing that is not', () => {
	// The live case, in the numbers it was measured in.
	assert.deepEqual(wouldGoWith(usage({ presets: 6, test_grids: 2, photos: 2 })), [
		'6 settings',
		'2 test grids',
		'2 photos'
	]);
	// A material nothing hangs off gets an empty list, and the interface then asks a
	// different question — one that does not pretend work is at stake.
	assert.deepEqual(wouldGoWith(usage()), []);
	// One of a thing is "1 setting", not "1 settings": the count keys carry both forms
	// and this is the sentence a reader checks against their own list.
	assert.deepEqual(wouldGoWith(usage({ presets: 1, grid_recipes: 1 })), ['1 setting', '1 recipe']);
});

test('the order is the order of consequence, heaviest first', () => {
	// Settings are the work, boards are the evidence, recipes are a convenience. A list
	// that opens with "1 recipe" reads as though little is at stake.
	const parts = wouldGoWith(usage({ presets: 3, test_grids: 1, grid_recipes: 1, photos: 1 }));
	assert.deepEqual(parts, ['3 settings', '1 test grid', '1 recipe', '1 photo']);
});

test('a sheet naming the material is a separate sentence, not an item in the list', () => {
	// The sheet is not removed — only its link to the material is cleared — so it
	// cannot stand in a list of things that go. Measured on the wording: gluing it in
	// gave "…6 settings, 2 test grids and 1 sheet. Removing takes all of that with it",
	// which promises to delete the reader's drawing.
	assert.deepEqual(wouldGoWith(usage({ presets: 1, sheets: 2 })), ['1 setting']);
	assert.match(window_, /library\.material\.remove\.sheet/);
});

test('every verb on a material has a caller', () => {
	// The route table on one side, the store on the other. A route without a caller is
	// what this whole round is about: all five of these existed and the window offered
	// exactly one of them.
	const calls: [string, RegExp][] = [
		['read what would go', /\/api\/library\/materials\/\$\{id\}\/usage/],
		['rename', /materials\/\$\{id\}`, \{\s*method: 'PATCH'/],
		['merge into another', /materials\/\$\{id\}\/merge-into\/\$\{targetId\}/],
		['remove, with everything on it', /with_everything=/],
		['take one import back', /\/api\/library\/imports\//],
		['attach the strays', /\/api\/library\/presets\/adopt/]
	];
	for (const [what, pattern] of calls)
		assert.match(store, pattern, `nothing in the store can ${what} any more`);
	// And the window has to reach them, or they are a store nobody uses.
	for (const method of [
		'materialUsage',
		'renameMaterial',
		'mergeMaterial',
		'removeMaterial',
		'removeImport',
		'adoptStrays'
	])
		assert.ok(window_.includes(`library.${method}(`), `the window never calls ${method}`);
});

test('nothing here can create a machine profile without a machine', () => {
	// The form is gone and so is the store method behind it; `POST /api/library/machines`
	// keeps its place in the engine layer, where an import uses it, and has no door in
	// the interface. What is left is the half that was needed: an editor for the machine
	// you are working on, because every profile in this library carries `power_watt:
	// null` and without it nothing can match.
	assert.ok(!store.includes('addMachineProfile'), 'the store can create a profile again');
	assert.ok(
		!/'\/api\/library\/machines',\s*\{\s*method: 'POST'/.test(store),
		'something posts a new machine profile again'
	);
	assert.match(store, /machines\/\$\{id\}`, \{\s*method: 'PATCH'/);
	assert.match(window_, /saveMachine\(machine\.id, \{/);
});

test('the count of test boards uses a key that exists', () => {
	// `count.grids` stood in this window beside every profile that carries a board, and
	// that key is in neither catalogue: the literal text "count.grids" was printed on
	// the screen. The key is `count.testGrids`.
	assert.ok(!window_.includes("'grids'"), 'count.grids is being composed again');
	assert.match(window_, /count\(machine\.test_grids, 'testGrids'\)/);
});
