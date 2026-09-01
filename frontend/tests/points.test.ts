/**
 * A point, and the one layer kind that burns it.
 *
 * Run: `node --test frontend/tests/points.test.ts`
 *
 * The user set a layer to Dots and everything after that went quietly wrong: the shape
 * that was in it fell out, adding another was impossible, and the preview said there was
 * nothing left to burn — with no reason anywhere on screen. The engine was right about all
 * of it (`OpDotsNode._allowed_elements` is `("elem point",)`), and this app was wrong twice
 * over: it lied about what it had done, and it offered a layer kind that nothing in the app
 * could ever fill, because a point could not be drawn at all.
 *
 * The engine half is pinned in `api/tests/test_drawing.py`. What is pinned here is the part
 * that lives in the interface.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = (...bits: string[]) => readFileSync(join(here, '..', 'src', ...bits), 'utf8');

test('the rail has a way to place a point', () => {
	const rail = src('lib', 'components', 'ToolRail.svelte');
	assert.match(rail, /'point'/, 'the tool rail cannot place a point');
	assert.match(rail, /rail\.tool\.point/);

	// And the canvas does something with it: one click, one spot, no size.
	const canvas = src('lib', 'components', 'Canvas.svelte');
	assert.match(canvas, /type: 'point', x_mm: at\.x, y_mm: at\.y/);
	// Snapping belongs to a tool that puts something in a place.
	assert.match(canvas, /tool === 'point' \|\| tool === 'pen'/);
});

test('placing points does not fall back to Select after every one', () => {
	// The general rule is one shape per click and then back to selecting, which is right
	// for a rectangle and wrong for a point: points are placed in rows, for perforating or
	// for drill marks. Measured with the general rule in force: three clicks left one point
	// on the bed, because the second and third selected instead of placing.
	const page = src('routes', '+page.svelte');
	assert.match(page, /if \(shape\.type !== 'point'\) tool = 'select';/);
});


test('the stencil is reachable, and the window reads the route that measures', () => {
	// The rule this file's neighbours were written for: a route with no caller is not a
	// feature. `POST /api/design/stencil` is the whole of the stencil, and it is reached
	// from exactly one place — the menu row — through one client method.
	const actions = src('lib', 'actions.ts');
	assert.match(actions, /id: 'stencil'/, 'the menu has no way to make a stencil');
	assert.match(actions, /action\.stencil/);

	const edits = src('lib', 'edits.svelte.ts');
	assert.match(edits, /'\/api\/design\/stencil'/, 'nothing calls the stencil route');

	// The window measures before it acts, and it measures on the same route with a flag
	// rather than on a second code path: a preview that is its own arithmetic is a preview
	// that can disagree with what happens.
	const dialog = src('lib', 'components', 'StencilDialog.svelte');
	assert.match(dialog, /onLook\(width, each\)/);
	assert.match(dialog, /onApply\(numbers\.bridge, numbers\.per\)/);
	const page = src('routes', '+page.svelte');
	assert.match(page, /edits\.stencil\(design\.selectedIds, bridgeMm, perIsland, true\)/);

	// And the crossing is written the way every other number in this app is written. `n` is
	// the plural selector and is the one value that does not go through `Intl`, so a
	// millimetre figure named `n` would print 3.6 to a reader whose canvas says 3,6.
	assert.match(dialog, /mm: i18n\.mm\(report\.shortest_mm\)/);
	assert.doesNotMatch(dialog, /crossing', \{ n:/);
});
