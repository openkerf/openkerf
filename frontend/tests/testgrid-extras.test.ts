/**
 * The two extras on the test-grid form: the board's own code, and cutting the tile loose.
 *
 * Both were built end to end — the drawing, the library columns, the route that looks the
 * cut setting up, the photograph that reads a code back — and then had no control on any
 * screen: `code_enabled` and `cutout_enabled` appeared nowhere in `frontend/src`, so the
 * only way to ask for either was hand-written HTTP, and the handbook said so out loud.
 *
 * What is pinned here is the part of that repair a browser cannot be relied on to notice
 * again: that the preview is asked for every field that changes the board, that the two
 * switches start off, that a board keeps one name while you look at it, and that the four
 * refusals this form places beside their own switch still exist on the other side.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const HERE = new URL('.', import.meta.url).pathname;
const FORM = readFileSync(join(HERE, '../src/lib/components/TestGrid.svelte'), 'utf8');

/** The body of one `function name(...) { … }`, by brace counting. */
function functionBody(source: string, name: string): string {
	const start = source.indexOf(`function ${name}(`);
	assert.notEqual(start, -1, `TestGrid.svelte no longer has a function ${name}`);
	const open = source.indexOf('{', start);
	let depth = 0;
	for (let i = open; i < source.length; i++) {
		if (source[i] === '{') depth++;
		else if (source[i] === '}' && --depth === 0) return source.slice(open, i + 1);
	}
	throw new Error(`unbalanced braces in ${name}`);
}

/** The `void [ … ]` list the live-preview effect reads to decide it has to ask again. */
function previewDependencies(): string {
	const start = FORM.indexOf('void [');
	assert.notEqual(start, -1, 'the live preview no longer lists what it re-previews on');
	return FORM.slice(start, FORM.indexOf('];', start));
}

test('the preview is asked again for every field that changes the board', () => {
	// The promise this whole panel rests on: what is drawn beside the form is the board
	// that would burn if you stopped typing now. A field that goes to the server but is
	// not in the effect's list is a field whose preview quietly keeps the previous answer.
	//
	// Measured, and the reason this test exists: `material_id` and `thickness_mm` were
	// missing. That was harmless while the material only decided a word in the caption; it
	// stopped being harmless when the cut-out's speed came from a lookup per material and
	// thickness. Switching from birch to glass — which has no cut setting at all — left
	// "The rim is cut at 12 mm/s and 65%" on screen, from the material before it.
	const sent = new Set([...functionBody(FORM, 'body').matchAll(/form\.(\w+)/g)].map((m) => m[1]));
	const watched = previewDependencies();
	// The caption is the one field the preview does not get, and that is deliberate: the
	// planning route is not told it. It is in `body(true)` only, for the board itself.
	sent.delete('caption');
	const missing = [...sent].filter((field) => !watched.includes(`form.${field}`));
	assert.deepEqual(missing, [], `sent to the server but not re-previewed on: ${missing.join(', ')}`);
});

test('the code and the cut-out are on the form at all', () => {
	// The hole this round filled. Both switches bind to the form, both travel to the
	// server under the name the library column has, and the size of the code is a field
	// you can read back — which is why all of this is on the form and not in a menu.
	for (const bound of ['bind:checked={form.code}', 'bind:checked={form.cutout}'])
		assert.ok(FORM.includes(bound), `no control bound to ${bound}`);
	assert.ok(FORM.includes('bind:value={form.code_size_mm}'), 'the code has no size field');
	for (const key of ['code_enabled: form.code', 'cutout_enabled: form.cutout'])
		assert.ok(FORM.includes(key), `${key} is never sent to the server`);
});

test('both switches start off', () => {
	// What the library's own columns say (`code_enabled INTEGER NOT NULL DEFAULT 0`), and
	// what the handbook promises. A board that has always been squares and a caption must
	// not start costing 20 mm of plank and a rim of cutting because the form learned two
	// new tricks.
	const declaration = FORM.slice(FORM.indexOf('let form = $state({'), FORM.indexOf('/** Under which key'));
	assert.match(declaration, /\bcode:\s*false\b/, 'the code switch does not start off');
	assert.match(declaration, /\bcutout:\s*false\b/, 'the cut-out switch does not start off');
});

test('a board keeps one name for as long as the form is about that board', () => {
	// The planner mints a name whenever it is given none, and this form previews on every
	// keystroke — measured: three previews in a row gave BF11HGMK, FB66KTY7 and PBQ98RSY.
	// The name is printed in the caption and burned in the code, so it has to be held on
	// this side and sent back, or it changes between reading it and pressing the button.
	assert.ok(FORM.includes('uid: boardUid'), 'the preview does not send the name back');
	assert.match(FORM, /boardUid = verse\.plan\.uid/, 'the name that came back is not kept');
	// And dropped for the next plank, because two boards must never carry one name.
	const again = functionBody(FORM, 'again');
	assert.match(again, /boardUid = null/, 'a next board would inherit this one’s name');
});

test('the refusals this form places beside a switch still exist in the engine layer', () => {
	// Each of these is shown under the switch that caused it rather than in the notice
	// above the picture, and that routing is by code. A renamed code would leave the
	// refusal in the general notice — still on screen, but away from the field that has to
	// change — so the two sides are checked against each other here.
	const placed = [...FORM.matchAll(/'(library\.grid\.\w+)'/g)].map((m) => m[1]);
	assert.ok(placed.length >= 4, 'no refusal is routed to its own switch any more');
	const api = join(HERE, '../../api/openkerf_api');
	const python = readdirSync(api)
		.filter((name) => name.endsWith('.py'))
		.map((name) => readFileSync(join(api, name), 'utf8'))
		.join('\n');
	for (const code of placed)
		assert.ok(python.includes(`code="${code}"`), `${code} is not raised anywhere any more`);
});

test('the bed check names the rectangle it was measured on', () => {
	// `board_room` is measured on the cut rectangle and not on the board (testgrid.py:748),
	// because that is what the head really has to reach. Measured on the default form with
	// a cut-out: the board starts at 2.4 mm and fits, the cut runs to −1.6 mm and does not.
	// Naming the board's own corner in that warning points the reader at a number that
	// looks fine.
	const warning = FORM.slice(FORM.indexOf('board_room === false'), FORM.indexOf('legenda'));
	assert.ok(warning.includes('cut_x_mm') && warning.includes('cut_y_mm'), 'the warning names the board and not the cut');
	assert.ok(!warning.includes('outer_x_mm'), 'the warning still names the board’s own corner');
});
