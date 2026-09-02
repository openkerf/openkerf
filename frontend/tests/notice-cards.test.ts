/**
 * The cards that hang under the top bar do not cover the controls.
 *
 * Run: `node --test frontend/tests/notice-cards.test.ts`
 *
 * Three cards hang from the same line: the alarm, the message stack and the card that
 * says the connection has dropped. Above the canvas sit two bars — the action bar and
 * the sheet bar — and `+page.svelte` measures their height into `--topedge-height` so a
 * card can start below them. DESIGN-SYSTEM v4 says it in one line: a message does not
 * cover a control.
 *
 * Measured with the connection card up, at 1440 x 900: it stood at y 60, 620 x 89.9,
 * while the action bar runs y 48-86 and the sheet bar y 86-121. `elementFromPoint` in
 * the middle of each of the fifteen action-bar buttons gave the card — all fifteen,
 * including the three that still worked at that moment. Its two neighbours had the
 * offset and carried a comment about exactly this mistake; it did not.
 *
 * This reads the rule out of the source rather than out of a browser, because the
 * state that shows the card is a server that has gone away, and that turned out not to
 * be reproducible from inside the app on loopback.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const components = join(here, '..', 'src', 'lib', 'components');

/** The `top:` of the first fixed block in a component, comments stripped. */
function topOf(file: string, selector: string): string {
	const source = readFileSync(join(components, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
	const start = source.indexOf(selector);
	assert.notEqual(start, -1, `${file} has no ${selector} any more`);
	const block = source.slice(start, source.indexOf('}', start));
	const top = /top:\s*([^;]+);/.exec(block);
	assert.ok(top, `${file}: ${selector} does not place itself vertically any more`);
	return top[1].replace(/\s+/g, ' ');
}

test('a card under the top bar starts below the bars above the canvas', () => {
	const cards: [string, string][] = [
		['AlarmCard.svelte', '.alarm {'],
		['Message.svelte', '.notices {'],
		['ConnectionCard.svelte', '.dropped {']
	];
	for (const [file, selector] of cards) {
		const top = topOf(file, selector);
		assert.match(
			top,
			/--topbar-height/,
			`${file} does not hang from the top bar: ${top}`
		);
		assert.match(
			top,
			/--topedge-height/,
			`${file} starts at the top bar and so lies over the action bar: ${top}`
		);
	}
});
