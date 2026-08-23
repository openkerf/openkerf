/**
 * The series sums: what the window promises is what the machine does.
 *
 * Run: `node --test frontend/tests/series.test.ts`
 *
 * Every case here has a twin in `api/tests/test_series.py`, and that is the point of the
 * file. The browser answers "what does row twelve engrave" while somebody is typing, the
 * server answers the same question when it refuses a burn, and the engine answers it once
 * more with a laser on. Three readers of one syntax is where a preview learns to lie, so
 * the cases picked out below are exactly the ones where a tidier re-implementation would
 * be tidier and wrong: an offset past the end of the list, the absolute form, the absolute
 * form that is only absolute because of a space, a blank cell, two placeholders in one
 * text, and a column the list has not got.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	backwardsPlaceholder,
	blankRows,
	bracesInText,
	burnsFor,
	columnsUsed,
	fillFor,
	findColumn,
	overrunPlaces,
	placeholders,
	resolve,
	reservedColumn,
	stepOf,
	textProblem,
	unknownColumns,
	type Row
} from '../src/lib/series.ts';

/** The five names every measurement in `api/tests/test_series.py` was taken over. */
const FIVE: Row[] = ['Anna', 'Bram', 'Cees', 'Daan', 'Eva'].map((name) => ({ name }));

// --------------------------------------------------------------------------- //
// placeholders: the engine's parsing, quirks included
// --------------------------------------------------------------------------- //

test('a plain placeholder is the column at the row the pointer is on', () => {
	assert.deepEqual(placeholders('Hello {name}!'), [
		{ text: '{name}', column: 'name', offset: 0, absolute: false, reserved: false }
	]);
});

test('an index without a sign is a fixed row and not an offset', () => {
	// Measured on the engine with the pointer on row 1 of the five names: `{name#2}`
	// rendered `Cees` (the third name) while `{name#+2}` rendered `Daan` (two on from
	// Bram). Reading it as an offset would make `stepOf` over-count and hand every burn
	// two rows it never uses.
	const [holder] = placeholders('{name#2}');

	assert.equal(holder.absolute, true);
	assert.equal(holder.offset, 2);
	assert.equal(stepOf(['{name#2}']), 1);
});

test('a space before the sign turns an offset into a fixed row', () => {
	// The engine's own quirk, reproduced on purpose: the sign test is `startswith` on the
	// raw index string (`core/wordlist.py:526-531`), so a space in front of the `+` makes
	// it an absolute index while `int(" +1")` still parses as 1. Measured: `{name# +1}`
	// rendered `Bram` — row 1 counted from the top — where `{name#+1}` rendered `Cees`.
	const [holder] = placeholders('{name# +1}');

	assert.equal(holder.absolute, true);
	assert.equal(holder.offset, 1);
	assert.equal(resolve('{name# +1}', 3, FIVE), 'Bram');
});

test('the column name is lower-cased and trimmed the way the engine does it', () => {
	const [holder] = placeholders('{ Name #+1 }');

	assert.equal(holder.column, 'name');
	assert.equal(holder.offset, 1);
	// The run as typed, so the caller can find it back in the string it came from.
	assert.equal(holder.text, '{ Name #+1 }');
});

test('a hash at the start is part of the column name', () => {
	// The engine needs the hash after the first character (`pos > 0`,
	// `core/wordlist.py:520`). Reading `{#3}` as an index would invent a row nobody asked
	// for, and here it would silently make a burn eat four rows.
	const [holder] = placeholders('{#3}');

	assert.equal(holder.column, '#3');
	assert.equal(holder.offset, 0);
	assert.equal(holder.absolute, false);
});

test('an index that is not a number falls back to the first row', () => {
	// `except ValueError` in the engine, so `{name#abc}` is index 0 — absolute, because
	// nothing signed it. Refusing it here would refuse a text the engine renders happily.
	const [holder] = placeholders('{name#abc}');

	assert.equal(holder.offset, 0);
	assert.equal(holder.absolute, true);
	assert.equal(resolve('{name#abc}', 4, FIVE), 'Anna');
});

test("the engine's own names are marked and not treated as columns", () => {
	const found = placeholders('{name} {date} {op_power} {date@%Y}');

	assert.deepEqual(
		found.map((holder) => holder.reserved),
		[false, true, true, true]
	);
	assert.deepEqual(columnsUsed(['{name} {date} {op_power}']), ['name']);
	assert.deepEqual(unknownColumns(['{name} {date}'], ['name']), []);
	assert.equal(reservedColumn('Date'), true);
	assert.equal(reservedColumn('op_speed'), true);
	assert.equal(reservedColumn('name'), false);
});

test('a text without a placeholder has none', () => {
	// `{}` included: the engine's pattern needs a character between the brackets, so both
	// brackets are engraved rather than read.
	assert.deepEqual(placeholders('Anna'), []);
	assert.deepEqual(placeholders('{}'), []);
	assert.deepEqual(placeholders(''), []);
	assert.deepEqual(placeholders(null), []);
});

// --------------------------------------------------------------------------- //
// resolve: what a burn engraves
// --------------------------------------------------------------------------- //

test('a placeholder becomes the cell of the row the burn is on', () => {
	assert.equal(resolve('Hello {name}!', 0, FIVE), 'Hello Anna!');
	assert.equal(resolve('Hello {name}!', 4, FIVE), 'Hello Eva!');
});

test('an offset reads further down the list, which is what makes a sheetful', () => {
	// Measured on the engine with the pointer on row 1: `{name}` rendered `Bram`,
	// `{name#+1}` rendered `Cees` and `{name#+2}` rendered `Daan`.
	assert.equal(resolve('{name} {name#+1} {name#+2}', 1, FIVE), 'Bram Cees Daan');
});

test('two placeholders in one text do not cascade into each other', () => {
	// The measured trap on the server side of this syntax, and the reason both
	// implementations rebuild the string in one pass instead of replacing run by run: over
	// `"{name} {name#+1}"` a replace of the first run turns it into the second, and the
	// second replacement then hits both. That gave two places engraving one row.
	assert.equal(resolve('{name} {name#+1}', 0, FIVE), 'Anna Bram');
	assert.equal(resolve('{name}{name}', 2, FIVE), 'CeesCees');
});

test('an offset past the end leaves the placeholder standing, because that is what burns', () => {
	// This is the whole reason `OverrunMutator` exists. `fetch_value` answers None past
	// the end (`core/wordlist.py:266-269`) and `translate` only replaces a value that is
	// not None (`core/wordlist.py:597`), so those nine characters are engraved as a path
	// like any other — measured at 326 segments on the server's own plan. A preview that
	// showed an empty tag here would promise a blank plate and deliver `{name#+2}`.
	assert.equal(resolve('{name} {name#+2}', 4, FIVE), 'Eva {name#+2}');
	assert.equal(fillFor(placeholders('{name#+2}')[0], 4, FIVE).kind, 'nothing');
	assert.equal(resolve('{name}', 5, FIVE), '{name}');
});

test('an absolute placeholder is the same row on every burn', () => {
	// How somebody puts one heading on a whole sheet: `{name#0}` is row nought whatever
	// the pointer says, so it does not move with the burn and does not make it eat a row.
	for (let row = 0; row < FIVE.length; row += 1) {
		assert.equal(resolve('{name#0}', row, FIVE), 'Anna');
	}
	assert.equal(resolve('{name#4}', 0, FIVE), 'Eva');
	// And past the end it stays standing, exactly like an offset that overshoots.
	assert.equal(resolve('{name#9}', 0, FIVE), '{name#9}');
});

test('a blank cell resolves to nothing, and says so rather than looking like a name', () => {
	// Measured before this feature existed: a blank cell produced no warning anywhere and
	// the plate came out of the machine with the frame burned and the name missing.
	const rows: Row[] = [{ name: 'Anna' }, { name: '' }, { name: '  ' }, { name: 'Daan' }];

	assert.equal(resolve('Tag: {name}', 1, rows), 'Tag: ');
	assert.deepEqual(blankRows(['name'], rows), [1, 2]);
	assert.deepEqual(burnsFor(rows, ['name']), [[0], [3]]);
});

test('a column the list has not got becomes the empty string, and is named', () => {
	// The ghost. Measured on the engine: an unknown key is replaced with the empty string
	// (`core/wordlist.py:568`), the node's bounds come back `(nan, nan, nan, nan)` and it
	// drops out of the snapshot while still counting as burnable — invisible on the
	// canvas and present in the job. Naming it is what makes the refusal actionable.
	assert.equal(resolve('{name} {nope}', 0, FIVE), 'Anna ');
	assert.deepEqual(unknownColumns(['{name} {nope}', '{ALSO}'], ['Name']), ['nope', 'also']);
	// A key that is not in the register is empty whatever row the pointer is on, so the
	// unknown column is answered before the row is even looked at.
	assert.equal(resolve('{nope}', 99, FIVE), '');
});

test("the engine's own names are left standing, because only the engine knows them", () => {
	// `{date}` renders through `strftime('%x')` at burn time. Inventing one here would put
	// a date in the burn list that nobody burns; the true one comes off the server as
	// `check().uses[].renders`, computed by the engine itself.
	assert.equal(resolve('{name} {date}', 0, FIVE), 'Anna {date}');
});

test("a column is matched the way the engine matches it, not the way it is spelled", () => {
	// The engine lower-cases every key it is handed (`core/wordlist.py:143`), so `{Naam}`
	// and `{naam}` are one variable while the rows keep the reader's own spelling.
	const rows: Row[] = [{ Naam: 'Anna' }, { Naam: 'Bram' }];

	assert.equal(findColumn(['Naam'], 'naam'), 'Naam');
	assert.equal(findColumn(['Naam'], 'city'), null);
	assert.equal(resolve('{naam}', 1, rows), 'Bram');
	assert.deepEqual(unknownColumns(['{ NAAM }'], ['Naam']), []);
});

// --------------------------------------------------------------------------- //
// burnsFor and stepOf: how rows become burns
// --------------------------------------------------------------------------- //

test('one row is one burn, and the pre-flight multiplies by that', () => {
	// Fails on any partition that counts the rows of the last burn as a whole one, which
	// is the off-by-one that makes a series of fifty show the time of forty-nine.
	assert.deepEqual(burnsFor(FIVE, ['name']), [[0], [1], [2], [3], [4]]);
	assert.deepEqual(burnsFor([], ['name']), []);
});

test('a blank row is passed over unless it is asked for', () => {
	const rows: Row[] = ['Anna', '', 'Cees', '  ', 'Eva'].map((name) => ({ name }));

	assert.deepEqual(burnsFor(rows, ['name']), [[0], [2], [4]]);
	assert.deepEqual(burnsFor(rows, ['name'], 1, false), [[0], [1], [2], [3], [4]]);
});

test('a sheetful cannot skip a blank row and does not pretend to', () => {
	// The honest half of `skipBlank`, and it is not a choice anybody gets to make: the
	// engine resolves `{name#+1}` as the row *next to* the pointer, so the three places on
	// a sheet are always three consecutive rows. Skipping the blank one would shift the
	// other two along and every remaining row would land on the wrong tag.
	const rows: Row[] = ['Anna', '', 'Cees', 'Daan', 'Eva', 'Finn', 'Gerda'].map((name) => ({
		name
	}));

	assert.deepEqual(burnsFor(rows, ['name'], 3), [
		[0, 1, 2],
		[3, 4, 5],
		[6]
	]);
});

test('the step is one more than the biggest step forward', () => {
	assert.equal(stepOf(['{name}', '{name#+3}']), 4);
	assert.equal(stepOf(['{name#+11}']), 12);
	// A rectangle is not a place on the sheet, and neither is a plain label.
	assert.equal(stepOf(['{name}', '', null, 'Serial no.']), 1);
	// The minimum is one, so that dividing by it is always safe: a step of nought would
	// make the burn count infinite and the progress line meaningless.
	assert.equal(stepOf([]), 1);
	// A backwards read eats no extra rows; it is refused where the text is typed.
	assert.equal(stepOf(['{name#-1}']), 1);
	// One burn covers one sheetful, and a sheetful is as deep as its deepest place.
	assert.equal(stepOf(['{name} {code}', '{name#+1} {code#+1}', '{name#+2}']), 3);
});

// --------------------------------------------------------------------------- //
// overrunPlaces: the last sheet
// --------------------------------------------------------------------------- //

test('the last sheet leaves out the places it has no rows for', () => {
	// The server's own measurement, three texts at offsets 0, 1 and 2 over five names with
	// the burn starting at row 3: the plan held `Daan`, `Eva` and a third shape of 326
	// segments whose text was `{name#+2}`. This sum is what the pre-flight says about that
	// before the sheet goes in, and it has to agree with the mutator that removes them.
	const places = ['{name}', '{name#+1}', '{name#+2}'];

	assert.deepEqual(overrunPlaces(places, 3, FIVE), ['{name#+2}']);
	assert.deepEqual(overrunPlaces(places, 0, FIVE), []);
	assert.deepEqual(overrunPlaces(places, 4, FIVE), ['{name#+1}', '{name#+2}']);
});

test('a place goes whole or not at all, so half a sentence is never engraved', () => {
	// A text reading `{name} of {name#+1}` with one row left would otherwise burn
	// `Eva of {name#+1}`, and half a sentence engraved is worse than a place left empty.
	assert.deepEqual(overrunPlaces(['{name} of {name#+1}'], 4, FIVE), ['{name} of {name#+1}']);
});

test('a place the list has no column for is not an overrun and stays on the sheet', () => {
	// The two failures are told apart on purpose. A column the list has not got is
	// substituted with the empty string, so the shape stays in the plan and burns nothing
	// — that is the ghost, refused before the burn by `vet()`. Counting it here would take
	// a shape off the sheet that the server leaves on it, and then the pre-flight would be
	// describing a different plate than the one that comes out.
	assert.deepEqual(overrunPlaces(['{nope}'], 0, FIVE), []);
	// The engine's own names are answered by the engine, so they are never an overrun.
	assert.deepEqual(overrunPlaces(['{date}'], 4, FIVE), []);
	// And a plain label is not a place that reads the list at all.
	assert.deepEqual(overrunPlaces(['Serial no.'], 4, FIVE), []);
});

// --------------------------------------------------------------------------- //
// The brace cases
// --------------------------------------------------------------------------- //

test('a doubled brace is not an escape and is refused as one', () => {
	// Measured on the engine's own `wordlist_translate`: `'a {{name}}'` renders `'a }'` and
	// `'{{name}'` renders `''`. The inner pair is read as a key nobody has and deleted, and
	// what is left of the outer braces is what gets engraved. There is no escape in the
	// syntax and there cannot be one, so this is a refusal and not a rendering rule.
	assert.equal(bracesInText('a {{name}}'), true);
	assert.equal(bracesInText('{{name}'), true);
	assert.equal(textProblem('a {{name}}'), 'draw.bracesInText');
});

test('a brace that never closes is refused as well', () => {
	// The same mistake pointing the other way: a lone `{name` survives as itself, so the
	// reader who meant a name from the list gets five letters more than they meant.
	assert.equal(bracesInText('{name'), true);
	assert.equal(bracesInText('name}'), true);
	// `{}` is the same story with nothing in it — the engine's pattern needs a character
	// between the braces, so both brackets go on the workpiece.
	assert.equal(bracesInText('{}'), true);
	assert.equal(bracesInText('{ }'), true);
});

test('an ordinary placeholder is not a brace problem', () => {
	for (const text of ['{name}', 'Tag {name} / {code#+1}', 'plain', '', '{ Name #+1 }']) {
		assert.equal(bracesInText(text), false, text);
		assert.equal(textProblem(text), null, text);
	}
});

test('a placeholder that counts backwards is refused, because it reads bookkeeping', () => {
	// Measured with a three-name list standing on its first row: `{name#-1}` engraves `2`
	// (the row pointer) and `{name#-2}` engraves `1` (the type field), both as real
	// geometry on a real node. One row further along it silently reads a different row
	// instead, which is worse rather than better.
	assert.equal(backwardsPlaceholder('{name#-1}'), true);
	assert.equal(backwardsPlaceholder('{name#+1}'), false);
	// The space quirk again: ` -1` does not start with a sign, so the engine reads it as
	// row minus one of its own bookkeeping — but not as a backwards *offset*, and a
	// refusal the engine does not share is a text you cannot place and cannot explain.
	assert.equal(backwardsPlaceholder('{name#-abc}'), false);
	assert.equal(textProblem('{name#-2}'), 'draw.backwardsPlaceholder');
});

test('braces are answered before direction, the same order the server checks in', () => {
	// A text with an unmatched brace in it has no placeholder to have a direction, so
	// naming the direction first would send somebody looking for a minus sign that is not
	// their problem.
	assert.equal(textProblem('{{name#-1}}'), 'draw.bracesInText');
});

test('a backwards read walks off the front of the list rather than showing a number', () => {
	// Both halves of the measured behaviour, and this is why the form is refused rather
	// than rendered. From row 2 it silently reads row 1 — a real name, on a tag that says
	// it is about another row. From row 0 it walks off the front into the list's own
	// fields, where the engine engraves `2` (the row pointer) and `{name#-2}` engraves `1`
	// (the type field). Printing that here would teach a reader that the number means
	// something, and it means nothing at all.
	assert.equal(resolve('{name#-1}', 2, FIVE), 'Bram');
	assert.equal(resolve('{name#-1}', 0, FIVE), '{name#-1}');
	assert.equal(fillFor(placeholders('{name#-1}')[0], 0, FIVE).kind, 'bookkeeping');
	// And it is not an overrun: the engine does put something there, so the mutator leaves
	// that place on the sheet and the pre-flight must not say it comes off.
	assert.deepEqual(overrunPlaces(['{name#-1}'], 0, FIVE), []);
});
