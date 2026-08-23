/**
 * The series: the list on the server, and the row the bed is showing.
 *
 * One design burned once per row of a list. The list itself lives on the server — beside
 * the library, in `openkerf-series.json` — because fifty keyrings is an afternoon's work
 * and a page refresh must not cost it. This store is therefore not a copy of the list but
 * a window onto it: it holds what the last answer said, and every verb sends a request and
 * adopts the answer.
 *
 * The shape of `state` is `Series.check()` and `Series.state()` in
 * `api/openkerf_api/series.py`, field for field. It is typed here once and exported,
 * because three surfaces read it — the Series window, the context panel and the run block
 * in the Job panel — and the run block gets it from the status payload rather than from
 * this store's own `load()`. Two type declarations for one payload is how a field gets
 * renamed on one side only.
 *
 * ## Two rules copied from surfaces that paid for them
 *
 * **The preview and the button ask the same thing.** Both take the same request object,
 * built in one place by the window (`Generators.svelte`'s `opdracht()`), so the screen
 * cannot show a list read with a header row while the button attaches it read as data.
 *
 * **`previewError` is not `error`.** A preview refreshes while somebody is still typing,
 * and half-typed numbers are refused all the time — that is an intermediate state, not a
 * failure. `TestGrid.svelte:82-93` is where that split was measured: with one field the
 * whole preview block fell away mid-typing, the form jumped 300 px wide and the reason sat
 * below the fold. So a quiet round only ever touches `previewError`, and `error` belongs to
 * a button somebody actually pressed.
 */

import { apiError, t } from './i18n/core.ts';
import { burnsFor, resolve, type Row } from './series.ts';

// Re-exported so that a surface reading rows off this store does not have to import
// from two files to name what it is holding.
export type { Row };

/** How long the preview waits after the last keystroke. `Generators.svelte`'s number. */
const PREVIEW_REST_MS = 200;

/**
 * One distinct placeholder the design asks the list for, from `check()['uses']`.
 *
 * One entry per placeholder and not per shape: `{name}` on eight tags is one thing read
 * eight times. `renders` is what it puts on the material *for the row the bed is showing*,
 * and it comes from the engine's own substitution — which is why the window quotes it for
 * the current burn and works the other rows out itself with `resolve()`.
 */
export type SeriesUse = {
	placeholder: string;
	column: string;
	offset: number;
	absolute: boolean;
	/** An engine name (`date`, `time`, `op_*`): answered by the engine, not by the list. */
	reserved: boolean;
	/** Whether the list has this column — or the engine keeps the name itself. */
	known: boolean;
	renders: string;
};

/**
 * A shape that asks for a column the list has not got, from `check()['ghosts']`.
 *
 * Measured on the engine: it renders as the empty string, its bounds come back
 * `(nan, nan, nan, nan)` and it drops out of the snapshot while still counting as
 * burnable — invisible on the canvas and present in the job. That is why the window lists
 * them with a way to fix or delete each one instead of drawing a marker on the bed.
 */
export type SeriesGhost = {
	id: string | null;
	label: string | null;
	text: string;
	missing: string[];
};

/** What the design asks of the list and what it would get: `Series.check()`. */
export type SeriesCheck = {
	attached: boolean;
	row_count: number;
	current_row: number;
	/** Which burn the row falls in, counted from one. Null on a row being skipped. */
	current_burn: number | null;
	burns: number;
	/** How many rows one burn eats: one more than the largest step forward. */
	step: number;
	/** The columns the design reads, spelled the way the list spells them. */
	used_columns: string[];
	uses: SeriesUse[];
	/** The columns the design asks for that the list has not got, lower-cased. */
	unknown: string[];
	blanks: Record<string, number>;
	blank_rows: number;
	ghosts: SeriesGhost[];
	stale: boolean;
	/** `places` when the sheet holds a different number of places, `geometry` when the
	 *  shapes moved. Two stale runs, two different punishments, so the reason travels. */
	stale_reason: string;
	message: string;
};

/** Where the list came from, from `attach()`'s `source` block. */
export type SeriesSource = {
	kind: 'file' | 'numbers';
	name?: string;
	/** Null for a counted range: there was no file, so there is no header question. */
	has_header?: boolean | null;
	header_guess?: boolean | null;
	delimiter?: string | null;
	encoding?: string | null;
	imported_at?: string;
	first?: number;
	last?: number;
	step?: number;
	padding?: number;
};

/** What is true only while a run lasts. The row is not in here: see `Series`' docstring. */
export type SeriesRun = {
	/** Inclusive row ranges: `[[0, 18]]` is the first nineteen rows. */
	done: number[][];
	step: number;
	fingerprint: string;
	sheet_id: string | null;
	started_at: string;
};

/** `Series.state()`: the sum, plus the list and the run around it. */
export type SeriesState = SeriesCheck & {
	source: SeriesSource | null;
	columns: string[];
	skip_blank: boolean;
	run: SeriesRun | null;
};

/** `GET /api/series`, which is the only place the rows themselves travel. */
export type SeriesList = SeriesState & { rows: Row[] };

/** Something the reader's file survived rather than was refused for. */
export type SeriesWarning = { code: string; text: string; values?: Record<string, unknown> };

/**
 * What a file or a counted range turns out to hold, before anything is attached.
 *
 * `has_header` beside `header_guess`, and the delimiter and the encoding as well: each of
 * those is a decision this app took about somebody's file, and a decision taken silently
 * is one they cannot overrule.
 */
export type SeriesPreview = {
	source: SeriesSource;
	columns: string[];
	row_count: number;
	/** The first ten rows only — `SERIES_PREVIEW_ROWS` on the server. */
	rows: Row[];
	has_header: boolean | null;
	header_guess: boolean | null;
	delimiter: string | null;
	encoding: string | null;
	blanks: Record<string, number>;
	warnings: SeriesWarning[];
	/** Only on the answer to an upload: the name the file has on the server. */
	file?: string;
};

/**
 * The body the preview and the attach both take, as `_series_read` reads it.
 *
 * Numbers are not a second kind of series, only a second way of filling the rows in —
 * `first`/`last`/`step`/`padding` build the very shape a file builds, so everything after
 * it is the same. One request type for both doors, for the same reason the server has one
 * route family: a second one is a second place for the two to drift.
 */
export type SeriesRequest =
	| {
			kind: 'file';
			/** The name the upload answered with, not the name on the reader's disk. */
			file: string;
			/** Null means "use the server's guess", which it reports as `header_guess`. */
			has_header?: boolean | null;
			skip_blank?: boolean;
	  }
	| {
			kind: 'numbers';
			first: number;
			last: number;
			step?: number;
			/** How wide the number is written: 3 gives `001`, 0 writes it plain. */
			padding?: number;
			column?: string;
			skip_blank?: boolean;
	  };

export class SeriesStore {
	/** The last answer about the list and the design, or nothing yet. */
	state = $state<SeriesState | null>(null);
	/**
	 * The rows, which ride on `GET /api/series` and nowhere else.
	 *
	 * Deliberately not in the status payload: that goes down every open socket a few times
	 * a minute, and a thousand rows in there is a thousand rows for a number that fits in
	 * a word. So a surface that only shows the rows has to have called `load()`.
	 */
	rows = $state<Row[]>([]);
	/**
	 * What the file or the range turns out to hold, before anything is attached.
	 *
	 * Not called `preview`, because that name is the verb here: the window calls
	 * `preview(request)` on every keystroke and reads the answer off this field.
	 */
	sample = $state<SeriesPreview | null>(null);
	busy = $state(false);
	/** A quiet preview round, which must not disable the button beside it. */
	busyPreview = $state(false);
	error = $state<string | null>(null);
	previewError = $state<string | null>(null);
	/**
	 * The code of the last refusal, from `X-OpenKerf-Error`.
	 *
	 * The sentence alone is not enough for two of these: `series.alreadyBurned` is cleared
	 * by asking again with `confirm`, and the two stale codes are cleared by stopping the
	 * run. A surface that has to offer the way out needs to know which no it got, and
	 * matching on the translated sentence would break in the other language.
	 */
	errorCode = $state<string | null>(null);

	#token: () => string;
	#timer: ReturnType<typeof setTimeout> | null = null;
	/**
	 * Whether the last answer had a list attached — a plain field, deliberately.
	 *
	 * `adopt()` has to know it and `adopt()` runs inside an `$effect`; see there for what
	 * reading a rune in that position costs.
	 */
	#attached = false;
	/**
	 * Answers can overtake each other: somebody keeps typing while a round is in flight.
	 * Only the last request may still set what is on screen — `Generators.svelte:354`.
	 */
	#round = 0;

	constructor(token: () => string) {
		this.#token = token;
	}

	/** Whether there is a list at all. */
	get attached(): boolean {
		return this.state?.attached ?? false;
	}

	/** Whether a run is going, which is what guards the plain Burn button. */
	get running(): boolean {
		return this.state?.run != null;
	}

	/**
	 * How the rows fall into burns, right now.
	 *
	 * The same partition the server computes in `_burns` — same rows, same step, same
	 * skipping — so the numbered burn list on the screen and the burn a verb acts on are
	 * one computation rather than two that agree today. A getter and not a stored field —
	 * `TilingStore.current`'s shape — because the step comes off the design, and the design
	 * changes while the window is open.
	 */
	get burns(): number[][] {
		return burnsFor(
			this.rows,
			this.state?.used_columns ?? [],
			this.state?.step ?? 1,
			this.state?.skip_blank ?? true
		);
	}

	/**
	 * What a burn starting at this row engraves, one entry per place on the sheet.
	 *
	 * Worked out here rather than fetched, because the engine can only be asked about the
	 * row its own pointer stands on and moving that pointer is a write. The engine's own
	 * names are left out: `{date}` is the same date on every plate and says nothing about
	 * which row this is.
	 */
	engraves(row: number): string[] {
		return (this.state?.uses ?? [])
			.filter((use) => !use.reserved)
			.map((use) => resolve(use.placeholder, row, this.rows));
	}

	#headers(json = false): Record<string, string> {
		const headers: Record<string, string> = {};
		const token = this.#token();
		if (token) headers.Authorization = `Bearer ${token}`;
		if (json) headers['Content-Type'] = 'application/json';
		return headers;
	}

	/**
	 * One request, one place where a refusal becomes a sentence.
	 *
	 * `apiError` prefers the translated `api.<code>` over the English sentence the server
	 * sent, so a refusal arrives in the reader's own language wherever the catalogue has
	 * it. The code is kept beside it because two refusals have a way out that the sentence
	 * cannot carry — see `errorCode`.
	 */
	async #send(path: string, init?: RequestInit): Promise<unknown | null> {
		this.busy = true;
		this.error = null;
		this.errorCode = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				const body = await response.json().catch(() => null);
				this.error = apiError(response, body?.detail);
				this.errorCode = response.headers.get('X-OpenKerf-Error');
				return null;
			}
			return await response.json();
		} catch (e) {
			// Without this there is nothing to see when the connection drops: the failure
			// flies out uncaught, `error` stays empty and somebody stands at the machine
			// looking at a button that did nothing.
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	/** Adopt an answer that carries the state, which every verb below returns. */
	#adopt(data: unknown): SeriesState | null {
		if (!data || typeof data !== 'object') return null;
		const state = data as SeriesState;
		this.#attached = state.attached;
		this.state = state;
		// Nothing attached means the rows are gone as well; leaving them would show a burn
		// list for a list that is no longer there.
		if (!state.attached) this.rows = [];
		return state;
	}

	/**
	 * The list, the row and the sum — the window's own route.
	 *
	 * Read, so no token and no gate. Also the only call that brings the rows, which is why
	 * `attach` and `detach` end here as well.
	 */
	async load(): Promise<SeriesList | null> {
		const data = (await this.#send('/api/series')) as SeriesList | null;
		if (!data) return null;
		this.#adopt(data);
		this.rows = data.rows ?? [];
		return data;
	}

	/**
	 * The state as it rides in the status payload, from `_series_state()`.
	 *
	 * The same shape as `load()` minus the rows, and `null` when nothing is attached — so
	 * the run block, the top bar and the phone view all read one fact from one socket
	 * instead of asking three times and drifting. Called from the status store; the rows
	 * are left alone because this payload never carries them and a window that has loaded
	 * them must not lose them on the next heartbeat.
	 *
	 * A `null` here says "nothing is attached", which is *less* than what `load()` answers
	 * about the same situation: `check()` runs with no list too, and its `uses` and
	 * `ghosts` are exactly what the window has to show *before* a list is taken. So a
	 * heartbeat may not overwrite an unattached answer with nothing. Measured without this
	 * guard: the window opened with the ghost list up and it was gone two seconds later —
	 * one heartbeat — and never came back, taking the "In use" mark on the column table
	 * with it.
	 *
	 * Whether something is attached is kept in a plain field rather than read off `state`,
	 * because this method is called from an `$effect`. Reading a rune here would make that
	 * effect depend on `state`, and then our own `load()` setting `state` re-fires it with
	 * the snapshot from *before* the attach — measured that way round as well: the burn
	 * list sat at "0 burns out of 5 rows" until the window was closed and opened again.
	 */
	adopt(state: SeriesState | null) {
		if (!state && !this.#attached) return;
		this.#attached = state?.attached ?? false;
		this.state = state;
		if (!state) this.rows = [];
	}

	// ------------------------------------------------------------- reading a file

	/**
	 * Hand the server a file and hear what is in it. Nothing is attached yet.
	 *
	 * Two steps, like the library bundle and the machine profile: the file keeps its name
	 * in the upload directory so the header question can be answered again without
	 * uploading again. That name — `file` on the answer — is what every request after this
	 * one refers to, never the name on the reader's own disk.
	 *
	 * A refusal here lands in `error` and not in `previewError`: somebody pressed
	 * something, and "this file is larger than 5 MB" is an answer to that press.
	 */
	async upload(file: File): Promise<SeriesPreview | null> {
		const form = new FormData();
		form.append('file', file);
		const data = (await this.#send('/api/series/upload', {
			method: 'POST',
			headers: this.#headers(),
			body: form
		})) as SeriesPreview | null;
		if (data) {
			this.sample = data;
			// A refusal from the round before this belonged to another file.
			this.previewError = null;
		}
		return data;
	}

	/**
	 * The same reading again for a changed answer, on a rest of 200 ms.
	 *
	 * A preview behind a button is not a preview: you only see what you are setting after
	 * you have decided you want to see it. So every change schedules a round, and only the
	 * last round may still set `sample` — a `null` request clears the lot, which is what
	 * "no file chosen yet" looks like.
	 *
	 * It computes and writes nothing on the server and is still behind the write gate,
	 * because it reads a file off that machine's disk by name.
	 */
	preview(request: SeriesRequest | null): void {
		// Whatever is still in flight no longer counts: it belongs to a question this round
		// has overtaken. Without the counter a late answer to older input wipes the newer
		// one, and the reader is looking at the file they had a keystroke ago.
		if (this.#timer) clearTimeout(this.#timer);
		const mine = ++this.#round;
		if (!request) {
			this.sample = null;
			this.previewError = null;
			// Whatever is in flight will find its round overtaken and leave `busyPreview`
			// alone on the way out, so it is cleared here: there is no successor round to
			// do it, and a spinner that never stops is read as a server that never answers.
			this.busyPreview = false;
			return;
		}
		this.#timer = setTimeout(() => void this.#fetchPreview(mine, request), PREVIEW_REST_MS);
	}

	/**
	 * Drop a pending round without touching what is on screen.
	 *
	 * For a component being torn down: the answer would arrive after the window is gone,
	 * and the last valid preview is still the honest thing to have been showing.
	 */
	cancelPreview(): void {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		this.#round += 1;
		this.busyPreview = false;
	}

	async #fetchPreview(mine: number, request: SeriesRequest): Promise<void> {
		this.busyPreview = true;
		this.previewError = null;
		try {
			const response = await fetch('/api/series/preview', {
				method: 'POST',
				headers: this.#headers(true),
				body: JSON.stringify(request)
			});
			const data = await response.json().catch(() => null);
			if (mine !== this.#round) return;
			if (!response.ok) {
				this.previewError = apiError(response, data?.detail);
				return;
			}
			// Only replaced when something valid came out: leaving the last good reading up
			// is calmer than dropping a hole, and more honest too — that is still what you
			// would attach if you stopped typing now.
			this.sample = data as SeriesPreview;
		} catch (e) {
			if (mine === this.#round) {
				this.previewError = t('error.network', {
					message: e instanceof Error ? e.message : String(e)
				});
			}
		} finally {
			if (mine === this.#round) this.busyPreview = false;
		}
	}

	// ---------------------------------------------------------------- the list

	/**
	 * Take this list as the one the design burns from, and show its first row.
	 *
	 * The same request the preview was made with, so the button cannot attach something
	 * other than what was on the screen. It ends in `load()` because attaching is the one
	 * moment the rows themselves change, and the burn list is drawn from those.
	 */
	async attach(request: SeriesRequest): Promise<SeriesList | null> {
		const data = await this.#send('/api/series/attach', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify(request)
		});
		if (!data) return null;
		this.#adopt(data);
		return this.load();
	}

	/**
	 * Rows out of a counted range: "numbered parts 001 to 250".
	 *
	 * Through the very same attach, deliberately. Numbers are not a second kind of series
	 * — our layer already owns the rows, so this is only another way of filling them in —
	 * and answering that job with "go and make a spreadsheet first" would be a step that
	 * exists for the software's convenience. No counter goes anywhere near the engine: its
	 * own counter type increments on every read, so re-rendering the bed to show what is
	 * next would itself move it on.
	 */
	numbers(range: Omit<Extract<SeriesRequest, { kind: 'numbers' }>, 'kind'>) {
		return this.attach({ kind: 'numbers', ...range });
	}

	/** Take the list away, and stop the bed showing names it no longer has. */
	async detach(): Promise<SeriesState | null> {
		const data = await this.#send('/api/series', {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (!data) return null;
		this.rows = [];
		return this.#adopt(data);
	}

	// ----------------------------------------------------------------- the row

	/**
	 * Point the bed at one row, without starting anything.
	 *
	 * Looking at row twelve is reading and not burning. Without this the only way to see
	 * another name was to press Start, which writes a run — so somebody looking around
	 * would have begun one.
	 */
	setRow(row: number) {
		return this.#write('/api/series/row', { row });
	}

	// ----------------------------------------------------------------- the run

	/** Begin the run. `row` counts from nought; left out is where the bed already is. */
	start(row?: number) {
		return this.#write('/api/series/start', row === undefined ? {} : { row });
	}

	/**
	 * Send the burn the bed is showing to the machine.
	 *
	 * The only method in this file that reaches the laser, and the only one a surface may
	 * not call on its own initiative: it belongs to the button in the run block that
	 * somebody standing at the machine presses. `confirm` clears exactly one refusal,
	 * `series.alreadyBurned` — going over work that is already there is only ever right
	 * when the last attempt was spoiled.
	 */
	burn(confirm = false) {
		return this.#write('/api/series/burn', confirm ? { confirm: true } : {});
	}

	/** Move on to the next burn that still has to happen. Marks nothing done. */
	advance() {
		return this.#write('/api/series/advance', undefined);
	}

	/** Burn one of these again: point at its burn and mark that burn undone. */
	redo(row: number) {
		return this.#write('/api/series/redo', { row });
	}

	/** End the run and keep the list, and the row it stopped on. */
	stop() {
		return this.#write('/api/series/stop', undefined);
	}

	/**
	 * Every write that answers with the state, in one place.
	 *
	 * They all answer `state()`, some of them with a field or two extra (`burned`,
	 * `burned_rows`, `finished`), so the answer is adopted and handed back whole for the
	 * caller that cares about those.
	 */
	async #write(path: string, body: Record<string, unknown> | undefined) {
		const data = await this.#send(path, {
			method: 'POST',
			headers: this.#headers(body !== undefined),
			body: body === undefined ? undefined : JSON.stringify(body)
		});
		if (!data) return null;
		this.#adopt(data);
		return data as SeriesState & {
			burned?: number;
			burned_rows?: number[];
			finished?: boolean;
		};
	}
}
