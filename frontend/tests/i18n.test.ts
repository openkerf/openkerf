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
import { readFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const hier = dirname(fileURLToPath(import.meta.url));
const werk = join(hier, '.i18n-tmp');

async function laad(naam: string) {
	const ts = (await import('typescript')).default;
	mkdirSync(werk, { recursive: true });
	const bron = readFileSync(join(hier, '..', 'src', 'lib', 'i18n', `${naam}.ts`), 'utf8');
	// De vertaalbestanden importeren alleen een type uit de runtime; dat kan weg,
	// zodat we ze zonder Svelte-runes kunnen inlezen.
	const zonderTypes = bron.replace(/^import type[^\n]*\n/gm, '').replace(/: Catalogue\b/, '');
	const { outputText } = ts.transpileModule(zonderTypes, {
		compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
	});
	const pad = join(werk, `${naam}.mjs`);
	writeFileSync(pad, outputText);
	return (await import(pad))[naam] as Record<string, unknown>;
}

const en = await laad('en');
const nl = await laad('nl');
rmSync(werk, { recursive: true, force: true });

/** De andere talen, op naam. Groeit mee zodra er een bijkomt. */
const VERTALINGEN: Record<string, Record<string, unknown>> = { nl };

const plaatshouders = (waarde: unknown): string[] => {
	const tekst =
		typeof waarde === 'string'
			? waarde
			: [(waarde as { one: string }).one, (waarde as { other: string }).other].join(' ');
	return [...tekst.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
};

test('de brontaal heeft geen lege of dubbele berichten', () => {
	const gezien = new Map<string, string>();
	for (const [sleutel, waarde] of Object.entries(en)) {
		const tekst = typeof waarde === 'string' ? waarde : (waarde as { other: string }).other;
		assert.ok(tekst && tekst.trim().length > 0, `${sleutel} is leeg`);
		// Dezelfde tekst onder twee sleutels is niet fout, maar wel een teken dat
		// er een sleutel te veel is — de melding zegt welke twee.
		const eerder = gezien.get(tekst);
		if (eerder && tekst.length > 12)
			assert.fail(`"${tekst}" staat onder zowel ${eerder} als ${sleutel}`);
		gezien.set(tekst, sleutel);
	}
});

test('elke vertaling heeft precies de sleutels van de brontaal', () => {
	for (const [taal, catalogus] of Object.entries(VERTALINGEN)) {
		const bron = new Set(Object.keys(en));
		const doel = new Set(Object.keys(catalogus));
		const missend = [...bron].filter((k) => !doel.has(k));
		const extra = [...doel].filter((k) => !bron.has(k));
		assert.deepEqual(missend, [], `${taal} mist sleutels`);
		assert.deepEqual(extra, [], `${taal} heeft sleutels die de brontaal niet kent`);
	}
});

test('de plaatshouders overleven de vertaling', () => {
	for (const [taal, catalogus] of Object.entries(VERTALINGEN)) {
		for (const sleutel of Object.keys(en)) {
			assert.deepEqual(
				plaatshouders(catalogus[sleutel]),
				plaatshouders(en[sleutel]),
				`${taal} › ${sleutel}: andere plaatshouders`
			);
		}
	}
});

test('een meervoud in de brontaal is ook een meervoud in de vertaling', () => {
	for (const [taal, catalogus] of Object.entries(VERTALINGEN)) {
		for (const [sleutel, waarde] of Object.entries(en)) {
			const bronIsMeervoud = typeof waarde === 'object';
			const doelIsMeervoud = typeof catalogus[sleutel] === 'object';
			assert.equal(
				doelIsMeervoud,
				bronIsMeervoud,
				`${taal} › ${sleutel}: ${bronIsMeervoud ? 'meervoud verloren' : 'onverwacht meervoud'}`
			);
			if (bronIsMeervoud) {
				const vorm = catalogus[sleutel] as { one?: string; other?: string };
				assert.ok(vorm.one?.trim(), `${taal} › ${sleutel}: 'one' is leeg`);
				assert.ok(vorm.other?.trim(), `${taal} › ${sleutel}: 'other' is leeg`);
			}
		}
	}
});

test('geen bericht is een halve zin', () => {
	// Een sleutel met een kaal voegwoord of een losse eenheid erin betekent dat er
	// in de opmaak een zin aan elkaar geplakt wordt. Dat werkt in twee talen die
	// dezelfde woordorde hebben en verder nergens.
	const fragmenten = /^(of|and|or|en|van|in|op|to|for|met|the|de|het|een|a|mm|%|·|—)$/i;
	for (const [sleutel, waarde] of Object.entries(en)) {
		const teksten =
			typeof waarde === 'string'
				? [waarde]
				: [(waarde as { one: string }).one, (waarde as { other: string }).other];
		for (const tekst of teksten) {
			assert.ok(
				!fragmenten.test(tekst.trim()),
				`${sleutel} is een fragment ("${tekst}") — maak er een hele zin van`
			);
			assert.ok(
				!/^\s|\s$/.test(tekst),
				`${sleutel} begint of eindigt met witruimte ("${tekst}") — dat is opmaak, geen tekst`
			);
		}
	}
});

test('de vertaling is niet per ongeluk nog de brontaal', () => {
	// Een sleutel die letterlijk gelijk is aan het Engels kán juist zijn
	// ("Project", "Alarm", "OpenKerf"), maar een lange zin die identiek is, is
	// vergeten. De grens ligt bij vier woorden.
	for (const [taal, catalogus] of Object.entries(VERTALINGEN)) {
		for (const [sleutel, waarde] of Object.entries(en)) {
			if (typeof waarde !== 'string') continue;
			// Plaatshouders en losse tekens tellen niet als woord: "bed {width} ×
			// {height} mm" is in beide talen terecht hetzelfde.
			const woorden = waarde.replace(/\{\w+\}/g, ' ').match(/[A-Za-zÀ-ÿ]{2,}/g) ?? [];
			if (woorden.length < 5) continue;
			assert.notEqual(
				catalogus[sleutel],
				waarde,
				`${taal} › ${sleutel} is nog woord voor woord het Engels`
			);
		}
	}
});

test('sleutels zijn semantisch en niet de Engelse tekst', () => {
	for (const sleutel of Object.keys(en)) {
		assert.match(
			sleutel,
			/^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9]+)+$/,
			`${sleutel} volgt niet het patroon groep.naam`
		);
	}
});
