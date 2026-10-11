/**
 * What a drag box selects, and which shape a click under a pile takes.
 *
 * Run: `node --test frontend/tests/selecting.test.ts`
 *
 * The case that started it, from a real design: blue filled text (engraved on a raster
 * layer) inside red rectangular outlines (cut, no fill). Until now the drag box selected
 * by *overlapping bounding boxes*, so a box drawn around the text — even one wholly in
 * the empty middle of the outline — took the outline with it, in either direction.
 * `bounds` and paths below are in the design's units, as the canvas passes them.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	bandMode,
	bandSelection,
	boxOf,
	distanceTo,
	enclosed,
	flatten,
	pickAt,
	segmentTouchesBox,
	touched,
	type Selectable
} from '../src/lib/selecting.ts';

const rect = (id: string, x0: number, y0: number, x1: number, y1: number, face = false): Selectable => ({
	id,
	bounds: [x0, y0, x1, y1],
	path: `M ${x0},${y0} L ${x1},${y0} L ${x1},${y1} L ${x0},${y1} Z`,
	face
});

// A cut outline 0..100 × 0..60, and two engraved letters inside it.
const outline = rect('outline', 0, 0, 100, 60);
const letterA = rect('A', 20, 20, 30, 40, true);
const letterB = rect('B', 35, 20, 45, 40, true);
const design = [letterA, letterB, outline];

test('left to right is a window, right to left a crossing box', () => {
	assert.equal(bandMode(10, 50), 'window');
	assert.equal(bandMode(50, 10), 'crossing');
	// A purely vertical drag has not gone left: a window.
	assert.equal(bandMode(10, 10), 'window');
});

test('a window around the text inside an outline takes the text and not the outline', () => {
	const box = boxOf(15, 15, 50, 45);
	assert.deepEqual(bandSelection(box, 'window', design), ['A', 'B']);
});

test('a crossing box in the empty middle of an outline does not touch the outline', () => {
	// Covers letter A partly, and lies wholly inside the outline without reaching its lines.
	const box = boxOf(25, 25, 32, 35);
	assert.deepEqual(bandSelection(box, 'crossing', design), ['A']);
});

test('a crossing box over the outline line takes the outline', () => {
	const box = boxOf(90, 20, 110, 30);
	assert.deepEqual(bandSelection(box, 'crossing', design), ['outline']);
});

test('a window that does not enclose the outline leaves it out even when it crosses its line', () => {
	const box = boxOf(-10, 10, 50, 50);
	assert.deepEqual(bandSelection(box, 'window', design), ['A', 'B']);
});

test('a window around everything takes everything', () => {
	assert.deepEqual(bandSelection(boxOf(-1, -1, 101, 61), 'window', design), ['A', 'B', 'outline']);
});

test('a crossing box inside a filled face touches that face', () => {
	const panel = rect('panel', 0, 0, 100, 60, true);
	assert.equal(touched(boxOf(40, 20, 50, 30), panel), true);
	// …but not inside an outline of the same shape.
	assert.equal(touched(boxOf(40, 20, 50, 30), rect('line', 0, 0, 100, 60)), false);
});

test('an image is touched by its whole picture', () => {
	const image: Selectable = { id: 'img', bounds: [0, 0, 50, 50], path: null, face: true };
	assert.equal(touched(boxOf(10, 10, 20, 20), image), true);
	assert.equal(enclosed(boxOf(10, 10, 20, 20), image), false);
});

test('hidden shapes are left out', () => {
	const ghost = { ...letterA, id: 'ghost', hidden: true };
	assert.deepEqual(bandSelection(boxOf(0, 0, 200, 200), 'window', [ghost, letterB]), ['B']);
});

test('a window takes a group only when all of it lies inside', () => {
	const g1 = { ...letterA, group_id: 'g' };
	const g2 = { ...rect('far', 200, 200, 210, 210), group_id: 'g' };
	assert.deepEqual(bandSelection(boxOf(15, 15, 50, 45), 'window', [g1, g2, letterB]), ['B']);
	// A crossing box takes it as soon as one member is touched; `selectMany` adds the rest.
	assert.deepEqual(bandSelection(boxOf(15, 15, 50, 45), 'crossing', [g1, g2, letterB]), ['A', 'B']);
});

test('a curve is followed, not its control polygon', () => {
	// A circle of radius 50 around 50,50 in four cubic arcs.
	const k = 50 * 0.5523;
	const circle: Selectable = {
		id: 'c',
		bounds: [0, 0, 100, 100],
		path: `M 100,50 C 100,${50 + k} ${50 + k},100 50,100 C ${50 - k},100 0,${50 + k} 0,50 C 0,${50 - k} ${50 - k},0 50,0 C ${50 + k},0 100,${50 - k} 100,50 Z`
	};
	// The corner of the bounding box lies outside the circle: a box there touches nothing.
	assert.equal(touched(boxOf(0, 0, 10, 10), circle), false);
	assert.equal(touched(boxOf(95, 45, 105, 55), circle), true);
});

test('the path grammar: relative commands, H, V, arcs', () => {
	const lines = flatten('m 10,10 h 20 v 20 H 10 z');
	assert.deepEqual(lines[0][0], [10, 10]);
	assert.deepEqual(lines[0][2], [30, 30]);
	assert.deepEqual(lines[0].at(-1), [10, 10]);
	// A half circle from 0,0 to 20,0 reaches 10 units from the chord.
	const arc = flatten('M 0,0 A 10,10 0 0 1 20,0')[0];
	assert.deepEqual(arc.at(-1), [20, 0]);
	const ys = arc.map((p) => p[1]);
	assert.ok(Math.abs(Math.max(...ys.map(Math.abs)) - 10) < 0.01);
});

test('segment against box', () => {
	const box = boxOf(0, 0, 10, 10);
	assert.equal(segmentTouchesBox(box, -5, 5, 15, 5), true);
	assert.equal(segmentTouchesBox(box, -5, -5, -1, 20), false);
	assert.equal(segmentTouchesBox(box, -5, 12, 12, -5), true);
	assert.equal(segmentTouchesBox(box, -5, 20, 20, 16), false);
});

test('a click on a letter inside an outline takes the letter, even in the outline hit zone', () => {
	// The outline is drawn after the text, so it is topmost; its hit zone is 12 px wide.
	// A letter close to the outline's line, and a click on that letter 3 units from the line.
	const near = rect('near', 2, 20, 10, 40, true);
	assert.equal(pickAt([outline, near], 3, 30, 1), 'near');
	// Exactly on the line, beside the letter: the outline.
	assert.equal(pickAt([outline, near], 0, 10, 1), 'outline');
});

test('a click picks the one under the pointer before a smaller neighbour merely nearby', () => {
	// Pixel-font text: little squares side by side, each within the other's hit zone.
	const a = rect('a', 0, 0, 1, 1, true);
	const b = rect('b', 1.2, 0, 1.6, 0.4, true);
	assert.equal(pickAt([b, a], 0.5, 0.5, 0.05), 'a');
});

test('equally near: the smallest, then the topmost', () => {
	const panel = rect('panel', 0, 0, 100, 60, true);
	const hole = rect('hole', 40, 20, 60, 40);
	// On the hole's line, on the panel's face: both at distance 0, the hole is smaller.
	assert.equal(pickAt([panel, hole], 40, 30, 1), 'hole');
	const twin = { ...hole, id: 'twin' };
	assert.equal(pickAt([twin, hole], 40, 30, 1), 'twin');
	assert.equal(distanceTo(hole, 50, 30), 10);
	assert.equal(distanceTo(panel, 50, 30), 0);
});
