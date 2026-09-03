/**
 * The phase of the job: one derivation for every surface.
 *
 * Run: `node --test frontend/tests/jobphase.test.ts`
 *
 * Why this is pinned down. Before this round every surface read its own field to
 * decide whether work was under way — the top bar the machine state, the Job
 * panel `job.running`, the spooler card `job.status`. Measured with a job that had
 * been spooled but not picked up (`status: "Waiting"`, `running: false`,
 * `progress: 0`): the top bar disabled starting and the panel left it enabled. One
 * tap there spooled a second job on top of the first.
 *
 * This pins the cases where those four fields contradict each other.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { burnsNothing } from '../src/lib/design.svelte.ts';
import {
	jobBusy,
	jobPhase,
	jobStatusLabel,
	mayLeaveWorkArea,
	phaseBody,
	phaseTitle,
	transportAllowed
} from '../src/lib/api.ts';

function job(over: Record<string, unknown> = {}) {
	return {
		label: 'Sheet 1',
		type: 'LaserJob',
		status: 'Waiting',
		priority: 0,
		running: false,
		paused: false,
		steps_done: 0,
		steps_total: 287,
		progress: 0,
		loops_executed: 0,
		loops: 1,
		elapsed_seconds: 0,
		estimate_seconds: 298,
		...over
	} as NonNullable<Parameters<typeof jobPhase>[1]>;
}

const noDevice = null;

test('without a job the phase hangs on the bed', () => {
	assert.equal(jobPhase(noDevice, null, true), 'nothing');
	assert.equal(jobPhase(noDevice, null, false), 'ready');
});

test('spooled but not picked up is "queued", not "paused"', () => {
	// This is the case the surfaces drifted apart on: `running` is false,
	// `progress` zero, and yet there is work under way.
	const phase = jobPhase(noDevice, job(), false);
	assert.equal(phase, 'queued');
	assert.equal(jobBusy(phase), true, 'work is under way, so starting must be refused');
});

test('a running job burns', () => {
	const phase = jobPhase(noDevice, job({ running: true, status: 'Running', progress: 0.4 }), false);
	assert.equal(phase, 'burning');
	assert.equal(jobBusy(phase), true);
});

test('a job that has started and stands still is paused', () => {
	// `running` goes false on Lihuiyu the moment you pause, without the status
	// field saying so. Started + still = paused; nothing done yet = queued.
	assert.equal(jobPhase(noDevice, job({ progress: 0.3, elapsed_seconds: 12 }), false), 'paused');
});

test("the driver's pause flag is enough", () => {
	assert.equal(jobPhase(noDevice, job({ paused: true }), false), 'paused');
});

test('practically at a hundred per cent and still means done', () => {
	// `calc_steps` counts one step more than `execute` carries out, so the progress
	// reaches 0.998 and the job stays in the queue as "Waiting". Reading that as
	// "standing still" is exactly the message you do not want under finished work.
	const phase = jobPhase(
		noDevice,
		job({ progress: 0.998, steps_done: 286, elapsed_seconds: 240 }),
		false
	);
	assert.equal(phase, 'done');
	assert.equal(jobBusy(phase), false, 'a finished job must not block the machine');
});

test('every phase has a title and an explanation, and they say something', () => {
	for (const phase of ['nothing', 'ready', 'queued', 'burning', 'paused', 'done'] as const) {
		const title = phaseTitle(phase);
		const body = phaseBody(phase);
		assert.ok(title.length > 3, `${phase}: title too short`);
		assert.ok(body.length > 20, `${phase}: explanation says nothing`);
		assert.ok(!/^[a-z]/.test(title), `${phase}: title starts with a lower-case letter`);
		assert.ok(!title.includes('.'), `${phase}: title is a key, not a sentence: ${title}`);
	}
});

test('"queued" explains that nothing has hung', () => {
	// The whole reason this phase has a name of its own: "Waiting" is
	// indistinguishable from "it has stopped doing anything" for a user.
	assert.match(phaseBody('queued'), /not picked it up/);
	assert.match(phaseBody('queued'), /connection/);
});

test('"done" says why the job stays in the queue', () => {
	assert.match(phaseBody('done'), /queue/);
});

test('Waiting is not passed through as the engine wrote it', () => {
	// This one fell through every branch of `jobStatusLabel` and reached the screen
	// unfiltered — the one word in the Job tab that was not in the catalogue.
	assert.equal(jobStatusLabel(job({ status: 'Waiting' })), 'In the queue');
	assert.equal(jobStatusLabel(job({ status: 'Queued' })), 'In the queue');
	assert.equal(jobStatusLabel(job({ status: 'Running', running: true })), 'Busy');
	assert.equal(jobStatusLabel(job({ status: 'Paused' })), 'Paused');
});

test('the route out of the work area closes while the machine is burning', () => {
	// The machine chip in the top left is a link to the setup, and `routes/setup/` has
	// no stop button and no key handler: `Stop`, `transport` and `onStop` give zero
	// hits there. So one click on your own machine name during a job took away both
	// the button and the shortcut, and the way back is a second click.
	//
	// The phases where something is really under way are the phases where you must
	// stay. `jobBusy` already knows which those are; this is the same list, read as a
	// question about leaving rather than about stopping.
	for (const phase of ['burning', 'paused', 'queued'] as const) {
		assert.equal(mayLeaveWorkArea(phase), false, `${phase} let the user walk away from the stop`);
	}
	for (const phase of ['idle', 'ready', 'nothing', 'done'] as const) {
		assert.equal(mayLeaveWorkArea(phase), true, `${phase} kept the user in`);
	}
});

test('"nothing to burn" is one question, asked of the design', () => {
	// The top bar and the Job panel both call `jobPhase`, and the comment above each
	// call says it is the same source. It was not: the page passed `design.isEmpty`
	// (`elements.length === 0`) and the panel passed `estimate.parts === 0`. Those two
	// differ exactly when shapes are lying there that will not burn — every layer
	// switched off, or everything in a layer that does not go along. The bar then said
	// "ready" while the panel said "nothing", about one bed.
	//
	// `burnsNothing` asks the design itself, so it needs no estimate and cannot flip
	// while one is being recalculated.
	const op = (over: Record<string, unknown> = {}) => ({
		output: true,
		element_ids: ['a'],
		...over
	});
	assert.equal(burnsNothing([]), true, 'no layers at all');
	assert.equal(burnsNothing([op({ element_ids: [] })]), true, 'a layer with nothing in it');
	assert.equal(burnsNothing([op({ output: false })]), true, 'work in a layer that stays behind');
	assert.equal(burnsNothing([op()]), false, 'work in a layer that burns');
	assert.equal(
		burnsNothing([op({ output: false }), op()]),
		false,
		'one layer that burns is enough'
	);
});

test('may I pause, resume or stop — one answer for four surfaces', () => {
	// Four formulas for this existed. `+page.svelte` asked the capabilities and the
	// token; `JobControls` asked the capabilities, the phase and its own `blocked`;
	// `PhoneView` asked whether there was a job, the token and the connection — and not
	// the capabilities at all, so a driver that cannot pause was offered a pause button
	// on the phone. `StatusBar` had a fourth that the template never read.
	//
	// The three questions differ in exactly one way, and it is worth writing down:
	// stopping stays allowed wherever the machine can do it. If our reading of the
	// phase is wrong you must not lose the emergency stop over it.
	const able = { pause: true, resume: true, stop: true };
	assert.equal(transportAllowed('pause', { able, phase: 'burning', blocked: false }), true);
	assert.equal(
		transportAllowed('pause', { able, phase: 'ready', blocked: false }),
		false,
		'nothing is running, so there is nothing to pause'
	);
	assert.equal(
		transportAllowed('pause', { able, phase: 'paused', blocked: false }),
		false,
		'already paused'
	);
	assert.equal(
		transportAllowed('pause', { able: { ...able, pause: false }, phase: 'burning', blocked: false }),
		false,
		'this driver cannot pause — the phone used not to ask'
	);
	assert.equal(transportAllowed('pause', { able, phase: 'burning', blocked: true }), false);

	assert.equal(transportAllowed('resume', { able, phase: 'paused', blocked: false }), true);
	assert.equal(transportAllowed('resume', { able, phase: 'burning', blocked: false }), false);

	assert.equal(
		transportAllowed('stop', { able, phase: 'ready', blocked: false }),
		true,
		'the stop stays available: a wrong reading of the phase may not cost it'
	);
	assert.equal(
		transportAllowed('stop', { able: { ...able, stop: false }, phase: 'burning', blocked: false }),
		false,
		'a machine that cannot be stopped from here must not pretend'
	);
});
