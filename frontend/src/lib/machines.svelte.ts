/**
 * Machine management: catalogue, creation and settings.
 *
 * The catalogue comes from MeerK40t's own `dev_info` registry, so new machine
 * types from upstream appear here without a code change.
 */

import { apiError, t } from './i18n/core.ts';

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
	/** Set up by a human, or invented by the engine itself at startup? Absent on
	 *  an older server. */
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
 * The kinds of machine a user recognises.
 *
 * MeerK40t's catalogue is ordered by brand and board — forty names, none of
 * which you know when you are starting out. Somebody standing in their workshop
 * does know whether they have a glass tube with water cooling or an open diode
 * frame. So this division is not a technical one but a recognisable one.
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
		label: t('kind.co2Ruida'),
		blurb: t('kind.co2Ruida.blurb'),
		// Upright and tall, with a chiller beside it. The silhouette has to be
		// distinguishable from the K40 *without* reading the details — DESIGN-SYSTEM v3
		// demands distinct silhouettes, and two low boxes are not that.
		icon: 'M3 4h12v16H3zM3 9h12M6 20v1.5M12 20v1.5M18 8h3v8h-3z'
	},
	{
		id: 'co2-k40',
		label: t('kind.k40'),
		blurb: t('kind.k40.blurb'),
		// Low and wide: the blue box with its hinged lid.
		icon: 'M3 11h18v7H3zM4.5 11l2-3h11l2 3M9 14.5h6'
	},
	{
		id: 'diode',
		label: t('kind.diode'),
		blurb: t('kind.diode.blurb'),
		icon: 'M3 19h18M5 19V7M19 19V7M4 7h16M11 7v4M9.5 11h3l-1.5 3.5z'
	},
	{
		id: 'galvo',
		label: t('kind.galvo'),
		blurb: t('kind.galvo.blurb'),
		icon: 'M12 3v3M9 6h6v3H9zM12 9v2M8 11h8l-4 6zM6 20h12'
	}
];

/**
 * Which kind one machine from the catalogue belongs to.
 *
 * Classifying happens per **machine**, not per family. That is not a detail:
 * besides two Nano boards and two GRBL boards, MeerK40t's family "K-Series
 * CO2-Laser" also contains `ruida-beta` — the only Ruida in the whole catalogue.
 * Sorting on family name shoved that one Ruida along into "K40 CO2" and left the
 * kind "CO2 with Ruida or Newly" with thirty-one Newlys and no Ruidas at all.
 *
 * The `provider` is the most reliable source the catalogue supplies: it says
 * which driver drives the machine, and that is exactly what the kind means.
 * Family name and key are only a fallback for providers we do not know — that way
 * new upstream drivers do not drop straight out of the list.
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
		// A GRBL board in a K40 case is still a K40 to whoever is looking at it;
		// every other GRBL is an open diode frame.
		const context = `${machine.family ?? ''} ${machine.key ?? ''}`.toLowerCase();
		return /k-series|k40/.test(context) ? 'co2-k40' : 'diode';
	}

	const name = (machine.family ?? '').toLowerCase();
	const key = (machine.key ?? '').toLowerCase();
	if (/balor|fibre|fiber|uv/.test(name + key)) return 'galvo';
	if (/ruida|newly|moshi/.test(name + key)) return 'co2-ruida';
	if (/k-series|k40|nano/.test(name + key)) return 'co2-k40';
	if (/co2/.test(name)) return 'co2-ruida';
	return 'diode';
}

/**
 * What a search turns up (decision B6).
 *
 * A finding is a *proposal*, not a machine: it exists only in this answer until
 * the user confirms it. The API side is therefore a GET without write rights —
 * see `machines.py`, section "detection".
 */
export type Finding = {
	id: string;
	transport: 'usb' | 'serieel' | 'netwerk' | string;
	/** What was found, in plain words: "K40 board (CH341)". */
	title: string;
	/** Where it sits: a port name, an IP address, a USB identity. */
	where: string;
	detail: string | null;
	kind: Kind | string;
	confidence: 'zeker' | 'waarschijnlijk' | 'onzeker' | string;
	/** Why we think this. Always shown: a guess without a reason is a guess. */
	why: string;
	suggestions: { key: string; label: string; family: string }[];
	/** Connection settings that follow from the finding (port, address). */
	settings: Record<string, string>;
};

export type ScanResult = {
	candidates: Finding[];
	/** Where we looked — needed before "nothing found" can be trusted. */
	searched: string[];
	/** Why somewhere could *not* be looked at, or what stayed silent. */
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
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
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
	 * Search for machines on USB, serial ports and the local network.
	 *
	 * `signal` belongs with it: this takes seconds, and a user who cannot stop it
	 * does not wait but reloads the page.
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
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
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
	if (response.status === 401) return t('error.noToken');
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return apiError(response, body.detail);
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
		return t('error.engineRefused', { status: response.status });
	} catch {
		return t('error.engineRefused', { status: response.status });
	}
}
