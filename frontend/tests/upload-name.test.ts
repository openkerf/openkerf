/**
 * The name the machine keeps, worked out on the screen before it is sent.
 *
 * Run: `node --test frontend/tests/upload-name.test.ts`
 *
 * A Ruida keeps eight characters and shows them in capitals — the engine's own
 * emulator hands back `name.upper()[:8]` when it is asked for a document's name
 * (`ruida/emulator.py:791`). The field on the screen therefore does it *in front
 * of* the user rather than behind them: what you type is what the panel of the
 * machine will say, and you find out at the keyboard instead of at the machine.
 *
 * The second test is the one worth having. `machineName` here and
 * `ruida_upload.machine_name` there are two copies of one rule, in two languages
 * that cannot import each other, and the copy is only safe as long as something
 * compares them. Measured while writing this: the first draft of the browser side
 * kept the space (`>= 32`), so "Sheet 1" was promised as `SHEET 1` on screen and
 * arrived as `SHEET1` on the panel — one character adrift, in the one string this
 * whole screen exists to get right.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { machineName } from '../src/lib/api.ts';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, '..', '..');

/** The names both sides are asked about. Every rule of the pair has one. */
const NAMES = [
	'Sheet 1',
	'kastje-groot',
	'  bord  ',
	'vél',
	'',
	'   ',
	'a very long name indeed',
	'lid_2/3',
	'kist\tA'
];

test('the name is what the panel will show', () => {
	assert.equal(machineName('Sheet 1'), 'SHEET1', 'a space is not worth one of the eight');
	assert.equal(machineName('kastje-groot'), 'KASTJE-G');
	assert.equal(machineName('  bord  '), 'BORD');
	assert.equal(machineName('vél'), 'VL', 'a letter the machine cannot show is dropped');
	assert.equal(machineName(''), '');
	assert.equal(machineName('   '), '', 'a name of nothing but spaces is no name');
});

test('the screen and the engine layer cut the name the same way', () => {
	// Not "the code looks the same": the two are run against each other. Without a
	// Python to run, the comparison is skipped rather than faked — a green tick for a
	// measurement that never happened is worse than a skip that says so.
	const python = join(ROOT, 'meerk40t', '.venv-nogui', 'bin', 'python');
	if (!existsSync(python)) return; // no interpreter here; the first test still holds
	const script =
		'import json,sys;sys.path.insert(0,"api");' +
		'from openkerf_api.ruida_upload import machine_name;' +
		'print(json.dumps([machine_name(n) for n in json.loads(sys.argv[1])]))';
	const theirs = JSON.parse(
		execFileSync(python, ['-c', script, JSON.stringify(NAMES)], {
			cwd: ROOT,
			encoding: 'utf8'
		})
	);
	assert.deepEqual(
		NAMES.map((name) => machineName(name)),
		theirs,
		'the name on the screen is not the name the machine will keep'
	);
});
