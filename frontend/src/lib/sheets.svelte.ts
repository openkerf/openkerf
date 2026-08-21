/**
 * Sheets: more than one piece of material in one project.
 *
 * Every sheet is a document of its own in the engine. Switching saves the current
 * one and loads the other, so after a switch the design has to be fetched again —
 * which is why every action here reports back through `onSwitched`.
 */

import { apiError, t } from './i18n/core.ts';

export type Sheet = {
	id: string;
	name: string;
	width_mm: number;
	height_mm: number;
	/** What is being burned in. Empty is allowed: an offcut of unknown provenance
	 *  does not need an invented name. */
	material_id: number | null;
	thickness_mm: number | null;
	active: boolean;
};

export class SheetStore {
	sheets = $state<Sheet[]>([]);
	busy = $state(false);
	error = $state<string | null>(null);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	get active(): Sheet | null {
		return this.sheets.find((s) => s.active) ?? null;
	}

	async load() {
		try {
			const response = await fetch('/api/sheets');
			if (response.ok) this.sheets = (await response.json()).sheets;
		} catch {
			/* without sheets the app falls back to the bed */
		}
	}

	async #send(path: string, method = 'POST', body?: unknown) {
		this.busy = true;
		this.error = null;
		try {
			const token = this.#token();
			const response = await fetch(path, {
				method,
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = apiError(response, (await response.json().catch(() => null))?.detail);
				return false;
			}
			this.sheets = (await response.json()).sheets;
			return true;
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return false;
		} finally {
			this.busy = false;
		}
	}

	add(fields: Record<string, unknown> = {}) {
		return this.#send('/api/sheets', 'POST', fields);
	}

	activate(id: string) {
		return this.#send(`/api/sheets/${encodeURIComponent(id)}/activate`);
	}

	update(id: string, fields: Record<string, unknown>) {
		return this.#send(`/api/sheets/${encodeURIComponent(id)}`, 'PATCH', fields);
	}

	remove(id: string) {
		return this.#send(`/api/sheets/${encodeURIComponent(id)}`, 'DELETE');
	}

	move(ids: string[], to: string) {
		return this.#send(`/api/sheets/${encodeURIComponent(to)}/move`, 'POST', { ids });
	}
}
