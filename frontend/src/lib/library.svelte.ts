/**
 * The local material library.
 *
 * Everything sits in SQLite beside the engine's own settings — no service, no
 * account. A preset knows which machine it came from and where it came from
 * (by hand, extrapolated, test grid), because that determines how far you may
 * trust it.
 */

import { apiError, t } from './i18n/core.ts';

export type Material = { id: number; name: string; synonyms: string[] };

export type Preset = {
	id: number;
	material_id: number;
	material_name: string;
	machine_name: string | null;
	thickness_mm: number | null;
	operation: string;
	speed_mm_s: number;
	power_percent: number;
	passes: number;
	/** Line spacing when rastering; empty for cutting and vector engraving (B12). */
	interval_mm?: number | null;
	air_assist: boolean;
	focus_offset_mm: number;
	source: 'handmatig' | 'geextrapoleerd' | 'testraster' | 'geimporteerd';
	note: string;
	/** The grid this preset came from, if there is a photo of it. */
	grid_id: number | null;
	grid_photo: string | null;
	/** When that grid was burned — the date of the evidence. */
	grid_date?: string | null;
	/** Which square of that grid it became; pointable on the photo. */
	grid_cell?: { row: number; column: number } | null;
	/**
	 * Whether the photo of that grid is aligned. If not, the marker falls back on
	 * four default corners and the outline is only approximate.
	 */
	grid_aligned?: boolean;
	/** The last time this setting was put on a layer. */
	last_used_at?: string | null;
};

export const OPERATIONS = [
	{ value: 'snijden', label: t('operation.cut') },
	{ value: 'graveren-vector', label: t('operation.engraveVector') },
	{ value: 'graveren-raster', label: t('operation.engraveRaster') },
	{ value: 'markeren', label: t('operation.mark') }
];

/**
 * The same operation, without the middle dot.
 *
 * In a dropdown "Engrave · vector" reads fine, but on a card where the middle dot
 * is already the separator between thickness and operation you get
 * "3 mm · Engrave · vector" and no longer know what belongs to what.
 */
export function operationName(value: string): string {
	const label = OPERATIONS.find((o) => o.value === value)?.label ?? value;
	const [main, kind] = label.split(' · ');
	return kind ? `${main} (${kind})` : main;
}

/**
 * Which layer type belongs to which operation.
 *
 * Putting a cut preset on an engrave layer is not a typo but burned material:
 * 12 mm/s at 65% does something very different from 250 mm/s at 20%. We do not
 * block it — sometimes the user knows better — but we do say it.
 */
export const OPERATION_LAYER: Record<string, string[]> = {
	snijden: ['op cut'],
	'graveren-vector': ['op engrave'],
	'graveren-raster': ['op raster', 'op image'],
	markeren: ['op engrave', 'op dots']
};

/**
 * How certain is this preset?
 *
 * A badge alone is too easy to read past: two pills of the same size that differ
 * only in colour and word read as the same thing while scrolling. So every source
 * also carries a shape (the icon), a line saying what it means, and — where it
 * involves risk — a line saying what to do about it. Colour is then the third
 * signal, not the only one.
 */
export const SOURCE_LABEL: Record<
	Preset['source'],
	{ text: string; tone: string; icon: 'check' | 'alert' | 'pen' | 'down'; means: string; advice: string }
> = {
	testraster: {
		text: t('source.verified'),
		tone: 'ok',
		icon: 'check',
		means: t('source.verified.means'),
		advice: ''
	},
	handmatig: {
		text: t('source.manual'),
		tone: 'neutral',
		icon: 'pen',
		means: t('source.manual.means'),
		advice: ''
	},
	geextrapoleerd: {
		text: t('source.extrapolated'),
		tone: 'warn',
		icon: 'alert',
		means: t('source.extrapolated.means'),
		advice: t('source.extrapolated.advice')
	},
	geimporteerd: {
		text: t('source.imported'),
		tone: 'warn',
		icon: 'down',
		means: t('source.imported.means'),
		advice: t('source.imported.advice')
	}
};

/** Two settings about the same thing that carry different numbers. */
export type PresetConflict = {
	material: string;
	thickness_mm: number | null;
	operation: string;
	machine: string | null;
	mine: { speed_mm_s: number; power_percent: number; passes: number; source: string };
	theirs: { speed_mm_s: number; power_percent: number; passes: number; source: string };
};

export type Tally = {
	materials: number;
	presets: number;
	machines: number;
	test_grids: number;
};

/**
 * What is going to happen if you take this file in.
 *
 * Both choices are worked out in full, because the difference between merging and
 * replacing has to be on screen at the moment you choose — not afterwards.
 */
export type ImportPreview = {
	bundle: string;
	exported_at: string | null;
	bevat: Tally & { photos: number };
	current: Tally;
	samenvoegen: {
		materials: {
			new: string[];
			existing: { name: string; as: string; material_id: number }[];
			/** A different name, probably the same board — the M5 pitfall. */
			similar: { name: string; match: string; material_id: number; why: string }[];
		};
		machines: { new: string[]; existing: string[] };
		presets: { new: number; identical: number; conflicts: PresetConflict[] };
		test_grids: { new: number; existing: number };
	};
	vervangen: { removes: Tally };
};

export type ImportResult = {
	mode: string;
	removed: Tally | null;
	materials: number;
	machines: number;
	test_grids: number;
	presets: { added: number; updated: number; skipped: number };
};

export type MachineProfile = {
	id: number;
	name: string;
	power_watt: number | null;
	device_path: string | null;
	/**
	 * The device this profile belongs to no longer exists in the engine.
	 *
	 * The library sits beside the engine and does not follow along when you throw a
	 * machine away or wipe the settings. Without this distinction the list fills up
	 * with names that have nothing behind them any more — and then "for this
	 * machine" says nothing.
	 */
	orphaned: boolean;
	/** How much evidence hangs off it; decides whether it may go. */
	presets: number;
	test_grids: number;
};

export type ActiveMachine = {
	id: number;
	name: string;
	device_path: string | null;
	has_z: number;
	has_autofocus: number;
};

export class LibraryStore {
	materials = $state<Material[]>([]);
	presets = $state<Preset[]>([]);
	machines = $state<MachineProfile[]>([]);
	/** The profile of the machine that is active now; decides what you see here. */
	activeMachine = $state<ActiveMachine | null>(null);
	/** Off: show presets from other machines as well. */
	onlyThisMachine = $state(true);
	busy = $state(false);
	error = $state<string | null>(null);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	#headers(json = false): Record<string, string> {
		const headers: Record<string, string> = {};
		const token = this.#token();
		if (token) headers.Authorization = `Bearer ${token}`;
		if (json) headers['Content-Type'] = 'application/json';
		return headers;
	}

	async #request(path: string, init?: RequestInit) {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	async load() {
		const all = this.onlyThisMachine ? '' : '?all_machines=true';
		const [materials, presets, machines, active] = await Promise.all([
			this.#request('/api/library/materials'),
			this.#request(`/api/library/presets${all}`),
			this.#request('/api/library/machines'),
			// 409 when no machine is active; then the field stays empty and the
			// library shows itself without a machine header.
			this.#request('/api/library/active-machine')
		]);
		if (materials) this.materials = materials;
		if (presets) this.presets = presets;
		if (machines) this.machines = machines;
		this.activeMachine = active ?? null;
		// A failed 409 must not stay behind as an error message.
		if (!active) this.error = null;
	}

	async toggleScope() {
		this.onlyThisMachine = !this.onlyThisMachine;
		await this.load();
	}

	async addMaterial(name: string) {
		const created = await this.#request('/api/library/materials', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ name })
		});
		if (created) await this.load();
		return created;
	}

	async addPreset(preset: Record<string, unknown>) {
		const created = await this.#request('/api/library/presets', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify(preset)
		});
		if (created) await this.load();
		return created;
	}

	async updatePreset(id: number, fields: Record<string, unknown>) {
		const updated = await this.#request(`/api/library/presets/${id}`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(fields)
		});
		if (updated) await this.load();
		return updated;
	}

	async addMachineProfile(profile: Record<string, unknown>) {
		const created = await this.#request('/api/library/machines', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify(profile)
		});
		if (created) await this.load();
		return created;
	}

	async removeMachineProfile(id: number) {
		const done = await this.#request(`/api/library/machines/${id}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	suggest(materialId: number | null, operation: string, thicknessMm: number | null) {
		const params = new URLSearchParams({ operation });
		if (materialId !== null) params.set('material_id', String(materialId));
		if (thicknessMm !== null) params.set('thickness_mm', String(thicknessMm));
		return this.#request(`/api/library/suggest?${params}`);
	}

	async removePreset(id: number) {
		const done = await this.#request(`/api/library/presets/${id}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	applyTo(presetId: number, operationId: string) {
		return this.#request(`/api/library/presets/${presetId}/apply`, {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ operation_id: operationId })
		});
	}

	// -------------------------------------------------- exchange (decision B7)

	/**
	 * Fetch the whole library as one file.
	 *
	 * Through an anchor and not through fetch: that way the browser does what it is
	 * good at — a download with a name, without pulling the file into the page's
	 * memory first.
	 */
	exportBundle() {
		const anchor = document.createElement('a');
		anchor.href = '/api/library/export.openkerf-lib';
		anchor.download = 'library.openkerf-lib';
		anchor.click();
	}

	async uploadBundle(file: File): Promise<ImportPreview | null> {
		this.busy = true;
		this.error = null;
		try {
			const form = new FormData();
			form.append('file', file);
			const response = await fetch('/api/library/import/upload', {
				method: 'POST',
				headers: this.#headers(),
				body: form
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	/** The same preview, recomputed after you have pointed at a material. */
	previewBundle(bundle: string, mergeMaterials: Record<string, number>) {
		return this.#request('/api/library/import/preview', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ bundle, merge_materials: mergeMaterials })
		}) as Promise<ImportPreview | null>;
	}

	async importBundle(
		bundle: string,
		mode: 'samenvoegen' | 'vervangen',
		mergeMaterials: Record<string, number>,
		onConflict: 'eigen' | 'bestand'
	): Promise<ImportResult | null> {
		const done = await this.#request('/api/library/import', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({
				bundle,
				mode,
				merge_materials: mergeMaterials,
				on_conflict: onConflict
			})
		});
		if (done) await this.load();
		return done;
	}

	presetsFor(materialId: number | null) {
		return materialId === null
			? this.presets
			: this.presets.filter((p) => p.material_id === materialId);
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return t('error.noToken');
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return apiError(response, body.detail);
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
	} catch {
		/* generic text below */
	}
	return t('error.libraryRefused', { status: response.status });
}
