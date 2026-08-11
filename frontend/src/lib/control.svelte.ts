/**
 * Schrijfacties richting de API.
 *
 * De API laat schrijven vrij zolang hij op localhost luistert; zodra hij breder
 * bindt (telefoon/tablet) is een token verplicht. We bewaren die token in
 * localStorage zodat de PWA hem niet elke sessie opnieuw vraagt.
 */

import type { Capabilities } from './api';

const TOKEN_KEY = 'openkerf.token';

export class Controller {
	capabilities = $state<Capabilities | null>(null);
	token = $state('');
	busy = $state<string | null>(null);
	error = $state<string | null>(null);

	constructor() {
		if (typeof localStorage !== 'undefined') {
			this.token = localStorage.getItem(TOKEN_KEY) ?? '';
		}
	}

	get authRequired() {
		return this.capabilities?.auth_required ?? false;
	}

	get needsToken() {
		return this.authRequired && !this.token;
	}

	saveToken(value: string) {
		this.token = value.trim();
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem(TOKEN_KEY, this.token);
		}
	}

	async refreshCapabilities() {
		try {
			const response = await fetch('/api/capabilities');
			if (response.ok) this.capabilities = await response.json();
		} catch {
			this.capabilities = null;
		}
	}

	#headers(): Record<string, string> {
		return this.token ? { Authorization: `Bearer ${this.token}` } : {};
	}

	async #post(path: string, action: string, body?: FormData) {
		this.busy = action;
		this.error = null;
		try {
			const response = await fetch(path, {
				method: 'POST',
				headers: this.#headers(),
				body
			});
			if (!response.ok) {
				this.error = await describeFailure(response);
				return false;
			}
			return true;
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return false;
		} finally {
			this.busy = null;
		}
	}

	/**
	 * De kop langs de omtrek van het werk sturen. Geen laser, alleen beweging.
	 *
	 * De machine kan melden dat hij nog bezig is; dat komt hier in `error`
	 * terecht, want anders denk je het kader gezien te hebben terwijl er een
	 * hoek ontbrak.
	 */
	async frame() {
		this.busy = 'frame';
		this.error = null;
		try {
			const response = await fetch('/api/machine/frame', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...this.#headers() },
				body: '{}'
			});
			if (!response.ok) {
				this.error = await describeFailure(response);
				return false;
			}
			const uitslag = await response.json();
			if (uitslag?.notice) this.error = uitslag.notice;
			return true;
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return false;
		} finally {
			this.busy = null;
		}
	}

	/** Wordt bij een geslaagde start aangeroepen — het wauw-moment hangt hieraan. */
	onStarted: (() => void) | null = null;

	async start() {
		const ok = await this.#post('/api/job/start', 'start');
		// Aan de druk op de knop, niet aan de polling: een korte job is voorbij
		// voordat de status hem ooit als "running" laat zien.
		if (ok !== false) this.onStarted?.();
		return ok;
	}
	pause() {
		return this.#post('/api/job/pause', 'pause');
	}
	resume() {
		return this.#post('/api/job/resume', 'resume');
	}
	stop() {
		return this.#post('/api/job/stop', 'stop');
	}
	clearQueue() {
		return this.#post('/api/spooler/clear', 'clear');
	}

	load(file: File) {
		const form = new FormData();
		form.append('file', file);
		return this.#post('/api/job/load', 'load', form);
	}
}

async function describeFailure(response: Response): Promise<string> {
	if (response.status === 401) {
		return 'Geen of onjuiste token — schrijfacties zijn geblokkeerd.';
	}
	try {
		const body = await response.json();
		const detail = body.detail;
		if (typeof detail === 'string') return detail;
		if (detail?.output?.length) return detail.output.join(' · ');
		return `De engine weigerde de opdracht (${response.status}).`;
	} catch {
		return `De engine weigerde de opdracht (${response.status}).`;
	}
}
