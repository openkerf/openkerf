/**
 * Finding the board back: the photograph names it, and the list says its name.
 *
 * Run: `node --test frontend/tests/board-photo.test.ts`
 *
 * This exists because of a gap the user found by using the app: they burned a board,
 * were pleased with it, and then could not get from the photograph to the settings. The
 * whole of the reading half was built and none of it was connected —
 * `POST /api/library/testgrids/photo` (no id in the path, decodes the code, names its
 * own board) had **zero callers** in `frontend/src`, so it was reachable by
 * hand-written HTTP only. Meanwhile the picker offered every board ever burned as
 * `date · material · operation`, in which two planks of the same material on the same
 * day are the same line — measured on the author's library: of 32 boards, eleven were
 * indistinguishable from another one, which is the problem the code was minted to solve.
 *
 * So three promises are pinned here, and each one goes red if the wiring is pulled out
 * again. They read the source rather than the browser on purpose: what broke was not
 * behaviour under a condition but a connection that was never made, and a missing
 * connection is exactly what a rendering test cannot see.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = (...bits: string[]) => readFileSync(join(here, '..', 'src', ...bits), 'utf8');

const result = src('lib', 'components', 'TestGridResult.svelte');
const library = src('lib', 'components', 'MaterialLibrary.svelte');
const page = src('routes', '+page.svelte');

test('the photograph can name its own board, without being told which board', () => {
	// The id-less route, called with a form body and no board chosen beforehand. The
	// per-id route stays — it is the fallback for a board with no code and the one that
	// refuses a photograph of the wrong plank — so this asserts the id-less one is
	// *also* there, not that the other went away.
	assert.match(
		result,
		/fetch\('\/api\/library\/testgrids\/photo'/,
		'nothing calls the route that reads the code and finds its own board'
	);
	assert.match(result, /\/api\/library\/testgrids\/\$\{grid\.id\}\/photo/);

	// What comes back opens: the answer is the grid row, so the panel switches to it
	// rather than telling the reader to go and find it.
	const reader = result.slice(result.indexOf('async function readBoardFromPhoto'));
	assert.match(reader.slice(0, 1600), /openId = body\?\.id/);
});

test('a board is offered by the name that is burned on it', () => {
	// `nameOf` groups the eight characters as the caption does, because this is the one
	// string a reader compares by eye against a plank in their hand.
	assert.match(result, /uid\.slice\(0, 4\)\} \$\{uid\.slice\(4\)/);
	// And the line the picker renders leads with it.
	const line = result.slice(result.indexOf('function lineFor'));
	assert.match(line.slice(0, 700), /nameOf\(g\.uid\)/);
	assert.match(result, /\{lineFor\(g\)\}/);
});

test('the list can be narrowed by what the reader actually has in hand', () => {
	// Name, material, thickness and the date: four things, because a reader has one of
	// them, not a particular one.
	const sift = result.slice(result.indexOf('let shown = $derived.by'));
	for (const field of ['g.uid', 'g.material_name', 'g.operation', 'g.thickness_mm']) {
		assert.ok(sift.slice(0, 900).includes(field), `the filter ignores ${field}`);
	}
	// The board that is open stays in the list even when the filter no longer matches
	// it: narrowing must not silently close what you were looking at.
	assert.match(sift.slice(0, 900), /g\.id === openId/);
});

test('the material library has a door to it, and the door leads to the reading half', () => {
	// The reader who has just burned something comes here first, because this is where
	// settings live. Before this there was nothing here at all.
	assert.match(library, /onReadBoard\?\.\(\)/, 'the material library offers no way in');
	assert.match(library, /library\.readBoard/);
	// And the page wires that door to the panel, with a stamp rather than a flag so
	// that coming back a second time is also an event.
	assert.match(page, /onReadBoard=\{\(\) => \{/);
	assert.match(page, /readBoard = Date\.now\(\)/);
	assert.match(page, /scrollTo=\{readBoard\}/);
	// The panel does something with it: a way in that is below the fold of a long
	// dialog is not a way in.
	assert.match(result, /scrollIntoView/);
});
