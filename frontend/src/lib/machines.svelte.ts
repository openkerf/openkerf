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
