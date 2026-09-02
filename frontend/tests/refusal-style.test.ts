/**
 * A refusal on screen looks like a refusal.
 *
 * Run: `node --test frontend/tests/refusal-style.test.ts`
 *
 * The stencil window said its refusal in a paragraph with `class="notice failure"`,
 * and neither class existed in its style block. Measured in light and dark: the
 * sentence came out at `rgb(27, 31, 36)` — exactly the colour of the explanation above
 * it. So the one line saying that this cannot be done read as an ordinary line of
 * text. Its neighbours, Clipart and Generators, colour theirs with `--danger`.
 *
 * A class that nothing defines is invisible in the source too: the markup looks
 * styled. This walks every element that announces itself with `role="alert"` and
 * checks that the classes it wears exist — in the component itself, or in the global
 * `tokens.css`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, '..', 'src', 'lib');
const tokens = readFileSync(join(lib, 'tokens.css'), 'utf8');
const components = join(lib, 'components');

/** Every `class="..."` that sits on the same tag as `role="alert"`. */
function alertClasses(source: string): string[] {
	const found: string[] = [];
	for (const match of source.matchAll(/<[a-z]+\b[^>]*role="alert"[^>]*>/gs)) {
		const tag = match[0];
		const cls = /class="([^"{}]*)"/.exec(tag);
		if (!cls) continue;
		found.push(...cls[1].split(/\s+/).filter(Boolean));
	}
	return found;
}

test('the classes on a refusal are defined somewhere', () => {
	const missing: string[] = [];
	for (const file of readdirSync(components).filter((n) => n.endsWith('.svelte'))) {
		const source = readFileSync(join(components, file), 'utf8');
		for (const name of alertClasses(source)) {
			const selector = new RegExp(`\\.${name}[\\s,.:{]`);
			if (!selector.test(source.slice(source.indexOf('<style>'))) && !selector.test(tokens)) {
				missing.push(`${file}: .${name}`);
			}
		}
	}
	assert.deepEqual(
		missing,
		[],
		`a refusal wears a class nothing defines, so it reads as ordinary text: ${missing.join(', ')}`
	);
});
