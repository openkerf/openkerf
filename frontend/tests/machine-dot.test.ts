/**
 * The machine's state has one colour, on every surface.
 *
 * Run: `node --test frontend/tests/machine-dot.test.ts`
 *
 * The coloured dot beside the machine name appears in three places: the top bar, the
 * status bar and the phone view. Each of them wrote its own list of states, and the
 * lists were not the same. Measured with an unplugged port: `.dot.unplugged` on the
 * phone gave `rgb(184, 134, 11)` (`--warn-solid`) at 390 wide, and `rgb(91, 100, 112)`
 * (`--text-2`) at 1440 — because the top bar has no rule for that state at all. So the
 * same machine looked like a warning in your hand and like nothing on your desk. The
 * status bar had one state of the six.
 *
 * Both earlier repairs are still visible in the comments there: `.dot.running` that
 * matched nothing because the state is called `busy`, and `unplugged` that did not
 * exist yet when that dot was written. Both are the same mistake — a list of states
 * kept by hand, next to another list of states kept by hand.
 *
 * So the colours live in `tokens.css`, once, and this test refuses a component that
 * starts its own list again.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src', 'lib');
const read = (...parts: string[]) => readFileSync(join(src, ...parts), 'utf8');

/** The states the API can report, straight from the type. */
const STATES = (() => {
	const line = /export type MachineState =([^;]+);/.exec(read('api.ts'));
	assert.ok(line, 'MachineState is no longer a union type');
	return [...line[1].matchAll(/'([a-z]+)'/g)].map((m) => m[1]);
})();

test('every state the API can report has a colour', () => {
	assert.ok(STATES.length >= 6, `only ${STATES.length} states found: ${STATES.join(', ')}`);
	const tokens = read('tokens.css');
	for (const state of STATES) {
		assert.match(
			tokens,
			new RegExp(`\\.machinedot\\.${state}\\b`),
			`no colour for "${state}" — on a surface that does not name it, it stays grey`
		);
	}
});

test('no surface keeps a colour list of its own', () => {
	for (const file of ['components/TopBar.svelte', 'components/StatusBar.svelte', 'components/PhoneView.svelte']) {
		const source = read(...file.split('/'));
		for (const state of STATES) {
			assert.ok(
				!new RegExp(`\\.dot\\.${state}\\b`).test(source),
				`${file} colours "${state}" itself; the other two then differ from it`
			);
		}
	}
});
