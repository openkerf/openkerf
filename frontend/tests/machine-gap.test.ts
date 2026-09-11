/**
 * A gap in the line is not an unplugged machine.
 *
 * Run: `node --test frontend/tests/machine-gap.test.ts`
 *
 * Measured on a KH-5030 over UDP on 11 September 2026, three minutes of an idle
 * connection sampled every 0.3 s: the controller fell silent four times, holding
 * "disconnected" for 3.9, 4.5 and 4.6 seconds and once for less than one sample.
 * On the wire our side kept asking through one of those gaps — seven ENQ packets
 * out, not one answer back — and then the replies resumed with nothing in between
 * to explain it. Nothing was unplugged; nothing had been switched off.
 *
 * The bar read that as "Not connected" every time, which is the opposite of the
 * mistake this app is careful about and just as expensive: a warning that cries
 * wolf twice a minute is a warning nobody reads. But smoothing it away would be
 * the original lie — a machine that really is off must say so. Hence a state of
 * its own, and the rule that decides it lives here, once, so the top bar, the
 * status bar and the phone cannot disagree about what four seconds of silence
 * means.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { machineState, LINE_GAP_MS } from '../src/lib/api.ts';

const here = dirname(fileURLToPath(import.meta.url));
const read = (...parts: string[]) =>
	readFileSync(join(here, '..', 'src', 'lib', ...parts), 'utf8');

function device(over: Record<string, unknown> = {}) {
	return {
		label: 'KH-5030 Co2',
		path: 'ruida',
		active: true,
		laser_status: 'idle',
		paused: false,
		bed: { width_mm: 530, height_mm: 320 },
		position: { native: [0, 0], mm: [0, 0], state: ['idle', 'idle'] },
		spooler: { present: true, idle: true, queue_length: 0, jobs: [] },
		...over
	} as never;
}

test('a machine that has just gone quiet is faltering, not unplugged', () => {
	const quiet = device({ connection: { state: 'disconnected', detail: null, held_ms: 4000 } });

	assert.equal(machineState(quiet, true), 'faltering');
});

test('a machine that stays quiet is unplugged', () => {
	const off = device({
		connection: { state: 'disconnected', detail: null, held_ms: LINE_GAP_MS + 1 }
	});

	assert.equal(machineState(off, true), 'unplugged');
});

test('the longest gap measured on the machine still reads as faltering', () => {
	const gap = device({ connection: { state: 'disconnected', detail: null, held_ms: 4600 } });

	assert.equal(machineState(gap, true), 'faltering');
});

test('a connected machine is unaffected by the rule', () => {
	const up = device({ connection: { state: 'connected', detail: null, held_ms: 120000 } });

	assert.equal(machineState(up, true), 'ready');
});

test('a machine that is burning is never called faltering', () => {
	/**
	 * The same reasoning the `unplugged` branch already rests on: a laser that is
	 * working is connected whatever a flag says, and a job must not be written off
	 * over four seconds of silence in the status poll.
	 */
	const burning = device({
		laser_status: 'active',
		connection: { state: 'disconnected', detail: null, held_ms: 1000 }
	});

	assert.equal(machineState(burning, true), 'busy');
});

test('an older snapshot without the age is treated as lasting', () => {
	/**
	 * A server that predates this field sends no `held_ms`. Then the old reading
	 * is the honest one: say the machine is not connected rather than invent a
	 * gap that is about to end.
	 */
	const old = device({ connection: { state: 'disconnected', detail: null } });

	assert.equal(machineState(old, true), 'unplugged');
});


test('the status bar says the line is faltering rather than calling it unknown', () => {
	/**
	 * A source-level guard, like `machine-dot.test.ts`, and for the same reason: the
	 * bar works out its sentence from a chain of conditions, and a new state slips
	 * through such a chain silently. It did here — `unknown` is "connected, not
	 * unplugged, and the connection does not read connected", which a faltering
	 * machine answers yes to. The bar then said "Connection unknown" about a machine
	 * that had been answering a second earlier, which is the vaguest of the four
	 * things it could have said.
	 */
	const bar = read('components', 'StatusBar.svelte');

	assert.match(
		bar,
		/status\.machine\.faltering/,
		'the bar has no sentence for a faltering line'
	);
	assert.match(
		bar,
		/machineState !== 'faltering'/,
		'`unknown` still swallows the faltering state and reports it as unknown'
	);
});
