/**
 * A Ruida job's progress: burning time over the cut plan's estimate.
 *
 * Run: `node --test frontend/tests/ruida-progress.test.ts` — no server, no hardware.
 *
 * A Ruida takes its whole file in long before it has burned it (12,177 bytes in 13
 * blocks within 0.1 s, then a 77 s burn, on the KH-5030), so its packets say nothing
 * about how far the head has got. Since this round the API makes the progress of the
 * plan's estimate instead (`StatusReader.line_job_snapshot`): `running_seconds /
 * estimate_seconds`, capped at 0.99 until the link says "done", with
 * `progress_basis: "estimate"` and `elapsed_seconds` the same burning time (pauses
 * left out). These pin what the surfaces make of that: the bar and the status bar
 * show it and call it an estimate, the remainder does not grow after a pause, a burn
 * that outruns its estimate is neither "done" nor "0:00 left", the watchdog does not
 * call the waiting clock a stall, Pause and Resume are offered, and "Clear queue" is
 * not offered for a machine that has no queue.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileModule } from 'svelte/compiler';
import ts from 'typescript';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
	isFinished,
	jobPhase,
	machineState,
	pastEstimate,
	progressFromEstimate,
	remainingSeconds,
	totalSeconds,
	transportAllowed,
	type Device,
	type Job
} from '../src/lib/api.ts';

const here = dirname(fileURLToPath(import.meta.url));

/** A Ruida job as `/api/status` gives it, 77 s estimated. */
function ruidaJob(over: Partial<Job> = {}): Job {
	const ran = over.elapsed_seconds ?? 20;
	return {
		label: 'Sheet 1',
		type: 'RuidaJob',
		status: 'Running',
		priority: 0,
		running: true,
		paused: false,
		steps_done: 13,
		steps_total: 13,
		progress: Math.min(0.99, ran / 77),
		progress_basis: 'estimate',
		loops_executed: null,
		loops: 1,
		elapsed_seconds: ran,
		estimate_seconds: 77,
		...over
	};
}

function ruida(job: Job | null, laser_status = 'active'): Device {
	return {
		label: 'ruida',
		path: 'ruida',
		active: true,
		laser_status,
		paused: laser_status === 'paused',
		connection: { state: 'connected', detail: null },
		bed: { width_mm: 500, height_mm: 300 },
		position: { native: null, mm: null, state: null },
		spooler: {
			present: true,
			idle: job === null,
			queue_length: job ? 1 : 0,
			jobs: job ? [job] : [],
			ended: null
		}
	};
}

const able = { pause: true, resume: true, stop: true };

test('the remainder is the estimate less the burning time, and says it is one', () => {
	const job = ruidaJob({ elapsed_seconds: 20 });
	assert.equal(progressFromEstimate(job), true);
	// Not elapsed ÷ progress: that is the estimate back, and past the cap a wrong one.
	assert.equal(totalSeconds(job), 77);
	assert.equal(remainingSeconds(job), 57);
	assert.equal(pastEstimate(job), false);
});

test('a pause does not make the time left grow', () => {
	// The API's clock stands still while paused, so elapsed is the same before and
	// after a pause of any length; the remainder is what it was.
	const before = remainingSeconds(ruidaJob({ elapsed_seconds: 30 }));
	const paused = ruidaJob({ elapsed_seconds: 30, running: false, paused: true, status: 'Paused' });
	assert.equal(remainingSeconds(paused), before);
	assert.equal(jobPhase(ruida(paused, 'paused'), paused, false), 'paused');
});

test('a burn slower than its estimate waits at 99 %: not done, not "0:00 left"', () => {
	const job = ruidaJob({ elapsed_seconds: 90, progress: 0.99 });
	assert.equal(pastEstimate(job), true);
	assert.equal(isFinished(job), false);
	assert.equal(jobPhase(ruida(job), job, false), 'burning');
	assert.equal(machineState(ruida(job), true), 'busy');
});

test('an engine job keeps its measured progress', () => {
	const engine = ruidaJob({ type: 'LaserJob', progress_basis: 'steps', progress: 0.5, elapsed_seconds: 40, estimate_seconds: 999 });
	assert.equal(progressFromEstimate(engine), false);
	assert.equal(totalSeconds(engine), 80);
	// A server older than the field: no basis, so the old rule.
	const old = ruidaJob({ progress_basis: undefined, progress: 0.5, elapsed_seconds: 40 });
	assert.equal(progressFromEstimate(old), false);
	// No estimate on a Ruida: no progress, nothing shown as one.
	assert.equal(progressFromEstimate(ruidaJob({ progress: null, progress_basis: null })), false);
});

test('Pause is offered while a Ruida burns, Resume while it is paused', () => {
	const burning = ruidaJob();
	const phase = jobPhase(ruida(burning), burning, false);
	assert.equal(phase, 'burning');
	assert.equal(transportAllowed('pause', { able, phase, blocked: false }), true);
	assert.equal(transportAllowed('resume', { able, phase, blocked: false }), false);

	const sending = ruidaJob({ elapsed_seconds: 0, progress: 0 });
	assert.equal(jobPhase(ruida(sending, 'idle'), sending, false), 'burning');

	const held = ruidaJob({ running: false, paused: true, status: 'Paused' });
	const still = jobPhase(ruida(held, 'paused'), held, false);
	assert.equal(still, 'paused');
	assert.equal(transportAllowed('resume', { able, phase: still, blocked: false }), true);
	assert.equal(transportAllowed('pause', { able, phase: still, blocked: false }), false);
});

test('Clear queue is not drawn for a machine whose capabilities say it has none', () => {
	const source = readFileSync(join(here, '../src/lib/components/JobControls.svelte'), 'utf8');
	const at = source.indexOf("t('job.clearQueue'");
	assert.ok(at > 0);
	const guard = source.lastIndexOf('{#if', at);
	assert.match(source.slice(guard, at), /actions\?\.clear_queue !== false/);
});

test('the status bar and the job block call an estimated time an estimate', () => {
	for (const file of ['StatusBar.svelte', 'JobControls.svelte']) {
		const source = readFileSync(join(here, `../src/lib/components/${file}`), 'utf8');
		assert.match(source, /status\.remaining\.estimated/, file);
		assert.match(source, /status\.pastEstimate/, file);
	}
	const controls = readFileSync(join(here, '../src/lib/components/JobControls.svelte'), 'utf8');
	// Packets are not steps of work: no "13 / 13 steps" beside an estimated bar.
	assert.match(controls, /job\?\.steps_total && !estimated/);
	assert.match(controls, /job\.progressEstimated/);
});

test('the watchdog does not call a Ruida burn at its 99 % cap stalled', async () => {
	const work = join(here, '.ruida-progress-tmp');
	mkdirSync(work, { recursive: true });
	const source = readFileSync(join(here, '../src/lib/notifications.svelte.ts'), 'utf8')
		.replace("from './api.ts'", "from '../../src/lib/api.ts'")
		.replace("from './i18n/core.ts'", "from '../../src/lib/i18n/core.ts'");
	const plain = ts.transpileModule(source, {
		compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
	}).outputText;
	const compiled = compileModule(plain, { generate: 'server', filename: 'notifications.svelte.js' });
	const file = join(work, 'notifications.js');
	writeFileSync(file, compiled.js.code);
	const realNow = Date.now;
	try {
		const { Watchdog } = await import(file);
		const sent: string[] = [];
		let now = 1_000_000;
		Date.now = () => now;

		// Overrunning: elapsed past the estimate, progress waiting at 0.99, all
		// packets in. Ten minutes of identical readings.
		const ruidaDog = new Watchdog({ notify: (title: string) => sent.push(title) });
		const over = ruidaJob({ elapsed_seconds: 90, progress: 0.99 });
		for (let i = 0; i < 300; i++) {
			ruidaDog.status(ruida({ ...over, elapsed_seconds: 90 + i * 2 }), true);
			now += 2_000;
		}
		assert.equal(ruidaDog.alarm, null);
		assert.equal(sent.length, 0);

		// The same standstill on a job that counts its steps is still an alarm.
		const engineDog = new Watchdog({ notify: (title: string) => sent.push(title) });
		const stuck = ruidaJob({ type: 'LaserJob', progress_basis: 'steps', progress: 0.42, steps_done: 42, steps_total: 100 });
		for (let i = 0; i < 300; i++) {
			engineDog.status(ruida(stuck), true);
			now += 2_000;
		}
		assert.equal(engineDog.alarm?.code, 'stall');
	} finally {
		Date.now = realNow;
		rmSync(work, { recursive: true, force: true });
	}
});
