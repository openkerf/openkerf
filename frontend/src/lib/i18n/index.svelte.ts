/**
 * Multilingual OpenKerf: the reactive shell.
 *
 * The lookup itself lives in `core.ts`, in plain TypeScript, so that modules
 * without a Svelte compiler behind them (`api.ts` and its `node --test` tests)
 * can translate too. What is here is the one thing that needs a rune: which
 * language we are in, and remembering a change to it.
 *
 * Components import `t` from here. It is `core.t`, re-exported: it reads the
 * language through the getter handed over below, so a component that calls it
 * re-renders when the language changes — no subscription, no bookkeeping.
 */
import {
	CATALOGUES,
	STORAGE_KEY,
	ago,
	bindLanguage,
	dateTime,
	detect,
	locale,
	mm,
	number,
	t,
	type Language,
	type MessageKey
} from './core.ts';

export {
	LANGUAGES,
	t,
	type Catalogue,
	type Language,
	type Message,
	type MessageKey
} from './core.ts';

class I18n {
	#language = $state<Language>('en');
	/** Set once on the client; the server render is always English. */
	#ready = $state(false);

	constructor() {
		// The binding first, and before anything reads a message: from here on
		// `core.t` follows this rune, which is what makes the switch reactive.
		bindLanguage(() => this.#language);
		// Not in the field initialiser: `detect` touches `window`, and this module
		// is imported during the static build as well.
		if (typeof window !== 'undefined') {
			this.#language = detect();
			this.#ready = true;
		}
	}

	get language(): Language {
		return this.#language;
	}

	set language(next: Language) {
		if (!(next in CATALOGUES)) return;
		this.#language = next;
		if (typeof window !== 'undefined') {
			window.localStorage?.setItem(STORAGE_KEY, next);
			// Screen readers switch voice on this, and the browser hyphenates by it.
			// A page that says `lang="en"` while showing Dutch is read as gibberish.
			document.documentElement.lang = next;
		}
	}

	get ready(): boolean {
		return this.#ready;
	}

	/** The BCP 47 tag for `Intl`. */
	get locale(): string {
		return locale();
	}

	t(key: MessageKey, params?: Record<string, unknown>): string {
		return t(key, params);
	}

	number(value: number, decimals?: number): string {
		return number(value, decimals);
	}

	mm(value: number | null | undefined, decimals = 1): string {
		return mm(value, decimals);
	}

	ago(when: string | number | Date | null | undefined): string {
		return ago(when);
	}

	dateTime(when: string | number | Date | null | undefined): string {
		return dateTime(when);
	}
}

export const i18n = new I18n();
