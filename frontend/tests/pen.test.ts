/**
 * The pen's numbers: what the preview draws is what the API gets.
 *
 * Run: `node --test frontend/tests/pen.test.ts`
 *
 * The trap this pins down is the direction of a handle. A point carries the handle you
 * dragged *out* of it, and the API reads a point's numbers as the segment *arriving* at
 * it — so the arriving control is the mirror. Get that backwards and every curve kinks at
 * the second point instead of running smoothly through it, which is exactly the thing a
 * pen exists to avoid.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { penPath, penPreview, type PenPoint } from '../src/lib/pen.ts';

const corner = (x: number, y: number): PenPoint => ({ x, y, handle: null });
const pulled = (x: number, y: number, hx: number, hy: number): PenPoint => ({
	x,
	y,
	handle: { x: hx, y: hy }
});

test('clicks only give a line of corners', () => {
	const rows = penPath([corner(10, 10), corner(60, 10), corner(60, 40)], false);

	assert.deepEqual(rows, [
		[10, 10],
		[60, 10],
		[60, 40]
	]);
});

test('a point with a handle makes a cubic, and the handle mirrors', () => {
	// Pulled 20 mm to the right out of (60,10): the segment arriving there must use the
	// mirror, 20 mm to the *left*.
	const rows = penPath([corner(10, 10), pulled(60, 10, 80, 10), corner(110, 10)], false);

	assert.deepEqual(rows[1], [60, 10, 10, 10, 40, 10]);
	assert.deepEqual(rows[2], [110, 10, 80, 10, 110, 10]);
});

test('a corner at one end of a curve puts its control on itself', () => {
	const rows = penPath([corner(0, 0), pulled(40, 0, 60, 20)], false);

	// The first control sits on the corner, so that end leaves along the chord.
	assert.deepEqual(rows[1], [40, 0, 0, 0, 20, -20]);
});

test('closing puts the last segment on the first point', () => {
	const rows = penPath([pulled(0, 0, 10, -10), corner(40, 0), corner(40, 30)], true);

	assert.equal(rows.length, 3);
	// The segment arriving at point one is a curve, because point one has a handle: its
	// arriving control is the mirror of (10,-10) about (0,0).
	assert.deepEqual(rows[0], [0, 0, 40, 30, -10, 10]);
	// And the segment *leaving* point one is a curve for the same reason, with the corner
	// it arrives at putting its control on itself.
	assert.deepEqual(rows[1], [40, 0, 10, -10, 40, 0]);
	assert.deepEqual(rows[2], [40, 30]);
});

test('a path of one point has nothing to draw', () => {
	assert.deepEqual(penPath([corner(5, 5)], false), []);
});

test('the preview draws the same line, including the piece under the pointer', () => {
	const d = penPreview([corner(10, 10), pulled(60, 10, 80, 10)], corner(110, 10));

	assert.equal(d, 'M 10 10 C 10 10 40 10 60 10 C 80 10 110 10 110 10');
});

test('the preview of a single point is just that point', () => {
	assert.equal(penPreview([corner(10, 10)], null), 'M 10 10');
});

test('a closed preview ends in Z', () => {
	const d = penPreview([corner(0, 0), corner(40, 0), corner(40, 30)], null, true);

	assert.equal(d, 'M 0 0 L 40 0 L 40 30 Z');
});
