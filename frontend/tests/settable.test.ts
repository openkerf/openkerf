/**
 * A value the API accepts has a control that sets it.
 *
 * Run: `node --test frontend/tests/settable.test.ts`
 *
 * `CLAUDE.md` puts the rule in one line — "A route without a caller is not a feature" —
 * and names the trap underneath it: the handbook can write the gap up neatly and make
 * it invisible.
 *
 * That is what had happened to the tiling block. `sheets.py` validates `margin_mm`,
 * `overlap_mm` and `marker_size_mm`, rounds them and refuses politely; the app sent
 * `{ tiling: { enabled: true } }` and nothing else, and no screen had a field for any
 * of the three. One of those refusals says "Make the overlap at least 12 mm" — an
 * instruction for something the interface did not offer. And `docs/tiling.md` recorded
 * it as a property of the app: "the interface has no field for them at the moment",
 * eight lines above the quotation of that same refusal.
 *
 * So this reads the writable keys out of the engine layer and looks for each of them in
 * the app, in a line that is neither a type nor a comment.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const SRC = join(here, '..', 'src');
const API = join(here, '..', '..', 'api', 'openkerf_api');

function sources(dir: string, found: string[] = [], match = /\.(svelte|ts)$/): string[] {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) sources(path, found, match);
		else if (match.test(entry)) found.push(path);
	}
	return found;
}

/** Every line of the app that is not a comment and not a type-only line. */
const CODE = sources(SRC)
	.map((path) => readFileSync(path, 'utf8'))
	.join('\n')
	.split('\n')
	.filter((line) => {
		const trimmed = line.trim();
		return (
			trimmed &&
			!trimmed.startsWith('*') &&
			!trimmed.startsWith('//') &&
			!trimmed.startsWith('/*') &&
			!trimmed.startsWith('<!--')
		);
	})
	.join('\n');

test('every field of a sheet the API takes can be set from a screen', () => {
	const python = readFileSync(join(API, 'sheets.py'), 'utf8');
	const block = /DEFAULT_TILING = \{([\s\S]*?)\}/.exec(python);
	assert.ok(block, 'DEFAULT_TILING is no longer a block in sheets.py');
	const keys = [...block[1].matchAll(/"(\w+)":/g)].map((m) => m[1]);
	assert.ok(keys.length >= 4, `only ${keys.length} tiling keys found`);

	const unreachable = keys.filter((key) => !CODE.includes(key));
	assert.deepEqual(
		unreachable,
		[],
		`the API takes these and no screen sets them: ${unreachable.join(', ')}`
	);
});
