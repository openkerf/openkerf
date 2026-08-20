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

/** Every file the app is built from, so a key can be looked for in all of them. */
function sources(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) sources(path, found);
		else if (/\.(svelte|ts)$/.test(entry) && !path.includes(`${'i18n'}/`)) found.push(path);
	}
	return found;
}

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
	const DYNAMIC = ['machine.state.', 'machine.hint.', 'job.phase.', 'axis.'];
	for (const prefix of DYNAMIC)
		assert.ok(CODE.includes(`${prefix}$`), `nothing composes ${prefix}… any more — drop it here`);
	const unused = Object.keys(en).filter(
		(key) => !CODE.includes(`'${key}'`) && !DYNAMIC.some((p) => key.startsWith(p))
	);
	assert.deepEqual(unused, [], `keys in the catalogue that nothing uses: ${unused.join(', ')}`);
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
	for (const [key, value] of Object.entries(en)) {
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

test('the translation is not accidentally still the source language', () => {
	// A key that is literally the English *can* be right ("Project", "Alarm",
	// "OpenKerf"), but a long sentence that is identical has been forgotten. The
	// line is drawn at four words.
	for (const [language, catalogue] of Object.entries(TRANSLATIONS)) {
		for (const [key, value] of Object.entries(en)) {
			if (typeof value !== 'string') continue;
			// Placeholders and loose characters do not count as words: "bed {width} ×
			// {height} mm" is rightly the same in both languages.
			const words = value.replace(/\{\w+\}/g, ' ').match(/[A-Za-zÀ-ÿ]{2,}/g) ?? [];
			if (words.length < 5) continue;
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
