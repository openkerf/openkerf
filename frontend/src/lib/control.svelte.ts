/**
 * Schrijfacties richting de API.
 *
 * De API laat schrijven vrij zolang hij op localhost luistert; zodra hij breder
 * bindt (telefoon/tablet) is een token verplicht. We bewaren die token in
 * localStorage zodat de PWA hem niet elke sessie opnieuw vraagt.
 */

import { apiError, t } from './i18n/core.ts';
import type { Capabilities } from './api';
import { connection } from './connection.svelte';

const TOKEN_KEY = 'openkerf.token';

/** Een plek op het bed die deze machine onthoudt (gat J6). */
export type Position = { name: string; x_mm: number; y_mm: number };

/**
 * Het nulpunt van de gebruiker (gat J12), als losse module-toestand.
 *
 * Twee schermen hebben hem nodig: het Job-paneel, dat hem set, en het canvas,
 * dat laat zien waar het werk terechtkomt. Die twee zitten niet in elkaar en de
 * pagina ertussen is niet van deze ronde, dus in plaats van een prop door drie
 * lagen te rijgen staat hij hier — één waarde, twee lezers.
 */
class Nulpunt {
	punt = $state<{ x_mm: number; y_mm: number } | null>(null);
	#geladen = false;

	/** Eén keer per pagina ophalen; wie het opnieuw wil, geeft `opnieuw` mee. */
	async laad(opnieuw = false) {
		if (this.#geladen && !opnieuw) return;
		this.#geladen = true;
		try {
			const response = await fetch('/api/machine/origin');
			if (!response.ok) return;
			this.punt = (await response.json()).origin ?? null;
		} catch {
			// Zwijgen: zonder server valt er sowieso niets te sturen, en de
			// verbindingskaart zegt dat al.
		}
	}
}

export const nulpunt = new Nulpunt();

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
	/**
	 * De connection met de machine opzetten of verbreken.
	 *
	 * Niet elke driver kent het: Ruida heeft `ruida_connect`, de USB-families
	 * `usb_connect`, en grbl opent zelf zodra er werk naartoe gaat. Wat de
	 * capabilities op false zetten, hoort geen knop te zijn.
	 */
	connect() {
		return this.#post('/api/machine/connect', 'connect');
	}
	disconnect() {
		return this.#post('/api/machine/disconnect', 'disconnect');
	}
	clearQueue() {
		return this.#post('/api/spooler/clear', 'clear');
	}

	// ------------------------------------------------- bewegen naar een punt

	async #json(path: string, action: string, method = 'POST', body?: unknown) {
		this.busy = action;
		this.error = null;
		try {
			const response = await fetch(path, {
				method,
				headers: { 'Content-Type': 'application/json', ...this.#headers() },
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (response.status === 401) this.rejected = true;
			if (!response.ok) {
				this.error = await describeFailure(response, this.token !== '');
				return null;
			}
			this.rejected = false;
			return await response.json();
		} catch (e) {
			this.error = onbereikbaar(e);
			return null;
		} finally {
			this.busy = null;
		}
	}

	/**
	 * De kop naar een absolute plek op het bed sturen (gat J6).
	 *
	 * Draagt zowel "naar de oorsprong" als de bewaarde posities. De jogknoppen
	 * gaan via de pagina omdat die het canvas moet bijwerken; dit is een sprong
	 * naar een punt en heeft dat niet nodig.
	 */
	moveTo(xMm: number, yMm: number) {
		return this.#json('/api/machine/move', 'move', 'POST', { x_mm: xMm, y_mm: yMm });
	}

	/**
	 * Posities die deze machine onthoudt.
	 *
	 * Ze staan op de device-service in de engine, niet in de browser: een
	 * positie hoort bij de machine met de mal erop, niet bij de laptop waar je
	 * toevallig achter zit.
	 */
	async listPositions(): Promise<Position[]> {
		try {
			const response = await fetch('/api/machine/positions');
			if (!response.ok) return [];
			return (await response.json()).positions ?? [];
		} catch {
			return [];
		}
	}

	/** Zonder coördinaten: waar de kop nu staat. */
	savePosition(name: string) {
		return this.#json('/api/machine/positions', 'save-position', 'POST', { name });
	}

	deletePosition(name: string) {
		return this.#json(
			`/api/machine/positions?name=${encodeURIComponent(name)}`,
			'delete-position',
			'DELETE'
		);
	}

	// ------------------------------------------------- het nulpunt (gat J12)
	//
	// LightBurn's Set Origin: je legt een nulpunt op je werkstuk en het werk
	// brandt daarvandaan. Dat is de handeling bij het uitlijnen op een restplank
	// — de plank ligt waar hij ligt, en je wil je tekening niet verslepen om hem
	// erop te krijgen.
	//
	// Het nulpunt leeft op de machine (zoals de bewaarde posities), niet in de
	// browser: het hoort bij déze laser met dít stuk hout erin.

	get origin() {
		return nulpunt.punt;
	}

	loadOrigin() {
		return nulpunt.laad(true);
	}

	/** Zonder coördinaten: waar de kop nu staat. */
	async setOrigin(xMm?: number, yMm?: number) {
		const body = xMm === undefined || yMm === undefined ? {} : { x_mm: xMm, y_mm: yMm };
		const uitslag = await this.#json('/api/machine/origin', 'set-origin', 'POST', body);
		if (uitslag) nulpunt.punt = { x_mm: uitslag.x_mm, y_mm: uitslag.y_mm };
		return uitslag;
	}

	async clearOrigin() {
		const uitslag = await this.#json('/api/machine/origin', 'clear-origin', 'DELETE');
		if (uitslag) nulpunt.punt = null;
		return uitslag;
	}

	// --------------------------- bijstellen tijdens een lopende job (gat J11)
	//
	// Alleen als de driver een realtime kanaal heeft. Op een Ruida staat
	// `capabilities.adjust` op false en bestaan deze knoppen niet — zie
	// machine.py voor waarom dat geen tekortkoming van ons is.

	adjust = $state<{ power: number | null; speed: number | null }>({
		power: null,
		speed: null
	});

	get canAdjust() {
		const kan = this.capabilities?.adjust;
		return Boolean(kan?.power || kan?.speed);
	}

	async loadAdjustment() {
		try {
			const response = await fetch('/api/job/adjust');
			if (!response.ok) return;
			const data = await response.json();
			this.adjust = { power: data.power ?? null, speed: data.speed ?? null };
		} catch {
			// Zie loadOrigin.
		}
	}

	/** `factor` is een vermenigvuldiging op wat de laag zegt; 1 is "zoals ontworpen". */
	async setAdjustment(wat: 'power' | 'speed', factor: number) {
		const geknipt = Math.min(2, Math.max(0.1, Math.round(factor * 100) / 100));
		const uitslag = await this.#json('/api/job/adjust', `adjust-${wat}`, 'POST', {
			[wat]: geknipt
		});
		if (uitslag) this.adjust = { power: uitslag.power ?? null, speed: uitslag.speed ?? null };
		return uitslag;
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
 * The browser throws `TypeError: Failed to fetch` here, and putting that on the
 * screen is protocol language: it says neither what is broken nor what you do
 * about it. These are the two cases that really occur — the server is gone, or you
 * are without a network yourself — and they ask for different actions.
 */
function onbereikbaar(e: unknown): string {
	if (typeof navigator !== 'undefined' && navigator.onLine === false) {
		return t('error.noNetwork');
	}
	connection.online = false;
	connection.since ??= Date.now();
	return t('error.serverGone');
}

async function describeFailure(response: Response, metToken: boolean): Promise<string> {
	if (response.status === 401) {
		return metToken
			? t('error.tokenRefused')
			: t('error.tokenNeeded');
	}
	try {
		const body = await response.json();
		const detail = body.detail;
		if (typeof detail === 'string') return apiError(response, detail);
		// The engine answers with its own console output. That starts with the command
		// we sent ourselves ("plan copy preprocess…") and that is noise for anyone who
		// only wants to know why it did not work; keep only the last meaningful lines.
		if (detail?.output?.length) return zinnig(detail.output);
		return t('error.machineRefused', { status: response.status });
	} catch {
		return t('error.machineRefused', { status: response.status });
	}
}

function zinnig(output: string[]): string {
	const regels = output
		.map((r) => r.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').trim())
		.filter((r) => r && !/^(plan|spool|load|estop|abort|pause|resume)\b/.test(r));
	return (regels.length ? regels : output).join(' · ');
}
