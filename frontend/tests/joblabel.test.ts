/**
 * The name of a job in the queue.
 *
 * Run: `node --test frontend/tests/joblabel.test.ts`.
 *
 * Why: "Show frame" spools a single movement, and the Job panel showed the label
 * the engine hands over for it — the repr of a Python tuple:
 * `('move_abs', 114.7544mm, 80.0mm)`. Measured on 0.9.9040 via `/api/devices` →
 * `spooler.jobs[0].label` during a frame job.
 *
 * The expected strings are English because English is the source language: with
 * no reactive module loaded, `core.t` reads the `en` catalogue. That is the same
 * fallback the static build uses, so this test pins that path too.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { jobLabel } from '../src/lib/api.ts';

const job = (label: string) => ({ label }) as Parameters<typeof jobLabel>[0];

test('a movement job shows no Python tuple', () => {
	const out = jobLabel(job("('move_abs', 114.7544mm, 80.0mm)"));
	assert.doesNotMatch(out, /[()']/, `still engine language: ${out}`);
	assert.doesNotMatch(out, /move_abs/, `still the command name: ${out}`);
	assert.equal(out, 'Move head to 114.7544mm × 80.0mm');
});

test('a tuple without a recognisable point keeps a readable name', () => {
	assert.equal(jobLabel(job("('home',)")), 'Go home');
	assert.equal(jobLabel(job("('rapid_mode',)")), 'Move head');
});

test('an unknown command is not hidden but is made readable', () => {
	assert.equal(jobLabel(job("('iets_nieuws', 1, 2, 3)")), 'Machine movement');
});

test('the existing translations stay put', () => {
	assert.equal(jobLabel(job('Spooler:3 items')), '3 operations');
	assert.equal(jobLabel(job('Spooler:1 item')), '1 operation');
	assert.equal(jobLabel(job('my design.svg')), 'my design.svg');
	assert.equal(jobLabel(job('')), 'Unnamed job');
	assert.equal(jobLabel(null), 'Unnamed job');
});

test('text that happens to look like a tuple is left alone', () => {
	assert.equal(jobLabel(job('(not really a tuple)')), '(not really a tuple)');
	assert.equal(jobLabel(job("plate ('oak') 3mm")), "plate ('oak') 3mm");
});
