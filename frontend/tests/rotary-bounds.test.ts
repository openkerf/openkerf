/**
 * The scale the form allows is the scale the machine layer allows.
 *
 * Run: `node --test frontend/tests/rotary-bounds.test.ts`. No browser, no engine.
 *
 * Why this exists: the bounds on the rotary's Y scale are written down twice —
 * SCALE_MIN/SCALE_MAX in frontend/src/lib/rotary.ts, so the form can grey out a
 * number before it is sent, and again in api/openkerf_api/rotary.py, which is the
 * authority. Two copies of one rule drift, and this pair drifts quietly: the form
 * would happily accept a factor the API then refuses, and the user reads a refusal
 * for something the interface just told them was fine.
 *
 * The API is the authority, so this test reads its numbers and holds the
 * frontend's against them. It is deliberately a comparison and not a duplicate of
 * the values: writing 0.5 and 2.0 here a third time would only move the problem.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { SCALE_MIN, SCALE_MAX } from '../src/lib/rotary.ts';

const here = dirname(fileURLToPath(import.meta.url));
const python = readFileSync(join(here, '..', '..', 'api', 'openkerf_api', 'rotary.py'), 'utf8');

/** A module-level float constant out of the API. */
function apiNumber(name: string): number {
	const found = python.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)\\s*$`, 'm'));
	assert.ok(found, `${name} is no longer a plain number in api/openkerf_api/rotary.py`);
	return Number(found[1]);
}

test('the form and the engine layer bound the rotary scale the same way', () => {
	assert.equal(
		SCALE_MIN,
		apiNumber('SCALE_MIN'),
		'the smallest scale the form allows is not the smallest the API allows'
	);
	assert.equal(
		SCALE_MAX,
		apiNumber('SCALE_MAX'),
		'the largest scale the form allows is not the largest the API allows'
	);
});

test('those bounds still bracket 1.0, which is "no correction"', () => {
	// A rotary whose Y already comes out right needs a factor of exactly 1, and that
	// is the default. Bounds that excluded it would refuse the commonest setting.
	assert.ok(SCALE_MIN < 1 && SCALE_MAX > 1, `${SCALE_MIN}–${SCALE_MAX} does not contain 1.0`);
});
