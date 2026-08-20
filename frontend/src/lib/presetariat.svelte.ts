/**
 * De gedeelde presetcatalogus.
 *
 * Alles hier komt van andermans machine. Daarom draagt elke regel zijn herkomst
 * zichtbaar mee, en importeren we naar de eigen bibliotheek als "geïmporteerd" —
 * nooit als iets wat op jouw machine gemeten is.
 */

import { t } from './i18n/core.ts';

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

export const CONFIDENCE: Record<string, { text: string; tone: string }> = {
	testraster: { text: t('presetariat.confidence.measured'), tone: 'ok' },
	fabrikant: { text: t('presetariat.confidence.maker'), tone: 'neutral' },
	handmatig: { text: t('presetariat.confidence.starting'), tone: 'warn' }
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
			if (data.error) this.error = `Uit de lokale kopie: ${data.error}`;
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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
