/**
 * Multilingual OpenKerf: the machinery, without the reactivity.
 *
 * ## Why this file is separate from `index.svelte.ts`
 *
 * The reactive part needs `$state`, and a module with runes in it can only be
 * compiled by Svelte. That is fine for components, but `api.ts` also puts
 * messages on screen (`jobLabel`, `machineStateLabel`), and its tests run under
 * plain `node --test` — which cannot compile runes. So the lookup lives here in
 * ordinary TypeScript and the reactive shell lives next door.
 *
 * The link between them is `bindLanguage`: the reactive module hands over a
 * getter, and because `t()` calls that getter while a component renders, Svelte
 * still sees the dependency and re-renders on a language switch. Nothing
 * subscribes, nothing needs cleaning up. Without the reactive module loaded — in
 * a test, or during the static build — the getter is the default and everything
 * reads English.
 *
 * The app was written in Dutch throughout, which was the right way to start and
 * the wrong way to stay. English is the core language now — in the interface and
 * in the code — with translations layered on top; Dutch is the first of those.
 *
 * ## Why this and not a library
 *
 * The obvious candidates are Paraglide (compile-time, tree-shaken) and
 * svelte-i18n (runtime store with ICU). Both are good and both are more than this
 * app needs: one language switch at runtime, a few hundred messages, one plural
 * rule per language, and no server-side rendering to coordinate. What this app
 * *does* need is a compile error when a translation is incomplete, and that is
 * cheaper to get from a typed object than from a message-format compiler. Same
 * reasoning as the canvas: plain SVG until measurements say otherwise.
 *
 * ## The shape of a message
 *
 * A message is a string with `{name}` placeholders, or — when a count decides the
 * wording — an object with `one` and `other`. Both English and Dutch have exactly
 * two plural forms, so two is what we support; a language with more (Polish,
 * Russian, Arabic) needs `Intl.PluralRules` here, and the note in the README says
 * so rather than pretending it already works.
 *
 * ## Keys are semantic, not the English text
 *
 * `job.phase.queued.title`, not `'In the queue'`. Rewording the English then
 * costs one line in `en.ts` instead of a rename across the app — and a
 * translator sees where a message lives.
 */
import { en } from './en.ts';
import { nl } from './nl.ts';

/** A message: plain, or one that bends to a count. */
export type Message = string | { one: string; other: string };

export type MessageKey = keyof typeof en;

/**
 * Every language carries exactly the keys of `en` — that is the whole safety net.
 * A missing key is a type error, not a string that says `[job.stop]` at runtime
 * in front of a laser.
 */
export type Catalogue = Record<MessageKey, Message>;

export type Language = 'en' | 'nl';

/**
 * The languages, in the order a picker shows them, each named in its own tongue.
 * "Nederlands", not "Dutch": someone looking for their language is not reading
 * the language they cannot read.
 */
export const LANGUAGES: { code: Language; name: string; english: string }[] = [
	{ code: 'en', name: 'English', english: 'English' },
	{ code: 'nl', name: 'Nederlands', english: 'Dutch' }
];

export const CATALOGUES: Record<Language, Catalogue> = { en, nl: nl as Catalogue };

export const STORAGE_KEY = 'openkerf.language';

/**
 * Which language to open in.
 *
 * A stored choice wins, because it was made on purpose. Otherwise the browser's
 * preference list decides, in its own order of preference — `navigator.languages`
 * and not just `language`, so someone whose first choice we do not have still
 * gets their second. Anything we do not have falls back to English, which is the
 * source language and therefore always complete.
 */
export function detect(): Language {
	if (typeof window === 'undefined') return 'en';
	const stored = window.localStorage?.getItem(STORAGE_KEY);
	if (stored && stored in CATALOGUES) return stored as Language;
	const wanted = navigator.languages?.length ? navigator.languages : [navigator.language];
	for (const tag of wanted) {
		const base = (tag ?? '').toLowerCase().split('-')[0];
		if (base in CATALOGUES) return base as Language;
	}
	return 'en';
}

/** `{n} shapes` with `{ n: 3 }` → `3 shapes`. Unknown names stay put, visibly. */
function fill(template: string, params?: Record<string, unknown>): string {
	if (!params) return template;
	return template.replace(/\{(\w+)\}/g, (whole, name) =>
		name in params ? String(params[name]) : whole
	);
}

/**
 * Where the current language comes from.
 *
 * A plain module cannot hold reactive state, so it does not try: it holds a
 * getter that the reactive module replaces at import time.
 */
let readLanguage: () => Language = () => 'en';

export function bindLanguage(read: () => Language): void {
	readLanguage = read;
}

export function currentLanguage(): Language {
	return readLanguage();
}

/** The BCP 47 tag for `Intl`. */
export function locale(): string {
	return currentLanguage() === 'nl' ? 'nl-NL' : 'en-GB';
}

/**
 * Look up a message.
 *
 * Falls back to English per key rather than per language: a translation that is
 * one message behind should show that one message in English, not send the whole
 * interface back. The types make a gap impossible in this repository, but a
 * translation pack from outside it has no such guarantee.
 */
export function t(key: MessageKey, params?: Record<string, unknown>): string {
	const message = CATALOGUES[currentLanguage()]?.[key] ?? en[key];
	if (message === undefined) {
		// Loud, not silent: an untranslated key is a bug and should look like one.
		if (typeof console !== 'undefined') console.warn(`[i18n] missing key: ${key}`);
		return String(key);
	}
	if (typeof message === 'string') return fill(message, params);
	const count = Number(params?.n ?? params?.count ?? 0);
	const variant = count === 1 ? message.one : message.other;
	return fill(variant, params);
}

/**
 * A number in the reader's notation.
 *
 * This is not decoration. Dutch writes 3,5 mm and English 3.5 mm, and a laser
 * user reads those numbers off the screen and types them into a machine. The app
 * used to force the Dutch comma everywhere, which is wrong the moment the
 * interface is not Dutch.
 */
export function number(value: number, decimals?: number): string {
	if (!Number.isFinite(value)) return '—';
	return new Intl.NumberFormat(locale(), {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals ?? 3
	}).format(value);
}

/**
 * A list of numbers (or of words) in the reader's own notation.
 *
 * Not `join(', ')`. In Dutch the decimal mark *is* a comma, so three positions came out
 * as "Op 10, 33,5, 70 procent" — four numbers to read, not three. `Intl.ListFormat`
 * writes "10, 33,5 en 70" in Dutch and "10, 33.5 and 70" in English, and the separator
 * can then never be the decimal mark. Style "unit" ("10, 33,5, 70") would keep the
 * ambiguity, so this is the long form on purpose.
 */
export function list(parts: string[]): string {
	if (parts.length <= 1) return parts[0] ?? '';
	return new Intl.ListFormat(locale(), { style: 'long', type: 'conjunction' }).format(parts);
}

/** A length, with its unit. Keeps the space that stops "10mm". */
export function mm(value: number | null | undefined, decimals = 1): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—';
	return `${number(value, decimals)} mm`;
}

/**
 * How long ago, in words.
 *
 * `Intl.RelativeTimeFormat` rather than our own table of Dutch phrases: every
 * language it knows comes for free, including the ones we have not translated
 * yet.
 */
export function ago(when: string | number | Date | null | undefined): string {
	if (!when) return '—';
	const then = toDate(when);
	if (!then) return String(when);
	const seconds = (then.getTime() - Date.now()) / 1000;
	const format = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
	const steps: [Intl.RelativeTimeFormatUnit, number][] = [
		['second', 60],
		['minute', 60],
		['hour', 24],
		['day', 7],
		['week', 4.348],
		['month', 12],
		['year', Infinity]
	];
	let value = seconds;
	for (const [unit, size] of steps) {
		if (Math.abs(value) < size) return format.format(Math.round(value), unit);
		value /= size;
	}
	return format.format(Math.round(value), 'year');
}

/** A date and time, short. */
export function dateTime(when: string | number | Date | null | undefined): string {
	if (!when) return '—';
	const then = toDate(when);
	if (!then) return String(when);
	return new Intl.DateTimeFormat(locale(), { dateStyle: 'short', timeStyle: 'short' }).format(then);
}

function toDate(when: string | number | Date): Date | null {
	const then = when instanceof Date ? when : new Date(typeof when === 'string' ? sqlToIso(when) : when);
	return Number.isNaN(then.getTime()) ? null : then;
}

/**
 * SQLite hands back `2026-08-20 19:22:48` in UTC without saying so, and
 * `new Date()` reads that as local time — an hour or two of silent drift in the
 * "used 3 minutes ago" line.
 */
function sqlToIso(value: string): string {
	return /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(value) ? `${value.replace(' ', 'T')}Z` : value;
}

/**
 * The sentence for a refusal from our own API.
 *
 * The engine layer sends its message in `detail` and, when the refusal is one a
 * user can act on, a code in the `X-OpenKerf-Error` header. A code we know wins,
 * because it can be said in the reader's language; anything else falls back to the
 * message, which is English — the source language of that layer.
 *
 * Deliberately not every code: a message that carries numbers ("this box needs 6
 * sheets") keeps its own sentence, because the numbers do not travel in a header
 * and a translated sentence without them says less than the English one with them.
 */
export function apiError(response: Response, detail: string | null | undefined): string {
	const code = response.headers.get('X-OpenKerf-Error');
	const key = `api.${code}` as MessageKey;
	if (!code || !(key in en)) return detail ?? t('notice.failed');
	const carried = brought(response);
	// A `{what}` in the message is the second sentence of a refusal that broke off
	// halfway, and it is chosen from the values rather than written in the catalogue.
	// Without them there is nothing to choose it from, and a sentence with a hole where
	// its advice was says less than the English one the API sent, so that one wins.
	if (!String(en[key]).includes('{what}')) return t(key, written(carried));
	if (typeof carried?.announced !== 'boolean') return detail ?? t('notice.failed');
	return t(key, { ...written(carried), what: whatIsLeft(carried) });
}

/**
 * What an upload that broke off has left on the machine — one of four sentences.
 *
 * The same four the API layer picks between in `ruida_upload._interrupted`, and the
 * same order, because the difference between the first two is the thing this whole
 * refusal exists to say. `sent` counts blocks and `sent === 0` is true at two moments:
 * before the name went out, and after it. From the second one onwards the receiver has
 * opened a file on the panel under that name (`ruida/emulator.py:757`), so a reader who
 * is told there is nothing to clean up leaves an empty file of their own name behind.
 *
 * Which is why this reads `announced` and not the counter. The engine layer got this
 * wrong twice before it split the flag off from the count; branching on the numbers
 * here would make the same mistake once more, in the reader's own language.
 */
function whatIsLeft(carried: Record<string, unknown>): string {
	const sent = Number(carried.sent ?? 0);
	const chunks = Number(carried.chunks ?? 0);
	if (sent === 0 && carried.announced !== true) return t('upload.left.none');
	if (sent === 0) return t('upload.left.named');
	if (sent < chunks) return t('upload.left.partial');
	return t('upload.left.whole');
}

/**
 * The values a coded refusal brings along, exactly as they were sent.
 *
 * Split from `written` below because two of them are not for reading: `announced`
 * decides which sentence is said, and `sent` and `chunks` are compared with each other
 * to do it. Once through `Intl` a block count is the string "1.200", and comparing that
 * with another string is not the comparison the API made.
 */
function brought(response: Response): Record<string, unknown> | undefined {
	const raw = response.headers.get('X-OpenKerf-Error-Values');
	if (!raw) return undefined;
	try {
		const parsed = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object') return undefined;
		return parsed as Record<string, unknown>;
	} catch {
		return undefined;
	}
}

/**
 * The numbers a coded refusal brings along, from `X-OpenKerf-Error-Values`.
 *
 * Only for a number that is a constant of that layer — "at most 200 bridges" — which a
 * code alone cannot carry: measured before this, that refusal came out in English in an
 * otherwise Dutch panel, because the catalogue had no way to learn the 200 and a second
 * copy of it here would be a second source of truth. A refusal whose numbers are measured
 * per call still keeps its English sentence.
 */
function written(carried: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
	if (!carried) return undefined;
	// Numbers go through `Intl`, here as everywhere else. A refusal is not a place
	// where the app may write in another notation than the panel behind it: measured
	// with a Dutch reader, "Deze lijst heeft 1001 rijen en deze app draagt er hooguit
	// 1000" beside a canvas that writes 1.001 everywhere. Anything that is not a
	// number — a column name, a file name, the token that says which end of a range
	// was wrong — is the reader's own data or a key, and is left exactly as it came.
	const said: Record<string, unknown> = {};
	for (const [name, value] of Object.entries(carried)) {
		// `n` and `count` are left as they came: `t()` picks the singular or the
		// plural from them, and it reads them with `Number()`. A Dutch "1.000" would
		// parse back as 1 and put a refusal about a thousand rows in the singular.
		const selects = name === 'n' || name === 'count';
		said[name] = typeof value === 'number' && !selects ? number(value) : value;
	}
	return said;
}
