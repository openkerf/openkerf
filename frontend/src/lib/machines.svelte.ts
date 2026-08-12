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
 * Bij welke soort één machine uit de catalogus hoort.
 *
 * Classificeren gebeurt per **machine**, niet per familie. Dat is geen detail:
 * MeerK40t's familie "K-Series CO2-Laser" bevat naast twee Nano-borden en twee
 * GRBL-borden óók `ruida-beta` — de enige Ruida in de hele catalogus. Wie op
 * familienaam sorteerde, schoof die ene Ruida mee naar "K40 CO2" en liet de
 * soort "CO2 met Ruida of Newly" achter met eenendertig Newly's en nul Ruida's.
 *
 * De `provider` is de betrouwbaarste bron die de catalogus meegeeft: hij zegt
 * welke driver de machine aanstuurt, en dat is precies wat de soort betekent.
 * Familienaam en sleutel zijn alleen nog terugval voor providers die we niet
 * kennen — nieuwe upstream-drivers vallen dan niet meteen uit de lijst.
 */
export function kindOfMachine(machine: {
	family?: string;
	key?: string;
	provider?: string | null;
}): Kind {
	const driver = (machine.provider ?? '').toLowerCase().split('/').pop() ?? '';
	if (driver === 'balor') return 'galvo';
	if (driver === 'ruida' || driver === 'newly' || driver === 'moshi') return 'co2-ruida';
	if (driver === 'lhystudios') return 'co2-k40';
	if (driver === 'grbl') {
		// Een GRBL-bord in een K40-kast is nog steeds een K40 voor wie ernaar
		// kijkt; alle andere GRBL's zijn open diodeframes.
		const context = `${machine.family ?? ''} ${machine.key ?? ''}`.toLowerCase();
		return /k-series|k40/.test(context) ? 'co2-k40' : 'diode';
	}

	const naam = (machine.family ?? '').toLowerCase();
	const sleutel = (machine.key ?? '').toLowerCase();
	if (/balor|fibre|fiber|uv/.test(naam + sleutel)) return 'galvo';
	if (/ruida|newly|moshi/.test(naam + sleutel)) return 'co2-ruida';
	if (/k-series|k40|nano/.test(naam + sleutel)) return 'co2-k40';
	if (/co2/.test(naam)) return 'co2-ruida';
	return 'diode';
}

/**
 * Wat een zoekopdracht oplevert (besluit B6).
 *
 * Een vondst is een *voorstel*, geen machine: hij bestaat alleen in dit
 * antwoord tot de gebruiker hem bevestigt. De API-kant is daarom een GET zonder
 * schrijfrechten — zie `machines.py`, sectie "detection".
 */
export type Vondst = {
	id: string;
	transport: 'usb' | 'serieel' | 'netwerk' | string;
	/** Wat er gevonden is, in mensentaal: "K40-bord (CH341)". */
	title: string;
	/** Waar het zit: een poortnaam, een IP-adres, een USB-identiteit. */
	where: string;
	detail: string | null;
	kind: Kind | string;
	confidence: 'zeker' | 'waarschijnlijk' | 'onzeker' | string;
	/** Waarom we dit denken. Altijd tonen: een gok zonder reden is een gok. */
	why: string;
	suggestions: { key: string; label: string; family: string }[];
	/** Verbindingsinstellingen die uit de vondst volgen (poort, adres). */
	settings: Record<string, string>;
};

export type ScanResult = {
	candidates: Vondst[];
	/** Waar gekeken is — nodig om "niets gevonden" te kunnen vertrouwen. */
	searched: string[];
	/** Waarom ergens níet gekeken kon worden, of wat er stil bleef. */
	notes: string[];
	duration_ms: number;
};

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

	/**
	 * Zoek naar machines op USB, seriële poorten en het lokale netwerk.
	 *
	 * `signal` hoort erbij: dit duurt seconden, en een gebruiker die niet kan
	 * stoppen wacht niet maar ververst de pagina.
	 */
	async scan(options: { network?: boolean; seconds?: number; signal?: AbortSignal } = {}) {
		const { network = true, seconds = 2, signal } = options;
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(`/api/machines/scan?network=${network}&seconds=${seconds}`, {
				signal
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return (await response.json()) as ScanResult;
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return null;
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
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
