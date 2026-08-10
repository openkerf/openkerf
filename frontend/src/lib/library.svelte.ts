/**
 * De lokale materiaalbibliotheek.
 *
 * Alles staat in SQLite naast de instellingen van de engine — geen dienst, geen
 * account. Een preset weet van welke machine hij komt en waar hij vandaan komt
 * (handmatig, geëxtrapoleerd, testraster), want dat bepaalt hoeveel je hem mag
 * vertrouwen.
 */

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
	air_assist: boolean;
	focus_offset_mm: number;
	source: 'handmatig' | 'geextrapoleerd' | 'testraster' | 'geimporteerd';
	note: string;
};

export const OPERATIONS = [
	{ value: 'snijden', label: 'Snijden' },
	{ value: 'graveren-vector', label: 'Graveren · vector' },
	{ value: 'graveren-raster', label: 'Graveren · raster' },
	{ value: 'markeren', label: 'Markeren' }
];

/** Hoe zeker is deze preset? Bepaalt de badge in de materiaalkaart. */
export const SOURCE_LABEL: Record<Preset['source'], { text: string; tone: string }> = {
	testraster: { text: 'Geverifieerd', tone: 'ok' },
	handmatig: { text: 'Handmatig', tone: 'neutral' },
	geextrapoleerd: { text: 'Geëxtrapoleerd', tone: 'warn' },
	geimporteerd: { text: 'Geïmporteerd', tone: 'neutral' }
};

export class LibraryStore {
	materials = $state<Material[]>([]);
	presets = $state<Preset[]>([]);
	machines = $state<{ id: number; name: string; power_watt: number | null }[]>([]);
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
	}

	async load() {
		const [materials, presets, machines] = await Promise.all([
			this.#request('/api/library/materials'),
			this.#request('/api/library/presets'),
			this.#request('/api/library/machines')
		]);
		if (materials) this.materials = materials;
		if (presets) this.presets = presets;
		if (machines) this.machines = machines;
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

	presetsFor(materialId: number | null) {
		return materialId === null
			? this.presets
			: this.presets.filter((p) => p.material_id === materialId);
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return 'Geen of onjuiste token — wijzigen is geblokkeerd.';
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return body.detail;
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
	} catch {
		/* generieke tekst hieronder */
	}
	return `De bibliotheek weigerde de opdracht (${response.status}).`;
}
