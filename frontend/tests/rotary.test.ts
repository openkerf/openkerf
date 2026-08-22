/**
 * The rotary's arithmetic, the half of it the interface computes.
 *
 * Run: `node --test frontend/tests/rotary.test.ts`
 *
 * Every function here has a twin in `api/openkerf_api/rotary.py`, which uses the engine's
 * own `rotary_cam.py`. The numbers below are the same ones the API tests assert, on purpose:
 * if the two ever drift apart, the form would promise a factor the machine does not use —
 * and a user who is shown 1.0363 before saving and gets something else afterwards has no
 * way of telling which number burned.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	ROTARY_OFF,
	SCALE_MAX,
	SCALE_MIN,
	burnedHeightMm,
	calibrationFactor,
	circumferenceMm,
	goesRound,
	scaleIsSane,
	stepsFactor
} from '../src/lib/rotary.ts';

test('a chuck knows its circumference from the diameter, a roller carries it itself', () => {
	assert.equal(
		circumferenceMm({ kind: 'chuck', diameter_mm: 80, circumference_mm: 0 }),
		Math.PI * 80
	);
	// 251.3274 mm — the number the API reports for the same chuck.
	assert.ok(Math.abs(circumferenceMm({ kind: 'chuck', diameter_mm: 80, circumference_mm: 0 }) - 251.3274) < 1e-4);
	assert.equal(circumferenceMm({ kind: 'roller', diameter_mm: 80, circumference_mm: 189.5 }), 189.5);
	// Nothing filled in is not a circumference of zero-and-therefore-fine: it is
	// unknown, and the caller has to see the difference. Zero is that signal.
	assert.equal(circumferenceMm({ kind: 'chuck', diameter_mm: 0, circumference_mm: 200 }), 0);
});

test('"meant 100, measured 96.5" gives 1.036269', () => {
	const factor = calibrationFactor(1, 100, 96.5);
	assert.ok(Math.abs(factor - 1.036269) < 1e-6, `got ${factor}`);
});

test('calibrating again builds on the factor that is already in', () => {
	const first = calibrationFactor(1, 100, 96.5);
	const second = calibrationFactor(first, 100, 99.5);
	assert.ok(Math.abs(second - first * (100 / 99.5)) < 1e-9);
	// And it converges: the second correction is much smaller than the first.
	assert.ok(second - first < first - 1);
});

test('a measurement that is missing changes nothing', () => {
	assert.equal(calibrationFactor(1.25, 100, 0), 1.25);
	assert.equal(calibrationFactor(1.25, 0, 100), 1.25);
	assert.equal(calibrationFactor(1.25, 100, -5), 1.25);
});

test('the steps factor is the flat bed over the rotary', () => {
	assert.equal(stepsFactor(80, 64), 1.25);
	// Either number missing means no correction, not a division by zero.
	assert.equal(stepsFactor(80, 0), 1);
	assert.equal(stepsFactor(0, 64), 1);
});

test('a calibration lives near 1; beyond that it is a resize', () => {
	assert.equal(scaleIsSane(1), true);
	assert.equal(scaleIsSane(1.036269), true);
	assert.equal(scaleIsSane(SCALE_MIN), true);
	assert.equal(scaleIsSane(SCALE_MAX), true);
	assert.equal(scaleIsSane(3), false);
	assert.equal(scaleIsSane(0.2), false);
	assert.equal(scaleIsSane(Number.NaN), false);
});

test('the drawing is the truth: without a correction 30 mm burns 30 mm', () => {
	assert.equal(burnedHeightMm(30, 1), 30);
	// This is the whole reason we do not use `wrap_scale_y`: on this bed that factor is
	// 0.618424, and the same 30 mm logo would come off the cup at 18.55 mm while the
	// canvas kept saying 30.
	assert.ok(Math.abs(burnedHeightMm(30, 251.3274 / 406.4) - 18.55) < 0.01);
	assert.ok(Math.abs(burnedHeightMm(100, 1.036269) - 103.6269) < 1e-4);
});

test('going round is only answered when both numbers are known', () => {
	// A chuck of 60 mm is 188.5 mm round.
	assert.equal(goesRound(100, 1, 188.5), true);
	assert.equal(goesRound(300, 1, 188.5), false);
	// And the scale counts: work that fits flat can overflow once it is stretched.
	assert.equal(goesRound(185, 1, 188.5), true);
	assert.equal(goesRound(185, 1.036269, 188.5), false);
	assert.equal(goesRound(null, 1, 188.5), null, 'nothing on the bed');
	assert.equal(goesRound(100, 1, 0), null, 'an object we have no measurement for');
});

test('the off state is off, and its scale is exactly one', () => {
	assert.equal(ROTARY_OFF.active, false);
	assert.equal(ROTARY_OFF.scale_y, 1);
	assert.equal(ROTARY_OFF.scale_x, 1);
	// A rotary that reports itself as on because a fetch failed would refuse homing on a
	// flat bed. The default has to be the harmless one.
	assert.equal(ROTARY_OFF.kind, 'chuck');
});
