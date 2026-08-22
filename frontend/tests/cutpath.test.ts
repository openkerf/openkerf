/**
 * The arithmetic behind the cut-path window.
 *
 * Run: `node --test frontend/tests/cutpath.test.ts`
 *
 * What is pinned here is the model, not the looks: that a travel move is the gap
 * between two steps and not a step, that the head is in the right place at any
 * moment of the clock, that a curve stays a curve, and that the scrubber's lookup
 * does not walk the whole list. Those are the four things a wrong preview would
 * get wrong quietly — it would still look like a picture of your work.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	contourCount,
	contourStarts,
	contours,
	donePaths,
	endOf,
	headAt,
	indexAt,
	startOf,
	stepPath,
	travelPath,
	travelShare,
	type PathStep
} from '../src/lib/cutpath.ts';

/** A square of 10 mm at (0,0), cut clockwise: four steps, no travel between them. */
function square(at = 0, op = 'L1', from = 0): PathStep[] {
	const corners: [number, number][] = [
		[at, at],
		[at + 10, at],
		[at + 10, at + 10],
		[at, at + 10],
		[at, at]
	];
	return corners.slice(0, 4).map((corner, i) => ({
		k: 'cut' as const,
		op,
		x0: corner[0],
		y0: corner[1],
		x1: corners[i + 1][0],
		y1: corners[i + 1][1],
		t0: from + i,
		t1: from + i,
		t2: from + i + 1,
		...(i === 0 ? { f: true } : {})
	}));
}

test('a step becomes the line it burns', () => {
	const [step] = square();
	assert.equal(stepPath(step), 'M0 0L10 0');
});

test('a curve keeps its curve', () => {
	const cubic: PathStep = {
		k: 'cut',
		op: 'L1',
		x0: 0,
		y0: 0,
		x1: 10,
		y1: 0,
		c: [2, 5, 8, 5],
		t0: 0,
		t1: 0,
		t2: 1
	};
	const quad: PathStep = { ...cubic, c: [5, 5] };

	assert.equal(stepPath(cubic), 'M0 0C2 5 8 5 10 0');
	assert.equal(stepPath(quad), 'M0 0Q5 5 10 0');
});

test('a raster is the box it sweeps, not the line between its ends', () => {
	// The engine gives a raster one start and one end — the first and last scan
	// position — and drawing the line between them would put a diagonal across the
	// image. What burns is the box.
	const raster: PathStep = {
		k: 'raster',
		op: 'L2',
		x0: 100,
		y0: 20,
		w: 40,
		h: 30,
		sx: 100,
		sy: 50,
		ex: 140,
		ey: 20,
		t0: 0,
		t1: 1,
		t2: 300
	};

	assert.equal(stepPath(raster), 'M100 20h40v30h-40Z');
	// And the head still enters and leaves where the plan says it does.
	assert.deepEqual(startOf(raster), [100, 50]);
	assert.deepEqual(endOf(raster), [140, 20]);
});

test('travel is the gap between two steps and nothing else', () => {
	// One square: the head never lifts, so there is nothing to draw. Two squares
	// 30 mm apart: exactly one jump.
	assert.equal(travelPath(square()), '');

	const two = [...square(0), ...square(30, 'L1', 4)];
	assert.equal(travelPath(two), 'M0 0L30 30');
});

test('the head travels first and burns after', () => {
	const steps: PathStep[] = [
		{ k: 'cut', op: 'L1', x0: 10, y0: 0, x1: 20, y1: 0, t0: 0, t1: 2, t2: 4 }
	];

	// Halfway through the travel: half of the way from the origin to the start.
	assert.deepEqual(headAt(steps, 1), { x: 10, y: 0, travelling: true });
	// The first step travels from its own start (there is no previous), so the
	// travelling flag is what carries the information, not the movement.
	assert.equal(headAt(steps, 3)?.travelling, false);
	assert.deepEqual(headAt(steps, 3), { x: 15, y: 0, travelling: false });
	// Past the end it stands where it finished.
	assert.deepEqual(headAt(steps, 99), { x: 20, y: 0, travelling: false });
	assert.equal(headAt([], 1), null);
});

test('the head is on its way between two shapes', () => {
	const steps = [...square(0), ...square(30, 'L1', 4)];
	// The first square closes back at (0,0); the second starts at (30,30). The jump
	// between them gets a travel of its own, because `square` gives every step
	// t0 == t1 (no travel within a contour).
	steps[4] = { ...steps[4], t0: 4, t1: 6, t2: 7 };

	const half = headAt(steps, 5);

	assert.equal(half?.travelling, true);
	assert.equal(half?.x, 15);
	assert.equal(half?.y, 15);
});

test('the index at a moment is found without walking the list', () => {
	const steps = square();

	assert.equal(indexAt(steps, 0), 0);
	assert.equal(indexAt(steps, 1), 1);
	assert.equal(indexAt(steps, 2.5), 2);
	assert.equal(indexAt(steps, 100), 4);

	// A thousand steps and the search must not touch them all: the scrubber asks
	// this on every frame.
	const many: PathStep[] = Array.from({ length: 1000 }, (_, i) => ({
		k: 'cut',
		op: 'L1',
		x0: i,
		y0: 0,
		x1: i + 1,
		y1: 0,
		t0: i,
		t1: i,
		t2: i + 1
	}));
	let touched = 0;
	const watched = new Proxy(many, {
		get(target, key) {
			if (typeof key === 'string' && /^\d+$/.test(key)) touched += 1;
			return Reflect.get(target, key);
		}
	});
	assert.equal(indexAt(watched as PathStep[], 500), 500);
	assert.ok(touched < 20, `binary search touched ${touched} steps`);
});

test('what is already burned is one path per layer', () => {
	const steps = [...square(0, 'L1'), ...square(30, 'L2', 4)];
	const fragments = steps.map(stepPath);

	const halfway = donePaths(steps, fragments, 5);

	assert.deepEqual([...halfway.keys()], ['L1', 'L2']);
	assert.equal(halfway.get('L1'), fragments.slice(0, 4).join(''));
	assert.equal(halfway.get('L2'), fragments[4]);
	assert.equal(donePaths(steps, fragments, 0).size, 0);
});

test('every contour is counted once and numbered in cut order', () => {
	const steps = [...square(0, 'L1'), ...square(30, 'L1', 4)];

	assert.equal(contourCount(steps), 2);
	assert.deepEqual(contourStarts(steps), [
		{ n: 1, x: 0, y: 0, t: 0, more: 0 },
		{ n: 2, x: 30, y: 30, t: 4, more: 0 }
	]);
});

test('a contour with passes is one contour with one number', () => {
	// The case that made the drawing unreadable: the plan walks the same rectangle once
	// per pass, so it came back with `f` three times and was numbered 1, 3 and 5 at the
	// identical spot (measured on the gauntlet seed: three boxes at x 406.0, y 192.9).
	// Three passes is not three shapes.
	const steps = [
		...square(0, 'L1', 0),
		...square(30, 'L1', 4),
		...square(0, 'L1', 8),
		...square(30, 'L1', 12),
		...square(0, 'L1', 16),
		...square(30, 'L1', 20)
	];

	const list = contours(steps);

	assert.equal(list.length, 2);
	assert.deepEqual(
		list.map((c) => [c.n, c.x, c.y, c.passes, c.w, c.h]),
		[
			[1, 0, 0, 3, 10, 10],
			[2, 30, 30, 3, 10, 10]
		]
	);
	// And the numbers on the drawing follow: two, and the clock of the *first* time.
	assert.deepEqual(
		contourStarts(steps).map((m) => [m.n, m.t]),
		[
			[1, 0],
			[2, 4]
		]
	);
	assert.equal(contourCount(steps), 2);
});

test('a flag in the middle of a continuous burn is not a new contour', () => {
	// The engine's own `first` flag does not mean "a new shape". Measured on the
	// gauntlet seed: a circle of r=30 came out of the plan as two runs of six
	// segments with the flag on the *second* one and nothing on its first segment, so
	// counting flags gave the rectangle before it a contour of 205 x 80 mm (it is
	// 120 x 80) and the bottom half of the circle a number of its own. A contour is
	// one continuous burn: the gap is what counts, not the flag.
	const steps: PathStep[] = [
		{ k: 'cut', op: 'L1', x0: 0, y0: 0, x1: 10, y1: 0, t0: 0, t1: 0, t2: 1, f: true },
		{ k: 'cut', op: 'L1', x0: 10, y0: 0, x1: 20, y1: 0, t0: 1, t1: 1, t2: 2 },
		// Continues where the last one ended, and still carries the flag.
		{ k: 'cut', op: 'L1', x0: 20, y0: 0, x1: 30, y1: 0, t0: 2, t1: 2, t2: 3, f: true },
		// This one arrives somewhere else: that is a new contour.
		{ k: 'cut', op: 'L1', x0: 60, y0: 0, x1: 70, y1: 0, t0: 3, t1: 5, t2: 6 }
	];

	const list = contours(steps);

	assert.equal(list.length, 2);
	assert.deepEqual(
		list.map((c) => [c.n, c.x, c.w]),
		[
			[1, 0, 30],
			[2, 60, 10]
		]
	);
});

test('a contour keeps its own size, whatever way it runs', () => {
	// A shape that runs left of and above the point it starts at: its size is not the
	// distance from its start, and the list beside the drawing says the size out loud.
	const steps: PathStep[] = [
		{ k: 'cut', op: 'L1', x0: 50, y0: 50, x1: 20, y1: 50, t0: 0, t1: 0, t2: 1, f: true },
		{ k: 'cut', op: 'L1', x0: 20, y0: 50, x1: 20, y1: 30, t0: 1, t1: 1, t2: 2 }
	];

	const [contour] = contours(steps);

	assert.equal(contour.w, 30);
	assert.equal(contour.h, 20);
});

test('a number that would land on another is folded into it', () => {
	// Eighteen letters of a caption started inside a band of 96 x 29 px on the gauntlet
	// seed, and eighteen numbers there answer nothing. The lowest number stays — the
	// question is which comes first — and it carries how many it stands for.
	const steps: PathStep[] = [1, 2, 3, 4].flatMap((i) => [
		{
			k: 'cut' as const,
			op: 'L1',
			// A tenth of a millimetre apart: four different contours in one spot.
			x0: 10 + i * 0.1,
			y0: 10,
			x1: 10 + i * 0.1,
			y1: 10.5,
			t0: i,
			t1: i,
			t2: i + 1,
			f: true
		}
	]);

	const marks = contourStarts(steps, { box: { char: 2, height: 3, dx: 1, dy: -1 } });

	assert.equal(marks.length, 1);
	assert.equal(marks[0].n, 1);
	assert.equal(marks[0].more, 3);
	// The contours themselves are all still there, in order, for the list in words.
	assert.equal(contours(steps).length, 4);
});

test('numbers that stand clear of each other are all drawn', () => {
	const steps = [...square(0, 'L1'), ...square(30, 'L1', 4), ...square(60, 'L1', 8)];

	const marks = contourStarts(steps, { box: { char: 2, height: 5, dx: 1, dy: -1 } });

	assert.deepEqual(
		marks.map((m) => m.n),
		[1, 2, 3]
	);
	assert.equal(
		marks.every((m) => m.more === 0),
		true
	);
});

test('too many contours to number are not numbered at all', () => {
	// A hundred and fifty numbers over a bed is a texture, not an order. Then the
	// window says how many there are instead of drawing them all.
	// Every line stands apart from the one before it: a contour is one continuous
	// burn, so lines laid end to end would be one contour and not a hundred and fifty.
	const many: PathStep[] = Array.from({ length: 150 }, (_, i) => ({
		k: 'cut',
		op: 'L1',
		x0: i * 3,
		y0: 0,
		x1: i * 3 + 1,
		y1: 0,
		t0: i,
		t1: i,
		t2: i + 1,
		f: true
	}));

	assert.equal(contourCount(many), 150);
	assert.deepEqual(contourStarts(many), []);
});

test('the travel share is the number that says the order is wrong', () => {
	const steps: PathStep[] = [
		{ k: 'cut', op: 'L1', x0: 0, y0: 0, x1: 1, y1: 0, t0: 0, t1: 0, t2: 6 },
		{ k: 'cut', op: 'L1', x0: 9, y0: 0, x1: 10, y1: 0, t0: 6, t1: 8, t2: 10 }
	];

	assert.equal(travelShare(steps), 0.2);
	assert.equal(travelShare([]), 0);
});
