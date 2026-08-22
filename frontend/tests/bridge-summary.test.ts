/**
 * One answer about the bridges on a selection, read by three surfaces.
 *
 * Run: `node --test frontend/tests/bridge-summary.test.ts`
 *
 * The menu row (offer them or take them away), the shortcut and the panel fields all
 * ask the same question: what has this selection got? Same pattern as `actions.ts` and
 * `jobPhase` — where more than one place has to know the same thing, it is worked out
 * once. What is pinned down here is the two answers that are easy to get wrong: a
 * selection whose shapes disagree, and bridges that sit at places of their own instead
 * of spread evenly. A count alone would then be a lie about where they are.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_BRIDGES, bridgeSummary, type DesignElement } from '../src/lib/design.svelte.ts';

/** A shape with the bridges block the API sends, or `null` for a type that carries none. */
function shape(
	bridges: Partial<NonNullable<DesignElement['bridges']>> | null,
	id = 'a'
): DesignElement {
	return {
		id,
		bridges: bridges && {
			count: 0,
			length_mm: 2,
			positions_percent: [],
			path_length_mm: 200,
			path: '',
			...bridges
		}
	} as DesignElement;
}

/** The even spread the engine gives for `"*N"`: (i + 0.5) × 100 / N. */
const even = (n: number) => Array.from({ length: n }, (_, i) => ((i + 0.5) * 100) / n);

test('nothing selected, or nothing that carries bridges', () => {
	for (const selection of [[], [shape(null)]]) {
		const summary = bridgeSummary(selection);
		assert.equal(summary.carries, false);
		assert.equal(summary.has, false);
		assert.equal(summary.count, DEFAULT_BRIDGES.count);
		assert.equal(summary.lengthMm, DEFAULT_BRIDGES.lengthMm);
	}
});

test('a shape that can carry them but has none offers the default', () => {
	const summary = bridgeSummary([shape({})]);

	assert.equal(summary.carries, true);
	assert.equal(summary.has, false);
	assert.equal(summary.count, DEFAULT_BRIDGES.count);
	assert.equal(summary.shortestMm, 200);
});

test('the count and the length are read back off the shape', () => {
	const summary = bridgeSummary([
		shape({ count: 4, length_mm: 2.5, positions_percent: even(4) })
	]);

	assert.equal(summary.has, true);
	assert.equal(summary.mixed, false);
	assert.equal(summary.count, 4);
	assert.equal(summary.lengthMm, 2.5);
	// Spread evenly, so the count says it all and a list of percentages would be noise.
	assert.equal(summary.places, null);
});

test('places of their own are shown as places, not as a count', () => {
	const summary = bridgeSummary([
		shape({ count: 3, length_mm: 2, positions_percent: [10, 50, 90] })
	]);

	assert.deepEqual(summary.places, [10, 50, 90]);
});

test('shapes that disagree say so, so a number typed here levels them knowingly', () => {
	const differentCount = bridgeSummary([
		shape({ count: 4, positions_percent: even(4) }, 'a'),
		shape({ count: 6, positions_percent: even(6) }, 'b')
	]);
	assert.equal(differentCount.mixed, true);

	const differentLength = bridgeSummary([
		shape({ count: 4, length_mm: 2, positions_percent: even(4) }, 'a'),
		shape({ count: 4, length_mm: 3, positions_percent: even(4) }, 'b')
	]);
	assert.equal(differentLength.mixed, true);

	// One with and one without is a disagreement too — the switch would otherwise read as
	// "they all have them".
	const half = bridgeSummary([
		shape({ count: 4, positions_percent: even(4) }, 'a'),
		shape({}, 'b')
	]);
	assert.equal(half.mixed, true);
	assert.equal(half.has, true);
});

test('two shapes that agree are not mixed, and never show a list of places', () => {
	const summary = bridgeSummary([
		shape({ count: 4, length_mm: 2, positions_percent: even(4) }, 'a'),
		shape({ count: 4, length_mm: 2, positions_percent: even(4) }, 'b')
	]);

	assert.equal(summary.mixed, false);
	// Even if those places were explicit: with two shapes there is no single contour to
	// name percentages of, so the panel keeps to the count.
	assert.equal(summary.places, null);
});

test('the shortest contour is the one that decides', () => {
	// The API refuses per shape: the bridges may take at most half of *that* shape's path.
	// So the panel has to judge a typed length against the shortest one in the selection.
	const summary = bridgeSummary([
		shape({ path_length_mm: 200 }, 'a'),
		shape({ path_length_mm: 62.8 }, 'b')
	]);

	assert.equal(summary.shortestMm, 62.8);
});

test('how many shapes, and whether they share one contour', () => {
	// The read-back sentence quotes the shortest contour, which is the honest one — it is
	// the bound the API trips over first — but it may only say "a contour" when there is
	// one. Measured before this with a 200 mm rectangle and a 125.7 mm circle selected:
	// "spread over a contour of 125.7 mm" and the rectangle went unmentioned.
	const mixedSizes = bridgeSummary([
		shape({ count: 6, positions_percent: even(6), path_length_mm: 200 }, 'a'),
		shape({ count: 6, positions_percent: even(6), path_length_mm: 125.7 }, 'b')
	]);
	assert.equal(mixedSizes.shapes, 2);
	assert.equal(mixedSizes.sameContour, false);

	const sameSize = bridgeSummary([
		shape({ count: 6, positions_percent: even(6), path_length_mm: 200 }, 'a'),
		shape({ count: 6, positions_percent: even(6), path_length_mm: 200 }, 'b')
	]);
	assert.equal(sameSize.shapes, 2);
	assert.equal(sameSize.sameContour, true);

	// One shape is always one contour, and nothing that carries them is none.
	assert.equal(bridgeSummary([shape({})]).sameContour, true);
	assert.equal(bridgeSummary([]).shapes, 0);
});
