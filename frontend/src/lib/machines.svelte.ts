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
 * What kind of light the machine makes.
 *
 * A different question from `Kind` above, and both are needed. `Kind` is the
 * silhouette you recognise in your own workshop — a tall glass-tube cabinet, a blue
 * K40, an open diode frame — and it exists to get you through step 1 of the wizard.
 * This is the physics, and it is the axis along which a setting may travel: a CO2
 * setting on a diode is not a starting point, whatever the two cabinets look like.
 * The values are `catalogue_schema.LASER_KINDS` in the engine layer, so a preset
 * from the shared catalogue and a machine profile of ours speak of the same thing.
 */
export type LaserKind = 'co2-glass' | 'co2-rf' | 'diode' | 'fiber' | 'uv' | 'unknown';

/** The kinds a reader may choose from, in the order the wizard offers them. */
export const LASER_KINDS: LaserKind[] = ['co2-glass', 'co2-rf', 'diode', 'fiber', 'uv'];

/**
 * The kind in words.
 *
 * A function and not a table of labels built at import time: a module-level `t()`
 * resolves once, so a language switch would leave these six words in whichever
 * language happened to load first.
 */
export function laserKindLabel(kind: LaserKind | string): string {
	switch (kind) {
		case 'co2-glass':
			return t('laser.kind.co2Glass');
		case 'co2-rf':
			return t('laser.kind.co2Rf');
		case 'diode':
			return t('laser.kind.diode');
		case 'fiber':
			return t('laser.kind.fiber');
		case 'uv':
			return t('laser.kind.uv');
		default:
			return t('laser.kind.unknown');
	}
}

/**
 * `defaults.source` in a catalogue entry, to the kind of laser it means.
 *
 * A copy of `KIND_BY_SOURCE` in `api/openkerf_api/matching.py`, and a deliberate
 * one: the engine layer derives the kind from the same registry but exposes no route
 * that says so, so the wizard — which has to *prefill* the field before anything is
 * written — has no other way to ask. `frontend/tests/starter.test.ts` reads the
 * Python and fails when the two tables drift apart, which is the only thing that
 * makes a second copy safe.
 *
 * `Older CO2` is upstream's own label for the thirty g3v8 brands, a string with a
 * space in it rather than a slug, and is copied verbatim for the same reason it is
 * there: normalising it is how a rename upstream becomes a silent `unknown`.
 */
export const KIND_BY_SOURCE: Record<string, LaserKind> = {
	co2: 'co2-glass',
	'Older CO2': 'co2-glass',
	diode: 'diode',
	fiber: 'fiber',
	uv: 'uv'
};

/**
 * When the source says nothing usable, the family name does. Ordered, matched as a
 * substring, both spellings of fibre — same list as `KIND_BY_FAMILY` in `matching.py`.
 */
export const KIND_BY_FAMILY: [string, LaserKind][] = [
	['CO2', 'co2-glass'],
	['Diode', 'diode'],
	['Fibre', 'fiber'],
	['Fiber', 'fiber'],
	['UV', 'uv']
];

/**
 * Which kind of laser one catalogue entry describes.
 *
 * `unknown` is a real answer and not a failure: exactly one entry in the live
 * registry (`grbl-fluidnc`, family `Generic`, source `generic`) lands there, and a
 * FluidNC board really does drive whatever is bolted to it. A glass tube and an RF
 * metal tube cannot be told apart from this data at all, so this writes `co2-glass`
 * and the wizard shows it prefilled and changeable.
 */
export function laserKindFor(
	entry: { family?: string | null; defaults?: Record<string, unknown> | null } | null | undefined
): LaserKind {
	if (!entry) return 'unknown';
	const source = entry.defaults?.source;
	if (typeof source === 'string' && source in KIND_BY_SOURCE) return KIND_BY_SOURCE[source];
	const family = String(entry.family ?? '');
	for (const [needle, kind] of KIND_BY_FAMILY) if (family.includes(needle)) return kind;
	return 'unknown';
}

/**
 * Which kind of laser a machine that already exists is.
 *
 * The catalogue key it was made from is the precise answer, so it is asked first.
 * Without one — a machine from before we started stamping the key on the device —
 * the driver is what is left, and that is only an answer when every entry running
 * that driver agrees: `balor` drives a fibre, a CO2 and a UV galvo, so it says
 * nothing and the field is left for the reader to fill in. The same order of
 * preference as `MachineManager._info_key` uses for the key itself.
 */
export function laserKindOfMachine(
	catalog: CatalogFamily[],
	where: { info?: string | null; provider?: string | null }
): LaserKind {
	const entries = catalog.flatMap((family) => family.machines);
	if (where.info) {
		const found = entries.find((entry) => entry.key === where.info);
		if (found) return laserKindFor(found);
	}
	if (!where.provider) return 'unknown';
	const agreed = new Set(
		entries.filter((entry) => entry.provider === where.provider).map(laserKindFor)
	);
	return agreed.size === 1 ? [...agreed][0] : 'unknown';
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

	/**
	 * Which catalogue line a machine that exists was made from.
	 *
	 * Read through the export route, because that is the only route that answers this
	 * question: `machines.py` stamps the key on the device when it creates it and
	 * `export_profile` is the one place that hands it back. A GET, so nothing is
	 * written, and no `.openkerf-machine` file is ever saved — `fetch` ignores the
	 * attachment header.
	 *
	 * Deliberately outside `#request`: a machine from before we stamped the key, and
	 * whose driver runs no catalogue entry at all, is refused here with 409, and that
	 * is not a fault worth a red line across the wizard. The caller gets null and asks
	 * the reader instead.
	 */
	async infoKey(path: string): Promise<string | null> {
		try {
			const response = await fetch(
				`/api/machines/${encodeURIComponent(path)}/export.openkerf-machine`
			);
			if (!response.ok) return null;
			const profile = await response.json();
			const info = profile?.machine?.info;
			return typeof info === 'string' && info ? info : null;
		} catch {
			return null;
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
