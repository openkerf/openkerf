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
import {
	DEFAULT_BRIDGES,
	bridgeSummary,
	elementCuts,
	type DesignElement,
	type DesignOperation
} from '../src/lib/design.svelte.ts';

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

/**
 * A layer, as thin as the answer needs it: an id and a type.
 *
 * The panel only asks what kind of burn the shape is in; speed, power and the rest of
 * `DesignOperation` say nothing about whether a gap in the cut does anything.
 */
function layer(id: string, type: string): DesignOperation {
	return { id, type } as DesignOperation;
}

/** How a caller that speaks about several shapes reads the per-shape answer. */
function notCut(elements: DesignElement[], operations: DesignOperation[]): number {
	return elements.filter((element) => !elementCuts(element, operations)).length;
}

test('bridges only do something in a cut layer', () => {
	// Why: the sentence under the tick used to be "No bridges: this shape comes loose the
	// moment the cut closes" for every shape without them — measured on the seeded design
	// at 1440 px, the same sentence under a rectangle in the engrave layer Caption, under
	// a shape in no layer at all, and under the one shape it was true of. Three of those
	// four readings were false.
	const cut = layer('c', 'op cut');
	const engrave = layer('e', 'op engrave');
	const inCut = { operation_ids: ['c'] } as DesignElement;
	const inEngrave = { operation_ids: ['e'] } as DesignElement;

	assert.equal(elementCuts(inCut, [cut, engrave]), true);
	assert.equal(elementCuts(inEngrave, [cut, engrave]), false);
});

test('a shape in no layer is not cut either', () => {
	// It burns nothing at all, so "this shape comes loose the moment the cut closes" is as
	// wrong there as in an engrave layer. Both spellings of no layer count.
	assert.equal(elementCuts({ operation_ids: [] } as unknown as DesignElement, []), false);
	assert.equal(elementCuts({} as DesignElement, []), false);
	// And nothing selected is nothing to claim about.
	assert.equal(notCut([], []), 0);
});

test('a layer we cannot see is not called an engraving', () => {
	// The panel judges from the layers it holds. If a shape names a layer that is not in
	// that list, the honest answer is the one that adds no sentence: saying "this shape is
	// not in a cut layer" about a layer nobody looked up would be a new false sentence.
	assert.equal(elementCuts({ operation_ids: ['gone'] } as DesignElement, []), true);
});

test('the question is asked about the shapes the sentence counts', () => {
	// The two halves of the block have to count the same shapes. `bridgeSummary` counts
	// only the carriers — a text or a line carries no bridge — so the layer question must
	// leave the others out too. With a text in the cut layer beside a rectangle in an
	// engrave layer, the carriers are the rectangle alone and every one of them is uncut,
	// which is the sentence that names no number. Asked over the whole selection instead,
	// one of two comes back uncut and the panel would say "1 of these 2 shapes", counting
	// a text that carries no bridge at all.
	const cut = layer('c', 'op cut');
	const engrave = layer('e', 'op engrave');
	const text = { ...shape(null, 'text'), operation_ids: ['c'] } as DesignElement;
	const rect = { ...shape({}, 'rect'), operation_ids: ['e'] } as DesignElement;
	const chosen = [text, rect];
	const carriers = chosen.filter((element) => element.bridges);

	assert.equal(bridgeSummary(chosen).shapes, 1);
	assert.equal(carriers.length, 1);
	assert.equal(notCut(carriers, [cut, engrave]), 1);
	assert.equal(notCut(chosen, [cut, engrave]), 1);
	assert.equal(chosen.length, 2);
});

test('a mixed selection is counted, not flattened into one of its halves', () => {
	// Why: one answer for the whole selection was true as soon as one shape of it cut, and
	// the panel used that answer for a plural sentence about all of them. Measured on the
	// seeded design at 1440 px with the rectangle in Outline and the rectangle in Fine
	// lines selected: "No bridges — small gaps that hold the part in the sheet — so these
	// 2 shapes come loose the moment the cut closes", while one of the two is engraved and
	// comes loose from nothing. So the panel asks the question per shape and counts the
	// answers.
	const cut = layer('c', 'op cut');
	const engrave = layer('e', 'op engrave');
	const inCut = { ...shape({}, 'a'), operation_ids: ['c'] } as DesignElement;
	const inEngrave = { ...shape({}, 'b'), operation_ids: ['e'] } as DesignElement;
	const noLayer = { ...shape({}, 'c'), operation_ids: [] } as DesignElement;

	assert.equal(elementCuts(inCut, [cut, engrave]), true);
	assert.equal(elementCuts(inEngrave, [cut, engrave]), false);
	assert.equal(elementCuts(noLayer, [cut, engrave]), false);

	assert.equal(notCut([inCut, inEngrave], [cut, engrave]), 1);
	assert.equal(notCut([inCut], [cut, engrave]), 0);
	assert.equal(notCut([inEngrave, noLayer], [cut, engrave]), 2);
});
