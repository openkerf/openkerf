/**
 * The translations: complete, consistent, and no fragments.
 *
 * Run: `node --test frontend/tests/i18n.test.ts`
 *
 * The types already refuse a missing key inside this repository. What they cannot
 * see is the rest: a `{n}` that got lost in translation (a sentence that promises
 * a number and gives none), a plural that became a plain string, a message that
 * is empty, or English that leaked into the Dutch file. Those are exactly the
 * mistakes a translator makes at three in the morning, so a test makes them
 * loud instead of shipping them.
 *
 * It also guards the rule that keeps translation possible at all: no message may
 * be half a sentence. A key whose value is a bare fragment ("of", " mm") means
 * someone glued a sentence together in the markup, and word order is not a
 * constant across languages.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const work = join(here, '.i18n-tmp');
const SRC = join(here, '..', 'src');

async function load(name: string) {
	const ts = (await import('typescript')).default;
	mkdirSync(work, { recursive: true });
	const source = readFileSync(join(SRC, 'lib', 'i18n', `${name}.ts`), 'utf8');
	// The catalogues only import a type from the runtime; that can go, so they can
	// be read without Svelte runes.
	const withoutTypes = source.replace(/^import type[^\n]*\n/gm, '').replace(/: Catalogue\b/, '');
	const { outputText } = ts.transpileModule(withoutTypes, {
		compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
	});
	const path = join(work, `${name}.mjs`);
	writeFileSync(path, outputText);
	return (await import(path))[name] as Record<string, unknown>;
}

const en = await load('en');
const nl = await load('nl');
rmSync(work, { recursive: true, force: true });

/** The other languages, by name. Grows as soon as one is added. */
const TRANSLATIONS: Record<string, Record<string, unknown>> = { nl };

/**
 * A catalogue file in `i18n/`, by shape: `en.ts`, `nl.ts`, `de.ts`, `pt-BR.ts`.
 *
 * By shape and not by a list of names, because a list is a guard that goes quiet the
 * moment somebody does something good. A `de.ts` that a hand-written list does not know
 * would be read as ordinary source below, and then *every* key in the app counts as
 * used — `every key is used somewhere` would pass for ever without looking at anything,
 * and `no message is resolved once and kept` would report the catalogue itself. Measured
 * by adding a `de.ts` and a key nobody calls: with a list, the guard stayed green.
 */
const CATALOGUE_FILE = /^[a-z]{2}(-[A-Z]{2})?\.ts$/;

/**
 * Every file the app is built from, so a key can be looked for in all of them.
 *
 * The catalogues are left out and nothing else in `i18n/`: a key is written down in
 * `en.ts` and `nl.ts`, so reading those would let every key count as its own user. The
 * machinery beside them is ordinary app code — `core.ts` picks one of four sentences for
 * an upload that broke off halfway, and those four are as used as anything a component
 * calls. Leaving the whole folder out made them look like keys nobody wanted.
 */
function sources(dir: string, found: string[] = [], match = /\.(svelte|ts)$/): string[] {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) sources(path, found, match);
		else if (match.test(entry) && !(path.includes(`${'i18n'}/`) && CATALOGUE_FILE.test(entry)))
			found.push(path);
	}
	return found;
}

test('every catalogue on disk is one this file checks', () => {
	// The other half of the shape rule. `TRANSLATIONS` above is written by hand, so a
	// language added to the folder and not to that list would be translated by nobody and
	// checked by nothing — no test here would ever open it. Rather than two hand-written
	// lists that have to agree, the folder decides and this says so out loud.
	const onDisk = readdirSync(join(SRC, 'lib', 'i18n'))
		.filter((entry) => CATALOGUE_FILE.test(entry))
		.map((entry) => entry.replace(/\.ts$/, ''))
		.sort();
	assert.deepEqual(
		onDisk,
		['en', ...Object.keys(TRANSLATIONS)].sort(),
		'a catalogue in i18n/ that this file does not load — add it to TRANSLATIONS'
	);
});

const CODE = sources(SRC)
	.map((p) => readFileSync(p, 'utf8'))
	.join('\n');

const placeholders = (value: unknown): string[] => {
	const text =
		typeof value === 'string'
			? value
			: [(value as { one: string }).one, (value as { other: string }).other].join(' ');
	return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
};

test('the source language has no empty or duplicate messages', () => {
	const seen = new Map<string, string>();
	for (const [key, value] of Object.entries(en)) {
		const text = typeof value === 'string' ? value : (value as { other: string }).other;
		assert.ok(text && text.trim().length > 0, `${key} is empty`);
		// The same text under two keys is not wrong, but it is a sign that there is
		// one key too many — the message says which two.
		const earlier = seen.get(text);
		if (earlier && text.length > 12)
			assert.fail(`"${text}" sits under both ${earlier} and ${key}`);
		seen.set(text, key);
	}
});

test('every key is used somewhere', () => {
	// A key nobody calls is a message that will silently go stale: it is not
	// translated when the English changes, and it is not seen when it is wrong.
	// They arise while converting — one screen gets two attempts at the same
	// sentence — and the only moment to catch them is here.
	//
	// Some families are composed at runtime — `t(\`machine.state.${state}\`)` — so
	// their keys never appear as a literal. Those are listed here by prefix, and the
	// prefix itself has to be built somewhere, otherwise a whole family could go
	// unnoticed.
	const DYNAMIC = ['machine.state.', 'machine.hint.', 'job.phase.', 'axis.', 'panel.type.', 'notify.permission.', 'notify.state.', 'count.'];
	for (const prefix of DYNAMIC)
		assert.ok(CODE.includes(`${prefix}$`), `nothing composes ${prefix}… any more — drop it here`);
	const unused = Object.keys(en).filter(
		(key) =>
			!CODE.includes(`'${key}'`) &&
			!DYNAMIC.some((p) => key.startsWith(p)) &&
			!key.startsWith('api.')
	);
	assert.deepEqual(unused, [], `keys in the catalogue that nothing uses: ${unused.join(', ')}`);
});

test('every api.* key answers to a refusal the API can actually send', () => {
	// These are looked up as `api.${code}` from the `X-OpenKerf-Error` header, so
	// they never appear as a literal. What keeps them honest is the other side: the
	// code has to exist in the engine layer. A renamed refusal would otherwise leave
	// a translation nobody ever reaches.
	const python = sources(join(here, '..', '..', 'api', 'openkerf_api'), [], /\.py$/)
		.map((p) => readFileSync(p, 'utf8'))
		.join('\n');
	// A code is usually a literal at the raise. A family of them can be assembled:
	// `code=f"series.notAWholeNumber.{what}"` is four refusals from one raise, and a
	// literal search calls all four orphans — which is how those four sat untranslated
	// while the rest of the window spoke Dutch. So a template counts as well, and to
	// stop it waving anything through, the segment it fills in has to be a quoted word
	// of its own somewhere in the same Python: a key with a typo in that segment still
	// has nothing to answer to.
	const templates = [...python.matchAll(/code=f"([a-zA-Z0-9.]*)\{\w+\}"/g)].map((m) => m[1]);
	const words = new Set([...python.matchAll(/"([A-Za-z_][A-Za-z0-9_]*)"/g)].map((m) => m[1]));
	const sends = (code: string) =>
		python.includes(`code="${code}"`) ||
		templates.some((prefix) => {
			const tail = code.startsWith(prefix) ? code.slice(prefix.length) : '';
			return tail.length > 0 && !tail.includes('.') && words.has(tail);
		});
	const orphans = Object.keys(en)
		.filter((key) => key.startsWith('api.'))
		.filter((key) => !sends(key.slice(4)));
	assert.deepEqual(orphans, [], `translations for refusals the API no longer sends: ${orphans}`);
});

/**
 * The refusals the engine layer raises, by code, with the sentence it sends.
 *
 * The message is the first argument of a `DesignError(...)`, and Python writes a long
 * one as adjacent string literals, so the leading run of them is taken and joined. A
 * call whose message is a variable has no such run and is skipped: there is nothing to
 * compare. Every `{placeholder}` — ours and an f-string's own `{why}` — is flattened to
 * `{}`, because the names differ by necessity (the header calls it `block`, the Python
 * calls it `oversized`) and this is about the words around them.
 */
function refusalsInPython(python: string): Map<string, string> {
	const found = new Map<string, string>();
	// Every `…Error(` and not `DesignError(` alone: the library, the corners and the
	// shared catalogue raise classes of their own that carry the same `code=`, and
	// anchoring on one class left 26 of them uncompared — a guard that looks at four
	// fifths of the wall.
	for (const raised of python.matchAll(/\b[A-Z][A-Za-z]*Error\(/g)) {
		let rest = python.slice(raised.index + raised[0].length);
		const parts: string[] = [];
		for (;;) {
			// `(?:\s|#[^\n]*)*` and not `\s*`: Python's adjacent string literals are how a
			// long refusal is written, and a comment about the next half sits between them.
			const piece = /^(?:\s|#[^\n]*)*f?"((?:[^"\\]|\\.)*)"/.exec(rest);
			if (!piece) break;
			parts.push(piece[1]);
			rest = rest.slice(piece[0].length);
		}
		const code = /^[^)]*?code="([a-zA-Z0-9.]+)"/.exec(rest);
		if (!parts.length || !code) continue;
		found.set(code[1], parts.join(''));
	}
	return found;
}

/**
 * One shape to compare in: no line breaks, one kind of apostrophe, bare placeholders, and
 * the escapes Python writes a quotation mark with resolved — `\u201c` in a `.py` and “ in
 * a `.ts` are the same character, and a test that says otherwise reports a difference
 * nobody can see.
 */
const asOneSentence = (text: string) =>
	text
		.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
		.replace(/\\([\\"'])/g, '$1')
		.replace(/\{[^}]*\}/g, '{}')
		.replace(/’/g, "'")
		.split(/\s+/)
		.join(' ')
		.trim();

test('the English of a refusal is the sentence the API sends', () => {
	// Both halves reach the same reader. `apiError` says the catalogue's sentence when it
	// knows the code and the API's own when it does not, so where the two differ, one of
	// them is a version of the message nobody meant to keep — and which one shows depends
	// on nothing the reader can see. Measured when this was written: of the 146 `api.*`
	// keys, 139 could be read out of the API and 131 of those were word for word.
	//
	// The seven that cannot be read here at all, each for a reason: four
	// `series.notAWholeNumber.*` come out of one raise that builds its code with an
	// f-string, `upload.stalled` and `upload.interrupted` out of one raise that is handed
	// its code in a variable, and `rotary.homeWhileActive` is handed its whole sentence in
	// one. Nothing static can pair those with a key.
	//
	// The eight below are the ones that already differed, named one by one and not
	// counted, so that the debt is in the code instead of in somebody's memory. They are
	// written up in `.superpowers/sdd/2026-09-03-ruida-upload/zinnen-uiteen.md`, sentence
	// beside sentence. **This list may shrink and may never grow**: a new refusal whose
	// two halves disagree is a mistake being made now, and that is what this test is for.
	const ALREADY_APART = new Set([
		// Five where the API's sentence names something the header does not carry — a
		// command, an element id, an engine type, the user's own material name — so the
		// catalogue says the same thing without it ("That combination", "That shape is
		// gone"). Deliberate, and the repair, where there is one, is to let the value
		// travel rather than to reword either half.
		'stencil.tooMuchBridge',
		'draw.booleanEmpty',
		'edit.staleElement',
		'nodes.notEditable',
		'library.material.nameTaken',
		// The other way round: this one *does* send its numbers and only the catalogue
		// uses them, so the API's sentence is the half that stayed behind.
		'library.preset.kerfRange',
		// And two where only the quotation marks around a package name differ.
		'gen.noQrLib',
		'gen.noBarcodeLib'
	]);
	const python = sources(join(here, '..', '..', 'api', 'openkerf_api'), [], /\.py$/)
		.map((p) => readFileSync(p, 'utf8'))
		.join('\n');
	const apart: string[] = [];
	const together: string[] = [];
	const fresh: string[] = [];
	for (const [code, sentence] of refusalsInPython(python)) {
		// A plural is compared on its `other`, which is the branch the Python writes: a
		// refusal that bends to a count is exactly the kind with the most words in it, and
		// skipping every one of them would have made this guard blind where it is needed
		// most. `stencil.singleStroke` is one, and it does match.
		const message = en[`api.${code}`];
		const ours = typeof message === 'string' ? message : (message as { other?: string })?.other;
		if (typeof ours !== 'string') continue;
		const same = asOneSentence(ours) === asOneSentence(sentence);
		(same ? together : apart).push(code);
		if (!same && !ALREADY_APART.has(code))
			fresh.push(
				`api.${code}\n    API: ${asOneSentence(sentence)}\n    en : ${asOneSentence(ours)}`
			);
	}
	assert.deepEqual(fresh, [], `a refusal and its translation say two different things:\n  ${fresh.join('\n  ')}`);
	// The extractor reads Python, and Python can be rewritten. 139 were readable when this
	// was written; a sharp drop means it has stopped finding them and this test is quietly
	// measuring nothing.
	const read = together.length + apart.length;
	assert.ok(read >= 130, `only ${read} refusals could be read out of the API — the reader is losing them`);
	// And the list stays honest: a code on it that no longer differs has been repaired,
	// and then it comes off, or the next divergence hides behind it.
	const mended = [...ALREADY_APART].filter((code) => !apart.includes(code));
	assert.deepEqual(mended, [], `these no longer differ — take them off the list: ${mended.join(', ')}`);
});

test('every translation has exactly the keys of the source language', () => {
	for (const [language, catalogue] of Object.entries(TRANSLATIONS)) {
		const source = new Set(Object.keys(en));
		const target = new Set(Object.keys(catalogue));
		const missing = [...source].filter((k) => !target.has(k));
		const extra = [...target].filter((k) => !source.has(k));
		assert.deepEqual(missing, [], `${language} is missing keys`);
		assert.deepEqual(extra, [], `${language} has keys the source language does not know`);
	}
});

test('the placeholders survive the translation', () => {
	for (const [language, catalogue] of Object.entries(TRANSLATIONS)) {
		for (const key of Object.keys(en)) {
			assert.deepEqual(
				placeholders(catalogue[key]),
				placeholders(en[key]),
				`${language} › ${key}: different placeholders`
			);
		}
	}
});

test('a plural in the source language is a plural in the translation too', () => {
	for (const [language, catalogue] of Object.entries(TRANSLATIONS)) {
		for (const [key, value] of Object.entries(en)) {
			const sourceIsPlural = typeof value === 'object';
			const targetIsPlural = typeof catalogue[key] === 'object';
			assert.equal(
				targetIsPlural,
				sourceIsPlural,
				`${language} › ${key}: ${sourceIsPlural ? 'plural lost' : 'unexpected plural'}`
			);
			if (sourceIsPlural) {
				const form = catalogue[key] as { one?: string; other?: string };
				assert.ok(form.one?.trim(), `${language} › ${key}: 'one' is empty`);
				assert.ok(form.other?.trim(), `${language} › ${key}: 'other' is empty`);
			}
		}
	}
});

test('no message is half a sentence', () => {
	// A key holding a bare conjunction or a loose unit means a sentence is being
	// glued together in the markup. That works in two languages with the same word
	// order and nowhere else.
	const fragments = /^(of|and|or|en|van|in|op|to|for|met|the|de|het|een|a|mm|%|·|—)$/i;
	// A one-word *label* is not a fragment: "from" and "to" above two number fields
	// are the whole message, and a language that needs more words has room for them.
	// Listed by key so a genuinely glued sentence cannot hide behind the exception.
	const LABELS = new Set(['grid.from', 'grid.to']);
	for (const [key, value] of Object.entries(en)) {
		if (LABELS.has(key)) continue;
		const texts =
			typeof value === 'string'
				? [value]
				: [(value as { one: string }).one, (value as { other: string }).other];
		for (const text of texts) {
			assert.ok(
				!fragments.test(text.trim()),
				`${key} is a fragment ("${text}") — make it a whole sentence`
			);
			assert.ok(
				!/^\s|\s$/.test(text),
				`${key} starts or ends with whitespace ("${text}") — that is layout, not text`
			);
		}
	}
});

test('a message that is filled with another message does not say its words twice', () => {
	// `TestGrid` fills {columns} and {rows} of `grid.lead` with `grid.lead.right` and
	// `grid.lead.down`, so the direction lives in those two fragments. A frame that
	// carries the direction as well says it twice, and nothing in the types or in the
	// other tests can see that: both halves are valid sentences on their own.
	// Measured on the first screen of the test-grid window: "power increases to the
	// right increases to the right, speed downwards downwards".
	for (const [name, catalogue] of Object.entries({ en, ...TRANSLATIONS })) {
		const frame = String(catalogue['grid.lead']);
		for (const part of ['grid.lead.right', 'grid.lead.down']) {
			const words = String(catalogue[part]).replace('{axis}', '').trim();
			assert.ok(
				!frame.includes(words),
				`${name}: ${part} already says "${words}", and grid.lead says it again`
			);
		}
	}
});

test('the translation is not accidentally still the source language', () => {
	// A key that is literally the English *can* be right — "Project", "Alarm", "Esc",
	// "mm", "QR" — but a sentence that is identical has been forgotten. The line used
	// to be drawn at five words, and that let a short one stand for months: the top
	// bar read "Start job" over a panel that read "Job starten", and nothing here saw
	// it.
	//
	// So the line is drawn at two words, and the few that are rightly identical are
	// named. Measured over the whole catalogue: 58 messages of 1841 are word for word
	// the English, and 54 of those are a single word — a name, a unit, an
	// abbreviation, or a word Dutch borrowed whole. One word being the same is
	// ordinary, and a list of 54 exceptions is a list nobody reads; two words being
	// the same is rare enough to be worth one line each.
	const SAME = new Set([
		'status.openkerf.live', // a product name and a word Dutch borrowed whole
		'canvas.bedSize', // "bed … mm": a unit, and a noun Dutch spells the same way
		'setup.head.machines', // "OpenKerf — machines", a window title around the product name
		'rotary.head', // "Rotary — OpenKerf", the same, and a rotary is a rotary in the workshop
		'sheets.tiling.overlap' // "Overlap (mm)": Dutch borrowed the word whole, and mm is mm
	]);
	for (const [language, catalogue] of Object.entries(TRANSLATIONS)) {
		for (const [key, value] of Object.entries(en)) {
			if (typeof value !== 'string' || SAME.has(key)) continue;
			// Placeholders and loose characters do not count as words: "{mm} mm
			// {direction}" is one word, not three, and is rightly the same in both.
			const words = value.replace(/\{\w+\}/g, ' ').match(/[A-Za-zÀ-ÿ]{2,}/g) ?? [];
			if (words.length < 2) continue;
			assert.notEqual(
				catalogue[key],
				value,
				`${language} › ${key} is still word for word the English`
			);
		}
	}
});

test('keys are semantic and not the English text', () => {
	for (const key of Object.keys(en)) {
		assert.match(
			key,
			/^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9]+)+$/,
			`${key} does not follow the pattern group.name`
		);
	}
});

test('no message carries the name of a thing in the code', () => {
	// Found by the user, who read "CornersDialog…" in their own context menu. The Dutch
	// catalogue had it four times, in the menu row, the window title and both buttons: a
	// rename of the component had been done with a blunt search and replace, and "Hoeken"
	// — the Dutch for corners — was the word it replaced. Nothing noticed for a month,
	// because every check here compares a translation with its English original and
	// "CornersDialog…" is not "Corners…".
	//
	// A token with a capital inside it is never a word in either language. The real names
	// that do look like that — OpenKerf, MeerK40t, LightBurn, GitHub, LibUSB — are the
	// same in both catalogues, so the rule is: a camel-cased word may appear in a
	// translation only if the English catalogue uses it too.
	const camel = /\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b/g;
	const names = (source: string) => {
		const found = new Set<string>();
		for (const line of source.split('\n')) {
			const at = line.indexOf(':');
			if (at < 0) continue;
			for (const word of line.slice(at).match(camel) ?? []) found.add(word);
		}
		return found;
	};
	const catalogue = (language: string) =>
		readFileSync(join(SRC, 'lib', 'i18n', `${language}.ts`), 'utf8');
	const english = names(catalogue('en'));
	for (const language of Object.keys(TRANSLATIONS)) {
		const strange = [...names(catalogue(language))].filter((word) => !english.has(word));
		assert.deepEqual(
			strange,
			[],
			`${language}.ts uses ${strange.join(', ')}, which the English catalogue does not: ` +
				'that is the name of something in the code, not a word'
		);
	}
});

test('a refusal with a code is said in the reader’s language', async () => {
	// The header is the whole mechanism, so it is worth one test end to end: a
	// known code becomes a catalogue message, an unknown one falls back to the
	// sentence the API sent, and a response without a code does too.
	const { apiError, bindLanguage } = await import('../src/lib/i18n/core.ts');
	const known = new Response(null, { headers: { 'X-OpenKerf-Error': 'nest.needsTwo' } });
	const unknown = new Response(null, { headers: { 'X-OpenKerf-Error': 'not.a.code' } });
	const bare = new Response(null);

	assert.equal(apiError(known, 'Choose at least two shapes to nest.'), en['api.nest.needsTwo']);
	assert.equal(apiError(unknown, 'Something else.'), 'Something else.');
	assert.equal(apiError(bare, 'Something else.'), 'Something else.');

	bindLanguage(() => 'nl');
	assert.equal(apiError(known, 'Choose at least two shapes to nest.'), nl['api.nest.needsTwo']);
	bindLanguage(() => 'en');
});

test('the one refusal a reader has to act on is not summarised away', () => {
	// `apiError` only helps where somebody calls it. These two screens are the pair that
	// did not: both upload a photograph of a test board, and the refusal on that route is
	// the one the board code exists to make — "the code in this photograph says board
	// FR5B R74F; you picked 6Y0Y JKS2" — where the answer is inside the sentence and the
	// board is still on the bench. Measured in a browser against an engine of its own:
	// before, the desktop panel said "Saving the photo failed." and the phone said "Photo
	// saved. You get the preset out of it on the desktop."; after, both say the sentence
	// above verbatim. Nothing in the suite noticed the difference — putting the summary
	// back left all 73 tests green and svelte-check at 0 — so it is noticed here.
	//
	// Named handlers rather than a rule over every failed fetch: there are 49 such
	// branches in the components and most of them refuse nothing a reader can act on.
	// When the next one does, it belongs in this list.
	//
	// Anchored on the function and not on "the first /photo in the file": there are now
	// two uploads in TestGridResult — the one that files a picture under a board you
	// picked, and the one that lets the code name its own board — and both carry a
	// refusal a reader has to act on. Anchoring on the string made the test read whichever
	// happened to come first in the file, which is how a third one could slip in unread.
	const handlers: [string, string][] = [
		['PhoneView.svelte', 'async function upload'],
		['TestGridResult.svelte', 'async function uploadPhoto'],
		['TestGridResult.svelte', 'async function readBoardFromPhoto']
	];
	for (const [file, handler] of handlers) {
		const source = readFileSync(join(SRC, 'lib', 'components', file), 'utf8');
		const at = source.indexOf(handler);
		assert.ok(at > 0, `${file} no longer has ${handler}; this test is measuring nothing`);
		assert.match(
			source.slice(at, at + 2200),
			/apiError\(\s*response/,
			`${file}: ${handler} reports its own summary of a refused photograph instead of the sentence the server sent`
		);
	}
});

test('a refusal may bring the number its sentence needs', async () => {
	// For the number that is a constant of the engine layer, not a measurement: a code
	// alone cannot carry it, so `MAX_COUNT` would have to be written down a second time
	// here to say the sentence in Dutch. Measured before this: "More than 200 bridges in
	// one contour is not a cut any more." in an otherwise fully Dutch panel.
	const { apiError, bindLanguage } = await import('../src/lib/i18n/core.ts');
	const refusal = () =>
		new Response(null, {
			headers: {
				'X-OpenKerf-Error': 'bridges.tooMany',
				'X-OpenKerf-Error-Values': '{"max":200}'
			}
		});

	assert.equal(apiError(refusal(), 'English.'), 'More than 200 bridges in one contour is not a cut any more.');
	bindLanguage(() => 'nl');
	assert.equal(apiError(refusal(), 'English.'), 'Meer dan 200 bruggen in één omtrek is geen snede meer.');
	bindLanguage(() => 'en');

	// Rubbish in the header leaves the placeholder visible rather than throwing: a broken
	// header must not take the message down with it.
	const broken = new Response(null, {
		headers: { 'X-OpenKerf-Error': 'bridges.tooMany', 'X-OpenKerf-Error-Values': 'nope' }
	});
	assert.match(apiError(broken, 'English.'), /\{max\}/);
});

test('a list of numbers is not separated by the decimal mark', async () => {
	// Measured in Dutch with three places on a contour: "Op 10, 33,5, 70 procent van de
	// omtrek" — four numbers to read where there are three, because the list separator and
	// the decimal mark are the same character.
	const { list, number, bindLanguage } = await import('../src/lib/i18n/core.ts');
	const places = [10, 33.5, 70];

	assert.equal(list(places.map((p) => number(p))), '10, 33.5 and 70');
	bindLanguage(() => 'nl');
	assert.equal(list(places.map((p) => number(p))), '10, 33,5 en 70');
	bindLanguage(() => 'en');

	assert.equal(list(['10']), '10');
	assert.equal(list([]), '');
});

test('a number in a refusal is written the way the rest of the app writes numbers', async () => {
	// A refusal is not a place where the app may switch notation. Measured before this:
	// a Dutch reader got "Deze lijst heeft 1001 rijen en deze app draagt er hooguit 1000"
	// beside a canvas that writes 1.001 and 1.000 everywhere else — two thousands in one
	// sentence, written two ways.
	//
	// What must NOT be formatted is the plural selector: `t()` reads `n` back with
	// `Number()`, and a Dutch "1.000" parses as 1, which would put a sentence about a
	// thousand rows in the singular.
	const { apiError, bindLanguage } = await import('../src/lib/i18n/core.ts');
	const refusal = (code: string, values: Record<string, unknown>) =>
		new Response(null, {
			headers: {
				'X-OpenKerf-Error': code,
				'X-OpenKerf-Error-Values': JSON.stringify(values)
			}
		});

	bindLanguage(() => 'nl');
	const said = apiError(refusal('series.tooManyRows', { rows: 1001, max: 1000 }), 'English.');
	assert.match(said, /1\.001/, `the row count was not written in Dutch: ${said}`);
	assert.match(said, /1\.000/, `the limit was not written in Dutch: ${said}`);

	// A column name is the reader's own data, whatever it looks like.
	const named = apiError(refusal('series.unknownColumn', { column: '1000' }), 'English.');
	assert.match(named, /1000/, `a column called "1000" was rewritten: ${named}`);
	bindLanguage(() => 'en');
});

test('a label the interface reads follows a language switch', async () => {
	// Measured in the browser: with the material library open, switching to Dutch turned
	// every sentence in the window Dutch — "Materiaalbibliotheek", "Er is nog geen
	// laag…" — and left the four source badges reading "Manual" and "Verified". The
	// table they came from called `t()` in its own initialiser, so it was built once, in
	// whichever language happened to load first, and no switch could reach it. This is
	// the same trap the catalogue's confidence table fell into, and it survived the
	// deletion of that file because it lives in another one.
	const { bindLanguage } = await import('../src/lib/i18n/core.ts');
	const { sourceLabel } = await import('../src/lib/library.svelte.ts');
	bindLanguage(() => 'en');
	const english = sourceLabel('testraster');
	bindLanguage(() => 'nl');
	const dutch = sourceLabel('testraster');
	bindLanguage(() => 'en');
	assert.notEqual(dutch.text, english.text, 'the badge did not follow the language');
	assert.notEqual(dutch.means, english.means, 'the explanation did not follow the language');
});

test('the notification state says its word in the reader’s language', async () => {
	// Measured on the phone view at 390 wide with the app in English: the chip beside
	// "Notifications" read "geblokkeerd". `PhoneView` chose between 'geblokkeerd', 'aan'
	// and 'uit' itself and used that same value as a CSS class, so the word could not be
	// translated without breaking the styling. The desktop said a whole sentence through
	// `permissionText()` at the same moment. One state, two surfaces, one function.
	const { bindLanguage } = await import('../src/lib/i18n/core.ts');
	const { notifyState } = await import('../src/lib/notifications.svelte.ts');
	bindLanguage(() => 'en');
	const english = notifyState('denied', false);
	bindLanguage(() => 'nl');
	const dutch = notifyState('denied', false);
	bindLanguage(() => 'en');
	assert.equal(english.name, 'blocked', 'the class name is not a word on screen');
	assert.equal(dutch.name, english.name, 'the class name followed the language');
	assert.notEqual(dutch.text, english.text, 'the word on screen did not follow the language');
	assert.equal(notifyState('granted', true).name, 'on');
	assert.equal(notifyState('granted', false).name, 'off');
});

test('a measurement on screen is written the way the reader writes numbers', async () => {
	// `formatMm` was `value.toFixed(1)` — an English full stop, whatever the language.
	// It feeds the head position and the mouse position in the status bar, so with the
	// app in Dutch the bar read "241.2, 108.4 mm" ten pixels away from a top bar
	// saying "3,5mm". A laser user reads that number off the screen and types it into a
	// machine; 3,5 against 3.5 is two different values.
	const { bindLanguage } = await import('../src/lib/i18n/core.ts');
	const { formatMm } = await import('../src/lib/api.ts');
	bindLanguage(() => 'en');
	assert.equal(formatMm(241.24), '241.2');
	bindLanguage(() => 'nl');
	assert.equal(formatMm(241.24), '241,2');
	bindLanguage(() => 'en');
	assert.equal(formatMm(null), '—');
});

test('one English word does not quietly become two Dutch ones', () => {
	// The translation may not split what the source language keeps together: two keys
	// with the same English text and two different Dutch texts means the same button
	// says something else depending on the screen. Measured before this round: sixteen
	// such groups, among them "Resume" as *Hervatten* twice and *Hervat* on the phone,
	// and "Paused" as *Pauze* in the top bar and *Gepauzeerd* in the panel.
	//
	// Eight of the sixteen are right, because English is the ambiguous one there: "Cut"
	// is the clipboard and the operation, "Group" is a verb and a thing, "up" is a
	// direction and a place. Those are listed here by their English text with the reason,
	// so the next round does not open them again — and so a *new* divergence, which is
	// what this test is for, stands out.
	const DELIBERATE: Record<string, string> = {
		Cut: 'the clipboard (Knippen) and the operation (Snijden) — English is the ambiguous one',
		Group: 'a verb (Groeperen) and a thing (Groep)',
		Design: 'a verb (Ontwerpen) and a thing (Ontwerp)',
		Burning: 'a phase you are in (Aan het branden) and a column heading (Branden)',
		'Leave it': 'a connection you leave hanging, a sheet you leave standing',
		Size: 'the format of a generated shape (Formaat) and the measure of a corner (Maat)',
		up: 'a direction to move in (naar boven) and an axis to raise (omhoog)',
		left: 'a direction to shift in (naar links) and which corner (links)'
	};
	const byText = new Map<string, string[]>();
	for (const [key, value] of Object.entries(en)) {
		if (typeof value !== 'string') continue;
		byText.set(value, [...(byText.get(value) ?? []), key]);
	}
	const split: string[] = [];
	for (const [text, keys] of byText) {
		if (keys.length < 2 || DELIBERATE[text]) continue;
		const dutch = new Set(keys.map((key) => nl[key]));
		if (dutch.size > 1) split.push(`"${text}" → ${[...dutch].join(' / ')} (${keys.join(', ')})`);
	}
	assert.deepEqual(split, [], `one English word, two Dutch ones: ${split.join(' | ')}`);
	// And the list stays honest: an entry for a text that no longer has two keys is a
	// leftover, and would hide a real divergence later.
	for (const text of Object.keys(DELIBERATE)) {
		assert.ok(
			(byText.get(text) ?? []).length > 1,
			`"${text}" is on the deliberate list but no longer sits under two keys`
		);
	}
});

test('no message is resolved once and kept', () => {
	// The general form of the bug above, so the next one is caught where it is written
	// rather than in a browser: a module-level `const` whose value calls `t()` freezes
	// the language of the first import. Anything the reader sees has to be resolved
	// while it is being drawn — a function, a getter, or a `$derived`.
	for (const path of sources(join(SRC, 'lib'), [], /\.ts$/)) {
		const text = readFileSync(path, 'utf8');
		// Walk the top-level declarations only: an indented `t(` sits inside a function
		// or a class method and is therefore called when it is read.
		const frozen: string[] = [];
		let declaring: string | null = null;
		for (const line of text.split('\n')) {
			const opens = line.match(/^export (?:const|let) (\w+)/);
			if (opens) declaring = opens[1];
			else if (/^\S/.test(line) && !/^\s/.test(line) && !line.startsWith('\t')) {
				// A new top-level statement: the previous declaration is finished, unless
				// this line is its own closing brace.
				if (!/^[)}\]];?$/.test(line.trim())) declaring = null;
			}
			if (declaring && /(?<![A-Za-z0-9_.])t\(/.test(line)) frozen.push(`${declaring} in ${path}`);
		}
		assert.deepEqual(frozen, [], `resolved at import instead of at render: ${frozen.join(', ')}`);
	}
});
