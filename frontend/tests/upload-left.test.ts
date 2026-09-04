/**
 * What an upload that broke off says is left on the machine.
 *
 * Run: `node --test frontend/tests/upload-left.test.ts`
 *
 * `upload.stalled` and `upload.interrupted` carry three values, and the sentence
 * turns on the one that is not a number. `sent` counts blocks, and `sent === 0`
 * holds at two moments that need opposite advice: before the name went out, when
 * there is nothing on the panel at all, and after it, when the receiver has
 * already opened a file on the name (`ruida/emulator.py:757`) and the panel can be
 * showing an empty one. `announced` is the only thing that tells those apart, and
 * the API layer says so in `_interrupted`: it made this mistake twice before
 * branching on the flag instead of on the counter.
 *
 * A translation that branches on the numbers makes the same mistake again, in the
 * reader's own language — telling somebody there is nothing to clean up while a
 * file of their name sits on the panel. So the four cases are pinned here, in both
 * languages, against the four the API distinguishes.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { apiError, bindLanguage } from '../src/lib/i18n/core.ts';
import { en } from '../src/lib/i18n/en.ts';
import { nl } from '../src/lib/i18n/nl.ts';

const refusal = (code: string, values: Record<string, unknown>) =>
	new Response(null, {
		headers: {
			'X-OpenKerf-Error': code,
			'X-OpenKerf-Error-Values': JSON.stringify(values)
		}
	});

/** The four states the API can break off in, named as it names them. */
const CASES = [
	{ what: 'nothing went out', values: { sent: 0, chunks: 6, announced: false }, key: 'upload.left.none' },
	{ what: 'only the name went out', values: { sent: 0, chunks: 6, announced: true }, key: 'upload.left.named' },
	{ what: 'part of the job went out', values: { sent: 3, chunks: 6, announced: true }, key: 'upload.left.partial' },
	{ what: 'every block went out', values: { sent: 6, chunks: 6, announced: true }, key: 'upload.left.whole' }
] as const;

test('each of the four endings gets its own advice, in both languages', () => {
	for (const language of ['en', 'nl'] as const) {
		bindLanguage(() => language);
		const catalogue = language === 'en' ? en : nl;
		for (const code of ['upload.stalled', 'upload.interrupted']) {
			for (const { what, values, key } of CASES) {
				const said = apiError(refusal(code, values), 'English.');
				assert.ok(
					said.includes(String(catalogue[key as keyof typeof en])),
					`${language} › ${code} with ${what} does not say ${key}: ${said}`
				);
			}
		}
	}
	bindLanguage(() => 'en');
});

test('the two zeroes do not get the same sentence', () => {
	// The whole point. Both are "0 of 6 blocks", and one of them leaves a file behind.
	bindLanguage(() => 'nl');
	const nothing = apiError(refusal('upload.stalled', { sent: 0, chunks: 6, announced: false }), 'x');
	const named = apiError(refusal('upload.stalled', { sent: 0, chunks: 6, announced: true }), 'x');
	assert.notEqual(nothing, named, 'the Dutch sentence branches on the count, not on the flag');
	assert.match(named, /paneel/, `the reader is not told a file may be on the panel: ${named}`);
	bindLanguage(() => 'en');
});

test('the numbers in the sentence are written the reader’s way', () => {
	bindLanguage(() => 'nl');
	const said = apiError(refusal('upload.stalled', { sent: 1200, chunks: 2400, announced: true }), 'x');
	assert.match(said, /1\.200/, `the block count was not written in Dutch: ${said}`);
	assert.match(said, /2\.400/, `the total was not written in Dutch: ${said}`);
	bindLanguage(() => 'en');
});

test('a refusal without values still says something whole', () => {
	// A header that never arrived, or arrived broken, must not leave a sentence with a
	// hole where its advice was: the fallback is the sentence the API itself sent.
	const bare = new Response(null, { headers: { 'X-OpenKerf-Error': 'upload.stalled' } });
	assert.equal(apiError(bare, 'The machine stopped taking the file.'), 'The machine stopped taking the file.');
});
