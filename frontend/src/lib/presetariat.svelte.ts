/**
 * The shared preset catalogue.
 *
 * Everything here comes from somebody else's machine. That is why every row carries
 * its provenance visibly, and why we import into the local library as "imported" —
 * never as something measured on your machine.
 */

import { t, type MessageKey } from './i18n/core.ts';

export type CataloguePreset = {
	id: string;
	material: string;
	synonyms?: string[];
	thickness_mm: number | null;
	operation: string;
	machine: { laser_type: string; power_watt: number; lens_mm?: number | null };
	speed_mm_s: number;
	power_percent: number;
	passes?: number;
	air_assist?: boolean;
	note?: string;
	source: { kind: 'testraster' | 'handmatig' | 'fabrikant'; by?: string; url?: string };
	verified?: boolean;
	imported?: boolean;
};

/**
 * How much a row's numbers are worth, as a badge.
 *
 * The keys are the catalogue's own `source.kind` values and stay Dutch: they are
 * stored data, not text for a reader — the same carve-out as `preset.source` in the
 * database. What a reader sees is the message, and that is looked up here.
 */
const BADGES: Record<string, { key: MessageKey; tone: string }> = {
	testraster: { key: 'presetariat.confidence.measured', tone: 'ok' },
	fabrikant: { key: 'presetariat.confidence.maker', tone: 'neutral' },
	handmatig: { key: 'presetariat.confidence.starting', tone: 'warn' }
};

/**
 * The badge for one row, translated at the moment it is read.
 *
 * This used to be a module-scope object literal holding the results of three `t()`
 * calls, and that resolves once, at import. Measured against `core.ts`: with the
 * language bound to a variable, the object kept saying `Starting value` after the
 * switch to Dutch while a call-time lookup gave `Startwaarde`. So the three badges
 * froze in whichever language happened to load first and never followed a switch —
 * the one row in the window that is a value judgement, in the wrong language.
 *
 * A function and not a `$derived`: derived state cannot be exported from a module,
 * and it does not need to be. `t()` reads the language through the getter
 * `index.svelte.ts` hands over, so calling this while a component renders makes
 * Svelte see the dependency and re-render on a switch — the same way every other
 * message in the app works.
 *
 * The unknown kind falls back to `handmatig` here rather than at each call site: an
 * unlabelled row is a guess until somebody says otherwise, and that is the honest
 * badge for it.
 */
export function confidence(kind: string | null | undefined): { text: string; tone: string } {
	const badge = BADGES[kind ?? ''] ?? BADGES.handmatig;
	return { text: t(badge.key), tone: badge.tone };
}

/**
 * The old shape, for `Presetariat.svelte` while that window still stands.
 *
 * Getters and not values, so each read translates afresh — the freeze above is in the
 * evaluation moment, not in the shape. This goes when the window does.
 */
export const CONFIDENCE: Record<string, { text: string; tone: string }> = {
	get testraster() {
		return confidence('testraster');
	},
	get fabrikant() {
		return confidence('fabrikant');
	},
	get handmatig() {
		return confidence('handmatig');
	}
};

export class PresetariatStore {
	presets = $state<CataloguePreset[]>([]);
	version = $state<string | null>(null);
	total = $state(0);
	/** From the cache because the network was gone — the user should see that. */
	stale = $state(false);
	busy = $state(false);
	error = $state<string | null>(null);
	chosen = $state<Set<string>>(new Set());

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	async load(options: {
		machineId?: number | null;
		material?: string;
		operation?: string;
		refresh?: boolean;
	} = {}) {
		this.busy = true;
		this.error = null;
		const query = new URLSearchParams();
		if (options.machineId) query.set('machine_id', String(options.machineId));
		if (options.material?.trim()) query.set('material', options.material.trim());
		if (options.operation) query.set('operation', options.operation);
		if (options.refresh) query.set('refresh', 'true');
		try {
			const response = await fetch(`/api/presetariat?${query}`);
			if (!response.ok) {
				this.error = (await response.json().catch(() => null))?.detail ?? t('error.fetchFailed');
				return;
			}
			const data = await response.json();
			this.presets = data.presets;
			this.version = data.version;
			this.total = data.total;
			this.stale = data.stale;
			if (data.error) this.error = t('presetariat.fromCopy', { error: data.error });
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
		} finally {
			this.busy = false;
		}
	}

	toggle(id: string) {
		const next = new Set(this.chosen);
		if (!next.delete(id)) next.add(id);
		this.chosen = next;
	}

	async importChosen(machineId: number | null) {
		if (!this.chosen.size) return null;
		this.busy = true;
		this.error = null;
		try {
			const token = this.#token();
			const response = await fetch('/api/presetariat/import', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify({ ids: [...this.chosen], machine_id: machineId })
			});
			if (!response.ok) {
				this.error = (await response.json().catch(() => null))?.detail ?? t('error.importFailed');
				return null;
			}
			this.chosen = new Set();
			return await response.json();
		} finally {
			this.busy = false;
		}
	}
}
