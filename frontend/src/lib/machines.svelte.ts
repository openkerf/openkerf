/**
 * Machinebeheer: catalogus, aanmaken en instellingen.
 *
 * De catalogus komt uit MeerK40t's eigen `dev_info`-registry, dus nieuwe
 * machinetypes uit upstream verschijnen hier zonder codewijziging.
 */

export type CatalogMachine = {
	key: string;
	family: string;
	friendly_name: string;
	extended_info: string | null;
	priority: number;
	provider: string | null;
	defaults: Record<string, unknown>;
};

export type CatalogFamily = { family: string; priority: number; machines: CatalogMachine[] };

export type Machine = {
	path: string;
	label: string;
	provider: string | null;
	active: boolean;
	/** Door een mens ingesteld, of door de engine zelf verzonnen bij het
	 *  opstarten? Ontbreekt bij een oudere server. */
	configured?: boolean;
};

export type SettingField = {
	attr: string;
	label: string;
	tip: string | null;
	type: 'str' | 'int' | 'float' | 'bool' | string;
	value: unknown;
	options: string[] | null;
	section: string | null;
};

export type SettingSheet = { sheet: string; fields: SettingField[] };

/**
 * De soorten machine die een gebruiker herkent.
 *
 * MeerK40t's catalogus is geordend op merk en bord — veertig namen waarvan je
 * er geen kent als je net begint. Wie in zijn werkplaats staat weet wél of hij
 * een glazen buis met waterkoeling heeft of een open diodeframe. Deze indeling
 * is dus geen technische maar een herkenbare.
 */
export type Kind = 'co2-ruida' | 'co2-k40' | 'diode' | 'galvo';

export const KINDS: {
	id: Kind;
	label: string;
	blurb: string;
	icon: string;
}[] = [
	{
		id: 'co2-ruida',
		label: 'CO2 met Ruida of Newly',
		blurb: 'Grote kast, glazen buis, waterkoeling, meestal een Z-as. K50/K60 en groter.',
		// Rechtop en hoog, met een koeler ernaast. Het silhouet moet van de K40
		// te onderscheiden zijn zónder de details te lezen — DESIGN-SYSTEM v3
		// eist onderscheidende silhouetten, en twee lage doosjes zijn dat niet.
		icon: 'M3 4h12v16H3zM3 9h12M6 20v1.5M12 20v1.5M18 8h3v8h-3z'
	},
	{
		id: 'co2-k40',
		label: 'K40 CO2',
		blurb: 'De blauwe doos van 40 W, met een M2- of M3-Nano-bord.',
		// Laag en breed: de blauwe doos met zijn klapdeksel.
		icon: 'M3 11h18v7H3zM4.5 11l2-3h11l2 3M9 14.5h6'
	},
	{
		id: 'diode',
		label: 'Diode op GRBL',
		blurb: 'Open frame zonder koeling. Ortur, Longer, Sculpfun, zelfbouw.',
		icon: 'M3 19h18M5 19V7M19 19V7M4 7h16M11 7v4M9.5 11h3l-1.5 3.5z'
	},
	{
		id: 'galvo',
		label: 'Galvo — fiber of UV',
		blurb: 'Spiegelkop op een statief, markeert metaal. Balor-besturing.',
		icon: 'M12 3v3M9 6h6v3H9zM12 9v2M8 11h8l-4 6zM6 20h12'
	}
];

/**
 * Bij welke soort een familie uit de catalogus hoort.
 *
 * Op naam classificeren is grof, maar de catalogus geeft niets beters mee dan
 * de familienaam en de sleutel. Wat nergens in past komt bij "diode" terecht —
 * dat is waar de meeste GRBL-borden thuishoren.
 */
export function kindOf(family: string, keys: string[]): Kind {
	const naam = family.toLowerCase();
	const sleutels = keys.join(' ').toLowerCase();
	if (/balor|fibre|fiber|uv/.test(naam + sleutels)) return 'galvo';
	if (/k-series|k40/.test(naam) || /nano|k40/.test(sleutels)) return 'co2-k40';
	if (/newly|ruida|moshi|co2/.test(naam) || /ruida|newly|moshi/.test(sleutels)) return 'co2-ruida';
	return 'diode';
}

export class MachineStore {
	catalog = $state<CatalogFamily[]>([]);
	machines = $state<Machine[]>([]);
	settings = $state<SettingSheet[]>([]);
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
			return response.status === 204 ? {} : await response.json();
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
	}

	async loadCatalog() {
		const data = await this.#request('/api/machines/catalog');
		if (data) this.catalog = data;
	}

	async loadMachines() {
		const data = await this.#request('/api/machines');
		if (data) this.machines = data;
	}

	async loadSettings(path: string, essentialOnly = true) {
		const data = await this.#request(
			`/api/machines/${encodeURIComponent(path)}/settings?essential=${essentialOnly}`
		);
		this.settings = data ?? [];
		return this.settings;
	}

	create(info: string, label: string) {
		return this.#request('/api/machines', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ info, label: label || null })
		});
	}

	activate(path: string) {
		return this.#request(`/api/machines/${encodeURIComponent(path)}/activate`, {
			method: 'POST',
			headers: this.#headers()
		});
	}

	remove(path: string) {
		return this.#request(`/api/machines/${encodeURIComponent(path)}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
	}

	updateSettings(path: string, values: Record<string, unknown>) {
		return this.#request(`/api/machines/${encodeURIComponent(path)}/settings`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(values)
		});
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return 'Geen of onjuiste token — wijzigen is geblokkeerd.';
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return body.detail;
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
		return `De engine weigerde de opdracht (${response.status}).`;
	} catch {
		return `De engine weigerde de opdracht (${response.status}).`;
	}
}
