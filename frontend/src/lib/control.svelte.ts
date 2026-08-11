/**
 * Schrijfacties richting de API.
 *
 * De API laat schrijven vrij zolang hij op localhost luistert; zodra hij breder
 * bindt (telefoon/tablet) is een token verplicht. We bewaren die token in
 * localStorage zodat de PWA hem niet elke sessie opnieuw vraagt.
 */

import type { Capabilities } from './api';
import { verbinding } from './verbinding.svelte';

const TOKEN_KEY = 'openkerf.token';

export class Controller {
	capabilities = $state<Capabilities | null>(null);
	token = $state('');
	busy = $state<string | null>(null);
	error = $state<string | null>(null);
	/**
	 * De server heeft onze token geweigerd.
	 *
	 * Zonder dit zat je klem: `needsToken` is alleen waar als er géén token is,
	 * dus met een verkeerde token verdween het invoerveld en faalde elke actie
	 * met 401 zonder enige weg terug. Nu komt het veld terug zodra de server
	 * nee zegt.
	 */
	rejected = $state(false);

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

	/** Moet het tokenveld in beeld? Ook als er wél een token is, maar een foute. */
	get tokenProbleem() {
		return this.needsToken || this.rejected;
	}

	saveToken(value: string) {
		this.token = value.trim();
		this.rejected = false;
		this.error = null;
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
			if (response.status === 401) this.rejected = true;
			if (!response.ok) {
				this.error = await describeFailure(response, this.token !== '');
				return false;
			}
			this.rejected = false;
			return true;
		} catch (e) {
			this.error = onbereikbaar(e);
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
			if (response.status === 401) this.rejected = true;
			if (!response.ok) {
				this.error = await describeFailure(response, this.token !== '');
				return false;
			}
			const uitslag = await response.json();
			if (uitslag?.notice) this.error = uitslag.notice;
			return true;
		} catch (e) {
			this.error = onbereikbaar(e);
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

/**
 * Een mislukte fetch is bijna nooit "een netwerkfout".
 *
 * De browser gooit hier `TypeError: Failed to fetch`, en dat op het scherm
 * zetten is protocoltaal: het zegt niet wat er stuk is en niet wat je eraan
 * doet. Dit zijn de twee gevallen die echt voorkomen — de server is weg, of
 * je zit zelf zonder netwerk — en ze vragen om verschillende handelingen.
 */
function onbereikbaar(e: unknown): string {
	if (typeof navigator !== 'undefined' && navigator.onLine === false) {
		return 'Dit apparaat heeft geen netwerk. De machine loopt gewoon door; zodra je weer verbinding hebt, zie je het hier.';
	}
	verbinding.online = false;
	verbinding.sinds ??= Date.now();
	return 'De OpenKerf-server reageert niet — de opdracht is niet aangekomen. Controleer of hij nog draait.';
}

async function describeFailure(response: Response, metToken: boolean): Promise<string> {
	if (response.status === 401) {
		return metToken
			? 'De server weigert deze token. Vul hieronder de token in die in het venster van de engine staat.'
			: 'Deze OpenKerf is vanaf het netwerk bereikbaar en vraagt daarom een token voordat er iets mag bewegen. Vul hem hieronder in.';
	}
	try {
		const body = await response.json();
		const detail = body.detail;
		if (typeof detail === 'string') return detail;
		// De engine antwoordt met zijn eigen console-uitvoer. Die begint met de
		// opdracht die we zelf verstuurden ("plan copy preprocess…") en dat is
		// ruis voor wie alleen wil weten waarom het niet ging; alleen de laatste,
		// betekenisvolle regels overhouden.
		if (detail?.output?.length) return zinnig(detail.output);
		return `De machine weigerde de opdracht (foutcode ${response.status}).`;
	} catch {
		return `De machine weigerde de opdracht (foutcode ${response.status}).`;
	}
}

function zinnig(output: string[]): string {
	const regels = output
		.map((r) => r.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').trim())
		.filter((r) => r && !/^(plan|spool|load|estop|abort|pause|resume)\b/.test(r));
	return (regels.length ? regels : output).join(' · ');
}
