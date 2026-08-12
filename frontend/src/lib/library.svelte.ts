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
	/** Lijnafstand bij rasteren; leeg bij snijden en vectorgraveren (B12). */
	interval_mm?: number | null;
	air_assist: boolean;
	focus_offset_mm: number;
	source: 'handmatig' | 'geextrapoleerd' | 'testraster' | 'geimporteerd';
	note: string;
	/** Het raster waar deze preset uit komt, als daar een foto van is. */
	grid_id: number | null;
	grid_photo: string | null;
	/** Wanneer dat raster gebrand is — de datum van het bewijs. */
	grid_date?: string | null;
	/** Welk vakje van dat raster het werd; aanwijsbaar op de foto. */
	grid_cell?: { row: number; column: number } | null;
	/**
	 * Of de foto van dat raster uitgelijnd is. Zo niet, dan valt de markering
	 * terug op vier standaardhoeken en ligt de omtrek er bij benadering.
	 */
	grid_aligned?: boolean;
	/** Laatste keer dat deze instelling op een laag gezet is. */
	last_used_at?: string | null;
};

export const OPERATIONS = [
	{ value: 'snijden', label: 'Snijden' },
	{ value: 'graveren-vector', label: 'Graveren · vector' },
	{ value: 'graveren-raster', label: 'Graveren · raster' },
	{ value: 'markeren', label: 'Markeren' }
];

/**
 * Dezelfde bewerking, zonder middenpunt.
 *
 * In een keuzelijst leest "Graveren · vector" prima, maar op een kaart waar het
 * middenpunt al de scheiding is tussen dikte en bewerking, krijg je
 * "3 mm · Graveren · vector" en weet je niet meer wat bij wat hoort.
 */
export function operationName(value: string): string {
	const label = OPERATIONS.find((o) => o.value === value)?.label ?? value;
	const [hoofd, soort] = label.split(' · ');
	return soort ? `${hoofd} (${soort})` : hoofd;
}

/**
 * Welk laagtype bij welke bewerking hoort.
 *
 * Een snijpreset op een graveerlaag zetten is geen tikfout maar verbrand
 * materiaal: 12 mm/s op 65% doet iets heel anders dan 250 mm/s op 20%. We
 * blokkeren het niet — soms weet de gebruiker beter — maar we zeggen het wel.
 */
export const OPERATION_LAYER: Record<string, string[]> = {
	snijden: ['op cut'],
	'graveren-vector': ['op engrave'],
	'graveren-raster': ['op raster', 'op image'],
	markeren: ['op engrave', 'op dots']
};

/**
 * Hoe zeker is deze preset?
 *
 * Een badge alleen is te makkelijk over te lezen: twee pillen van dezelfde maat
 * die alleen in kleur en woord verschillen, lezen bij het scrollen als
 * hetzelfde ding. Daarom draagt elke bron ook een vorm (het icoon), een regel
 * die zegt wát het betekent, en — als het risico oplevert — een regel die zegt
 * wat je ermee moet. Kleur is dan het derde signaal, niet het enige.
 */
export const SOURCE_LABEL: Record<
	Preset['source'],
	{ text: string; tone: string; icon: 'check' | 'alert' | 'pen' | 'down'; means: string; advice: string }
> = {
	testraster: {
		text: 'Geverifieerd',
		tone: 'ok',
		icon: 'check',
		means: 'Gebrand en beoordeeld op een testraster',
		advice: ''
	},
	handmatig: {
		text: 'Handmatig',
		tone: 'neutral',
		icon: 'pen',
		means: 'Zelf ingevoerd, niet gemeten',
		advice: ''
	},
	geextrapoleerd: {
		text: 'Geëxtrapoleerd',
		tone: 'warn',
		icon: 'alert',
		means: 'Uitgerekend vanaf een andere dikte — nooit gebrand',
		advice: 'Probeer eerst op restmateriaal; begin lager in vermogen.'
	},
	geimporteerd: {
		text: 'Geïmporteerd',
		tone: 'warn',
		icon: 'down',
		means: 'Van iemand anders zijn machine',
		advice: 'Andere laser, ander resultaat — behandel dit als startwaarde.'
	}
};

/**
 * "Gisteren" in plaats van een tijdstempel.
 *
 * De terugkerende gebruiker zoekt op wanneer, niet op wanneer precies. SQLite
 * schrijft UTC zonder zone-achtervoegsel; zonder de Z erbij leest de browser
 * het als lokale tijd en is alles een paar uur mis.
 */
export function toen(stamp: string | null | undefined): string {
	if (!stamp) return '';
	const tijd = new Date(stamp.includes('T') ? stamp : `${stamp.replace(' ', 'T')}Z`);
	if (Number.isNaN(tijd.getTime())) return '';
	const dag = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
	const dagen = Math.round((dag(new Date()) - dag(tijd)) / 86400000);
	if (dagen <= 0) return 'vandaag';
	if (dagen === 1) return 'gisteren';
	if (dagen < 7) return `${dagen} dagen geleden`;
	if (dagen < 14) return 'vorige week';
	return tijd.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Twee instellingen die over hetzelfde gaan maar andere getallen dragen. */
export type PresetConflict = {
	material: string;
	thickness_mm: number | null;
	operation: string;
	machine: string | null;
	mine: { speed_mm_s: number; power_percent: number; passes: number; source: string };
	theirs: { speed_mm_s: number; power_percent: number; passes: number; source: string };
};

export type Telling = {
	materials: number;
	presets: number;
	machines: number;
	test_grids: number;
};

/**
 * Wat er gaat gebeuren als je dit bestand binnenhaalt.
 *
 * Beide keuzes zijn doorgerekend, want het verschil tussen samenvoegen en
 * vervangen moet op het scherm staan op het moment dat je kiest — niet erna.
 */
export type ImportPreview = {
	bundle: string;
	exported_at: string | null;
	bevat: Telling & { photos: number };
	huidig: Telling;
	samenvoegen: {
		materials: {
			new: string[];
			existing: { name: string; as: string; material_id: number }[];
			/** Andere naam, waarschijnlijk dezelfde plank — de valkuil uit M5. */
			similar: { name: string; match: string; material_id: number; why: string }[];
		};
		machines: { new: string[]; existing: string[] };
		presets: { new: number; identical: number; conflicts: PresetConflict[] };
		test_grids: { new: number; existing: number };
	};
	vervangen: { removes: Telling };
};

export type ImportResult = {
	mode: string;
	removed: Telling | null;
	materials: number;
	machines: number;
	test_grids: number;
	presets: { added: number; updated: number; skipped: number };
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
	machines = $state<{ id: number; name: string; power_watt: number | null }[]>([]);
	/** Het profiel van de machine die nu actief is; bepaalt wat je hier ziet. */
	activeMachine = $state<ActiveMachine | null>(null);
	/** Uit: ook presets van andere machines tonen. */
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
	}

	async load() {
		const alles = this.onlyThisMachine ? '' : '?all_machines=true';
		const [materials, presets, machines, active] = await Promise.all([
			this.#request('/api/library/materials'),
			this.#request(`/api/library/presets${alles}`),
			this.#request('/api/library/machines'),
			// 409 als er geen machine actief is; dan blijft het veld leeg en
			// toont de bibliotheek zich zonder machinekop.
			this.#request('/api/library/active-machine')
		]);
		if (materials) this.materials = materials;
		if (presets) this.presets = presets;
		if (machines) this.machines = machines;
		this.activeMachine = active ?? null;
		// Een mislukte 409 mag niet als foutmelding blijven staan.
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

	// ------------------------------------------------ uitwisselen (besluit B7)

	/**
	 * De hele bibliotheek als één bestand ophalen.
	 *
	 * Via een ankertje en niet via fetch: dan doet de browser wat hij goed doet
	 * — een download met een naam, zonder het bestand eerst in het geheugen van
	 * de pagina te trekken.
	 */
	exportBundle() {
		const anker = document.createElement('a');
		anker.href = '/api/library/export.openkerf-lib';
		anker.download = 'bibliotheek.openkerf-lib';
		anker.click();
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
	}

	/** Hetzelfde voorbeeld, herrekend nadat je een materiaal hebt aangewezen. */
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
