/**
 * A grey control says why it is grey.
 *
 * Run: `node --test frontend/tests/why-grey.test.ts`
 *
 * `actions.ts` states the rule about itself — "A grey button without a reason is a
 * riddle" — and `actions.test.ts` enforces it, but only for rows that come out of
 * `actions.ts`. Everything else was on its honour, and counted: **89 of the 180
 * `disabled` bindings in the app named no reason at all**, sixteen of them in the
 * context panel alone. The sharpest was a verb that exists in both places: the bridge
 * control went pale on three conditions without a word, six pixels from a menu row
 * carrying the sentence.
 *
 * Two thirds needed no new sentence — the app already says "Another operation is still
 * running" and "Requires a token", and those controls now read them. The rest got one
 * each, in both languages.
 *
 * What this pins is the ratchet: a new control that goes grey without saying why fails
 * here. The unit is the element, not the line — a `disabled` on its own line often has
 * its title three lines up, and a second `title` attribute would silently win or lose.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const SRC = join(here, '..', 'src');

function sources(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) sources(path, found);
		else if (entry.endsWith('.svelte')) found.push(path);
	}
	return found;
}

/** Every element tag, from `<button` to the `>` that closes it. */
function* tags(text: string) {
	const open = /<(button|input|select|textarea|a)\b/g;
	let m: RegExpExecArray | null;
	while ((m = open.exec(text))) {
		let depth = 0;
		for (let i = m.index; i < text.length; i++) {
			const c = text[i];
			if (c === '{') depth++;
			else if (c === '}') depth--;
			else if (c === '>' && depth === 0) {
				yield text.slice(m.index, i + 1);
				break;
			}
		}
	}
}

test('a control that goes grey names a reason', () => {
	const silent: string[] = [];
	for (const path of sources(SRC)) {
		const text = readFileSync(path, 'utf8');
		for (const tag of tags(text)) {
			if (!tag.includes('disabled=')) continue;
			// `title` is the tooltip a pointer finds; `aria-label` serves a screen reader
			// where the visible label already carries the state. Either counts.
			if (tag.includes('title=') || tag.includes('aria-label=')) continue;
			const line = text.slice(0, text.indexOf(tag)).split('\n').length;
			silent.push(`${path.split('/').pop()}:${line}`);
		}
	}
	assert.deepEqual(
		silent,
		[],
		`grey without a reason — a riddle, and the app has a sentence for most of them: ${silent.join(', ')}`
	);
});

test('the two shared reasons are the ones the app already had', () => {
	// Not new sentences: the same two `actions.ts` puts on a menu row. A second wording
	// for "still running" would be exactly the drift this round went looking for.
	const en = readFileSync(join(SRC, 'lib', 'i18n', 'en.ts'), 'utf8');
	assert.match(en, /'reason\.busy': 'Another operation is still running'/);
	assert.match(en, /'reason\.needsToken': 'Requires a token'/);
});
