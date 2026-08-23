/**
 * The sums a series needs between two keystrokes, and nothing else.
 *
 * A series is one design burned once per row of a list, and the window that sets it up
 * has to answer four questions while the reader is still typing: what will this text
 * engrave on row twelve, which columns does the design ask for that the list has not
 * got, how many burns is that, and how many places on the last sheet have no row left
 * to fill them. Every one of those is arithmetic over a list the browser already holds,
 * so asking the server per keystroke would be a round trip for a sum — and a round trip
 * that can arrive late and out of order, which is how a preview comes to show something
 * other than what the button makes.
 *
 * Plain TypeScript, no runes, for the reason `cutpath.ts` gives: this is the half where
 * a mistake costs a plate of material, so it is the half `node --test` can reach.
 *
 * ## The one rule this file lives under
 *
 * **The substitution is the engine's, and these are copies of its arithmetic.** The
 * burn substitutes through `Wordlist.translate` (`meerk40t/core/wordlist.py:507-600`),
 * and `api/openkerf_api/series.py` re-walks that same parsing in Python for the server's
 * own sums. This file is the third reader of one mechanism, which is a real risk, so
 * every function below names its Python counterpart in `api/openkerf_api/series.py`. The
 * two must agree; where they cannot, the comment says so out loud and says why.
 *
 * What is deliberately **not** here: the value a placeholder has on the bed right now.
 * That comes off the server as `check().uses[].renders`, computed by the engine itself,
 * because the panel line and the burn have to be the same sentence. These sums answer
 * "what would row twelve say", which the engine cannot be asked without moving its own
 * pointer.
 */

/** One row of the list, keyed by column name as the reader spelled it. */
export type Row = Record<string, string>;

/**
 * One `{…}` run in a text, read the way the engine reads it.
 *
 * The mirror of `Placeholder` in `api/openkerf_api/series.py`. `text` is the run exactly
 * as it stands in the template so a caller can find it again in the string; `column` is
 * lower-cased and trimmed because that is the key the engine looks up; `absolute` marks
 * the `{name#2}` form, which is a fixed row and therefore does not make a burn eat more
 * rows.
 */
export type Placeholder = {
	text: string;
	column: string;
	offset: number;
	absolute: boolean;
	reserved: boolean;
};

/**
 * Names the engine answers itself, from `RESERVED_COLUMNS` / `RESERVED_PREFIXES` in
 * `api/openkerf_api/series.py`.
 *
 * A column with one of these names would be accepted and then never resolve, because
 * `translate` answers `date` and `time` off the clock before it looks at any content
 * (`core/wordlist.py:538-563`) and the cut plan pushes the `op_*` family per operation.
 * Keeping the list here as well as on the server is duplication with a purpose: the text
 * field has to be able to say "that name is the engine's" before a request goes out.
 */
export const RESERVED_COLUMNS = ['version', 'date', 'time'];
export const RESERVED_PREFIXES = ['op_', 'date@', 'time@'];

/** Whether the engine would answer this name itself instead of from the list. */
export function reservedColumn(name: string | null | undefined): boolean {
	const key = (name ?? '').trim().toLowerCase();
	if (RESERVED_COLUMNS.includes(key)) return true;
	return RESERVED_PREFIXES.some((prefix) => key.startsWith(prefix));
}

/**
 * A whole number the way Python's `int()` reads one, because that is what parses the
 * index in `{name#+2}` (`core/wordlist.py:531`).
 *
 * Leading and trailing whitespace is allowed, which matters: `{name# +1}` hands `" +1"`
 * to `int()` and gets 1, and the space is also what makes that form an absolute row
 * rather than an offset. Python would additionally take `1_0` and non-ASCII digits; JS
 * `\d` would not, and a template with either in it is not a file anybody has.
 */
function wholeNumber(text: string): number | null {
	const trimmed = text.trim();
	return /^[+-]?\d+$/.test(trimmed) ? Number(trimmed) : null;
}

/** The engine's whole template syntax: `_BRACKETS` at `core/wordlist.py:35`. */
const BRACKETS = /\{[^}]+\}/g;

/**
 * Every placeholder in a template, with its column and its offset.
 *
 * A line-for-line copy of `placeholders()` in `api/openkerf_api/series.py`, which is
 * itself a line-for-line copy of `core/wordlist.py:507-535`, including the three quirks
 * a tidier re-implementation would smooth away and thereby disagree with the burn:
 *
 * - the `#` has to be after the first character, so `{#3}` is a column called `#3`;
 * - an index that does not *start* with `+` or `-` is an absolute row, so `{name#2}` is
 *   row 2 whatever the pointer says — and `{name# +1}` is row 1, because the space means
 *   the `+` is no longer first;
 * - the bracketed run is lower-cased and trimmed first, so `{ Name #+1 }` is the column
 *   `name` at offset 1.
 *
 * An index that is not a number at all falls back to offset 0, exactly as the engine's
 * `except ValueError` does.
 */
export function placeholders(text: string | null | undefined): Placeholder[] {
	const found: Placeholder[] = [];
	for (const run of String(text ?? '').match(BRACKETS) ?? []) {
		let key = run.slice(1, -1).toLowerCase().trim();
		let offset = 0;
		let absolute = false;
		const position = key.indexOf('#');
		if (position > 0) {
			const index = key.slice(position + 1);
			key = key.slice(0, position).trim();
			if (!index.startsWith('+') && !index.startsWith('-')) absolute = true;
			offset = wholeNumber(index) ?? 0;
		}
		found.push({
			text: run,
			column: key,
			offset,
			absolute,
			reserved: reservedColumn(key)
		});
	}
	return found;
}

/**
 * The column a placeholder means, matched the way the engine matches it.
 *
 * `find_column()` in `api/openkerf_api/series.py`, and the reason both exist: the engine
 * lower-cases and trims every key it is handed (`core/wordlist.py:143`), so `{Naam}` and
 * `{naam}` are one variable, while the rows keep the reader's own spelling because a
 * column name is their data and not our label. Every comparison between the two goes
 * through here so that no caller has to remember which side it is holding.
 *
 * Returns the column as the list spells it, or null.
 */
export function findColumn(columns: readonly string[], name: string | null | undefined): string | null {
	const key = (name ?? '').trim().toLowerCase();
	if (!key) return null;
	return columns.find((column) => String(column).trim().toLowerCase() === key) ?? null;
}

/**
 * The columns a set of texts actually reads, in the order they were met.
 *
 * `columns_used()` in `api/openkerf_api/series.py`. Lower-cased, because these are keys
 * and not labels; the engine's own names are left out because they answer themselves.
 * Reading order and not sorted, so that the window's column table does not shuffle
 * between two reloads of the same design.
 */
export function columnsUsed(templates: readonly (string | null | undefined)[]): string[] {
	const seen: string[] = [];
	for (const template of templates ?? []) {
		for (const holder of placeholders(template)) {
			if (holder.reserved || !holder.column) continue;
			if (!seen.includes(holder.column)) seen.push(holder.column);
		}
	}
	return seen;
}

/**
 * The columns these texts ask for that the list has not got.
 *
 * `unknown_columns()` in `api/openkerf_api/series.py`, and the same list the server
 * refuses a burn over (`series.unknownColumn`). Each one is a shape that burns nothing:
 * measured, the engine replaces an unknown key with the empty string
 * (`core/wordlist.py:568`), the node's bounds come back `(nan, nan, nan, nan)` and it
 * drops out of the snapshot while still counting as burnable. Having the same answer in
 * the browser is what lets the window name the shape before the button is pressed
 * instead of after.
 */
export function unknownColumns(
	templates: readonly (string | null | undefined)[],
	columns: readonly string[]
): string[] {
	const missing: string[] = [];
	for (const column of columnsUsed(templates)) {
		if (findColumn(columns, column) === null && !missing.includes(column)) missing.push(column);
	}
	return missing;
}

/**
 * How many rows one burn eats: one more than the largest step forward.
 *
 * `step_of()` in `api/openkerf_api/series.py`. A sheet with twelve tags on it reading
 * `{name}` … `{name#+11}` consumes twelve rows per burn, which is the engine's own page
 * idea (`gui/wordlisteditor.py:181-213`). Absolute forms do not count — `{name#2}` is
 * always row 2 — and neither do backwards ones, which are refused where a text is typed.
 * The minimum is one, so that dividing by it is always safe.
 */
export function stepOf(templates: readonly (string | null | undefined)[]): number {
	let biggest = 0;
	for (const template of templates ?? []) {
		for (const holder of placeholders(template)) {
			if (holder.absolute || holder.reserved) continue;
			if (holder.offset > biggest) biggest = holder.offset;
		}
	}
	return biggest + 1;
}

/**
 * The rows that have nothing in one of the columns the design reads.
 *
 * `blank_rows()` in `api/openkerf_api/series.py`. Blank in *any* of them and not all: a
 * plate whose name is missing is a plate with a frame and nothing in it, whichever of
 * its two texts came up empty. `columns` are row keys, already spelled the way the rows
 * are — `findColumn` is where that mapping happens, once, in the caller.
 */
export function blankRows(columns: readonly string[], rows: readonly Row[]): number[] {
	const empty: number[] = [];
	(rows ?? []).forEach((row, index) => {
		if ((columns ?? []).some((column) => !String(row?.[column] ?? '').trim())) empty.push(index);
	});
	return empty;
}

/**
 * How the rows fall into burns: one list of row numbers per burn, in order.
 *
 * `burn_rows()` in `api/openkerf_api/series.py`, and the number the pre-flight multiplies
 * the time of one burn by. With a step of one that is one burn per row and a blank row
 * can simply be left out; with a sheetful it cannot, and that is not a choice anybody
 * gets to make — the engine resolves `{name#+1}` as the row *next to* the pointer
 * (`core/wordlist.py:520-535`), so the twelve places on a sheet are always twelve
 * consecutive rows. A blank row in the middle of a sheetful therefore leaves one tag
 * empty rather than shifting the other eleven along.
 *
 * The last burn is short when the rows run out, which is the burn `overrunPlaces` is
 * about.
 *
 * `columns` is here and not implied by `skipBlank` because blank is per column: which
 * cell has to be filled in depends on which columns the design reads, and that is
 * exactly what the Python signature takes for the same reason.
 */
export function burnsFor(
	rows: readonly Row[],
	columns: readonly string[],
	step = 1,
	skipBlank = true
): number[][] {
	const total = (rows ?? []).length;
	if (step <= 1) {
		const skip = new Set(skipBlank ? blankRows(columns, rows) : []);
		const burns: number[][] = [];
		for (let index = 0; index < total; index += 1) if (!skip.has(index)) burns.push([index]);
		return burns;
	}
	const burns: number[][] = [];
	for (let start = 0; start < total; start += step) {
		const group: number[] = [];
		for (let row = start; row < Math.min(start + step, total); row += 1) group.push(row);
		burns.push(group);
	}
	return burns;
}

/**
 * What the engine would put in one placeholder's place, in the three kinds it has.
 *
 * There are three and not two, and collapsing them is how a preview starts lying:
 *
 * - `value` — a cell, or the empty string for a column the list has not got. The engine
 *   substitutes an unknown key with `""` and does it *before* it ever looks at a row
 *   (`core/wordlist.py:568`), which is why that case is answered first below.
 * - `nothing` — the row is past the end of the list. `fetch_value` answers None
 *   (`core/wordlist.py:266-269`) and `translate` only replaces when the value is not None
 *   (`core/wordlist.py:597`), so the nine characters `{name#+2}` stay in the text and are
 *   engraved as a path like any other. Measured on the server: 326 segments of real
 *   geometry on somebody's ply. This is the state `overrunPlaces` counts and the reason
 *   `OverrunMutator` exists.
 * - `bookkeeping` — a backwards offset that walks off the front of the list. The engine
 *   guards only the upper bound, so from the first row `{name#-1}` reads index 1 of its
 *   own entry and engraves `2` (the row pointer) and `{name#-2}` engraves `1` (the type
 *   field); further back than that, `fetch_value` falls back to the current row
 *   (`core/wordlist.py:263-265`) and engraves the name of the plate you are holding.
 *   Measured, all of it as real geometry. A backwards offset that lands on a row that
 *   *exists* is not this kind: it reads that row, which is a real name on a tag claiming
 *   to be about another one, and it comes back as an ordinary `value` because that is
 *   what gets burned.
 *
 * The one place where this file deliberately does **not** reproduce the engine: a
 * `bookkeeping` fill is not printed. Putting `2` in a preview would teach a reader that
 * the number means something, and it means nothing at all — which is why the server
 * refuses the form where a text is typed (`draw.backwardsPlaceholder`, see
 * `backwardsPlaceholder` below) and why a preview can only meet one in a design that
 * arrived from somewhere else. The run is left standing there, the same as `nothing`,
 * but it is a separate kind so that `overrunPlaces` does not count it as a place with no
 * row: the engine does put *something* there, so the mutator would not take that place
 * off the sheet.
 */
export type Fill =
	| { kind: 'value'; text: string }
	| { kind: 'nothing' }
	| { kind: 'bookkeeping' };

export function fillFor(holder: Placeholder, row: number, rows: readonly Row[]): Fill {
	// The engine's own names, which it answers off the clock or out of the plan. We
	// cannot know them and must not guess: a date invented here would be a date nobody
	// burns. Left standing, and `check().uses[].renders` is where the true one comes from.
	if (holder.reserved || !holder.column) return { kind: 'nothing' };
	const list = rows ?? [];
	// Before the row, exactly as `translate` does it: a key that is not in the register
	// at all is the empty string whatever row the pointer is on. The first row is the
	// column list because `read_rows` puts every column in every row, missing cells
	// included, so there is no row that knows about a column the others do not.
	const spelled = findColumn(Object.keys(list[0] ?? {}), holder.column);
	if (spelled === null) return { kind: 'value', text: '' };
	const target = holder.absolute ? holder.offset : row + holder.offset;
	if (target < 0) return { kind: 'bookkeeping' };
	if (target >= list.length) return { kind: 'nothing' };
	return { kind: 'value', text: String(list[target]?.[spelled] ?? '') };
}

/**
 * What this text engraves on this row.
 *
 * The burn list in the Series window is a column of these, one per burn, and it is the
 * only place a reader can check the list against the design before there is material in
 * the machine. It resolves against `rows` and not against the engine because the engine
 * can only be asked about the row its pointer stands on, and asking it to stand
 * somewhere else is a write.
 *
 * `row` is the row this burn starts at; the list comes with it because an offset reads a
 * *different* row — `{name#+1}` is the next one down — so a single row cannot answer a
 * twelve-up sheet. That is a departure from the parameter list the plan sketched
 * (`resolve(template, row)`), and it is the whole mechanism of a sheetful.
 *
 * A run the engine has nothing to put in is left standing, because that is what gets
 * engraved: see `fillFor`.
 */
export function resolve(template: string | null | undefined, row: number, rows: readonly Row[]): string {
	return String(template ?? '').replace(BRACKETS, (run) => {
		const fill = fillFor(placeholders(run)[0], row, rows);
		return fill.kind === 'value' ? fill.text : run;
	});
}

/**
 * The places on this burn's sheet that the list has no row left for.
 *
 * The browser's copy of `OverrunMutator._leave_out` in `api/openkerf_api/series.py`, and
 * it has to give the same answer: the server removes exactly these shapes from the plan,
 * so this is what the pre-flight promises and what the last sheet comes out as. Returned
 * as the templates themselves rather than a count, because the window says which places
 * stay empty and the pre-flight says how many, and one of those is `.length`.
 *
 * A place is left out when any one of its placeholders has nothing to put there: a text
 * reading `{name} of {name#+1}` with one row left would otherwise burn
 * `Eva of {name#+1}`, and half a sentence engraved is worse than a place left empty.
 *
 * The server decides this by asking the engine to translate and seeing what survives,
 * which is a stronger method than arithmetic — it cannot disagree with the burn about the
 * absolute and reserved forms. This one *is* arithmetic, so it carries those forms
 * itself, in `fillFor`, which is why that function is the only place either question is
 * answered.
 */
export function overrunPlaces(
	templates: readonly (string | null | undefined)[],
	row: number,
	rows: readonly Row[]
): string[] {
	const left: string[] = [];
	for (const template of templates ?? []) {
		const holders = placeholders(template);
		if (!holders.length) continue;
		if (holders.some((holder) => !holder.reserved && fillFor(holder, row, rows).kind === 'nothing')) {
			left.push(String(template));
		}
	}
	return left;
}

/**
 * A placeholder in a line of text, refused to look inside a second brace.
 *
 * `_PLACEHOLDER` in `api/openkerf_api/drawing.py`. The engine's own pattern is
 * `\{[^}]+\}`, which is why a doubled brace is not an escape: it matches the inner pair
 * and leaves the outer brace standing. This one stops at a nested brace so that a
 * doubled one is left over to be seen.
 */
const WELL_FORMED = /\{([^{}]*)\}/g;

/**
 * Whether a curly bracket in this text does not open and close exactly once.
 *
 * `_check_placeholders` in `api/openkerf_api/drawing.py` raises `draw.bracesInText` for
 * precisely this, and the text field asks the question here so the answer arrives while
 * the reader is still typing rather than after they press Place. Measured on the engine's
 * own `wordlist_translate`: `'a {{name}}'` renders `'a }'` and `'{{name}'` renders `''` —
 * the inner pair is read as a key nobody has and deleted, and what is left of the outer
 * braces is what gets engraved. A lone `'{name'` survives as itself, which is the same
 * mistake pointing the other way. There is no escape in the engine's syntax, so a
 * bracket cannot be asked for as a bracket at all.
 */
export function bracesInText(text: string | null | undefined): boolean {
	const value = String(text ?? '');
	const remainder = value.replace(WELL_FORMED, '');
	const names = [...value.matchAll(WELL_FORMED)].map((match) => match[1]);
	return remainder.includes('{') || remainder.includes('}') || names.some((name) => !name.trim());
}

/**
 * Whether a placeholder in this text counts backwards.
 *
 * `draw.backwardsPlaceholder`, and the measurement behind it is in `fillFor`: there is no
 * offset here that means what it says. The reading of the modifier is kept deliberately
 * identical to `core/wordlist.py:518-531` — a `#` after the first character, and a sign
 * that makes the number an offset rather than a row of its own — because a refusal the
 * engine does not share is a text you cannot place and cannot explain.
 */
export function backwardsPlaceholder(text: string | null | undefined): boolean {
	for (const name of [...String(text ?? '').matchAll(WELL_FORMED)].map((match) => match[1])) {
		const key = name.toLowerCase().trim();
		const hash = key.indexOf('#');
		if (hash <= 0) continue;
		const modifier = key.slice(hash + 1);
		if (!modifier.startsWith('+') && !modifier.startsWith('-')) continue;
		const offset = wholeNumber(modifier);
		// An index the engine cannot parse it reads as zero, so it is not backwards.
		if (offset !== null && offset < 0) return true;
	}
	return false;
}

/**
 * The refusal this text would earn, as the code the server would send.
 *
 * The code and not a sentence, so that the surface looks the message up under `api.<code>`
 * — the very key `apiError()` would choose if the request went out and came back refused.
 * That is what makes "the preview and the refusal come from one sum" true rather than
 * aspirational: one text, one code, one sentence, whichever side of the wire says no.
 *
 * The order is the server's order (`_check_placeholders` checks the braces first),
 * because a text with an unmatched brace in it has no placeholder to have a direction.
 */
export function textProblem(
	text: string | null | undefined
): 'draw.bracesInText' | 'draw.backwardsPlaceholder' | null {
	if (bracesInText(text)) return 'draw.bracesInText';
	if (backwardsPlaceholder(text)) return 'draw.backwardsPlaceholder';
	return null;
}
