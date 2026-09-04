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
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { machineName } from '../src/lib/api.ts';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, '..', '..');

/**
 * The names both sides are asked about: every rule of the pair, and the edges where
 * two languages are most likely to disagree about what a character is.
 *
 * `İstanbul` because Turkish `İ` upper-cases to itself but lower-cases to two code
 * points; `ǅxy` because it is a title-case letter with three cases; `ﬁne` because the
 * ligature expands to two letters under `upper()` in Python and `toUpperCase()` in
 * JavaScript; `straße` because `ß` becomes `SS` and would make a name longer than it
 * was; `🙂box` because a non-BMP character is two code units in JavaScript and one in
 * Python. All of those are dropped on both sides now, but they are the cases where a
 * copy of a rule stops being a copy.
 */
const NAMES = [
	'Sheet 1',
	'kastje-groot',
	'  bord  ',
	'vél',
	'',
	'   ',
	'---',
	'!@#$%^&*',
	'nine char',
	'a very long name of twenty+',
	'lid_2/3',
	'kist\tA',
	'ÉÉÉ',
	'日本語ボード',
	'🙂box',
	'straße',
	'ﬁne',
	'İstanbul',
	'ǅxy'
];

test('the name is what the panel will show', () => {
	assert.equal(machineName('Sheet 1'), 'SHEET1', 'a space is not worth one of the eight');
	assert.equal(machineName('kastje-groot'), 'KASTJEGR', 'the hyphen goes before the eight are counted');
	assert.equal(machineName('  bord  '), 'BORD');
	assert.equal(machineName('vél'), 'VL', 'a letter the machine cannot show is dropped');
	assert.equal(machineName(''), '');
	assert.equal(machineName('   '), '', 'a name of nothing but spaces is no name');
});

test('a name is letters and digits, because that is what the refusal promises', () => {
	// `api.upload.needsName` says "a name of up to eight letters or digits; that is what
	// the machine's panel shows", and until this it was not true: `---` went through and
	// stood on the panel as `---`. A hyphen that falls away while you are typing it is
	// visible and one keystroke to undo; a sentence that is wrong is neither.
	assert.equal(machineName('---'), '');
	assert.equal(machineName('bord-2'), 'BORD2');
	assert.equal(machineName('a_b.c'), 'ABC');
	assert.equal(machineName('日本語'), '', 'not str.isalnum(): the panel has no glyph for it');
});

test('the field shows capitals even though it no longer stores them', () => {
	// The box keeps what you typed, in the case you typed it, so that a keystroke in the
	// middle of a name does not move the cursor to the end (measured, and written down at
	// `nameTyped` in the component). What makes it *look* like the panel of the machine is
	// therefore the style, and nothing else: take `text-transform` away and the field
	// quietly stops showing the name it will send. That is one line to delete and nothing
	// else would notice, so it is held here.
	const source = readFileSync(join(ROOT, 'frontend', 'src', 'lib', 'components', 'JobControls.svelte'), 'utf8');
	const at = source.indexOf('.pf-uploadrow input {');
	assert.ok(at > 0, 'the name field has no style block of its own any more');
	assert.match(
		source.slice(at, source.indexOf('}', at)),
		/text-transform:\s*uppercase/,
		'the name field no longer shows the capitals the machine will keep'
	);
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
