/**
 * One button, one definition.
 *
 * Run: `node --test frontend/tests/one-button.test.ts`
 *
 * Fifteen components defined a `.btn` of their own. They agreed on the border, the
 * radius, the surface and the weight, and disagreed on the size: `8px 12px` in six,
 * `8px 16px` in five, `var(--space-2) var(--space-4)` — the same 8/16, but as tokens —
 * in two, `6px 12px` with `min-height: 32px` in the starter offer and
 * `0 var(--space-4)` with `min-height: 36px` in a notification. Measured on screen:
 * 32.0, 36.0, 36.8 and 40.0 px, and the first two stand side by side, because the
 * offer sits inside the library window.
 *
 * `tokens.css:574` had noticed and written it down — "Eleven components define a
 * `.btn` of their own" — as a safety net rather than a repair. It was fifteen by the
 * time this round counted.
 *
 * So the button lives in `tokens.css` now, with named exceptions: `.btn.mini` where
 * the room is genuinely gone, `.btn.big` for the one that starts a burn. A component
 * may still say something extra about its own buttons (a `white-space`, a width); what
 * it may not do is start the base again.
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
const routes = join(here, '..', 'src', 'routes');

/** The properties that make a button a button. Whoever sets these starts a base. */
const BASE = ['border-radius', 'border:', 'background', 'font-weight', 'padding'];

function svelteFiles(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) svelteFiles(path, found);
		else if (entry.name.endsWith('.svelte')) found.push(path);
	}
	return found;
}

test('the button is defined in tokens.css', () => {
	assert.match(tokens, /^\.btn \{/m, 'no .btn in tokens.css');
	for (const property of BASE) {
		const block = /^\.btn \{[\s\S]*?^\}/m.exec(tokens)?.[0] ?? '';
		assert.ok(block.includes(property), `the shared .btn does not set ${property}`);
	}
	assert.match(tokens, /^\.btn\.primary/m, 'no primary variant in tokens.css');
	assert.match(tokens, /^\.btn\.mini/m, 'no mini variant — then the offer starts its own again');
});

test('no component defines a button of its own', () => {
	const offenders: string[] = [];
	for (const path of [...svelteFiles(components), ...svelteFiles(routes)]) {
		const source = readFileSync(path, 'utf8');
		const style = source.slice(source.indexOf('<style>'));
		// The base block, written exactly as the fifteen wrote it: `.btn {` on its own.
		const block = /\n\t*\.btn \{([\s\S]*?)\n\t*\}/.exec(style);
		if (!block) continue;
		const sets = BASE.filter((property) => block[1].includes(property));
		if (sets.length >= 3) {
			offenders.push(`${path.split('/').pop()}: ${sets.join(', ')}`);
		}
	}
	assert.deepEqual(
		offenders,
		[],
		`components starting the button over again: ${offenders.join(' | ')}`
	);
});
