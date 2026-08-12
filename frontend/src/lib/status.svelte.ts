/**
 * Live verbinding met de OpenKerf API.
 *
 * De WebSocket stuurt een snapshot bij connect, daarna kernel-signalen en elke
 * 2 s opnieuw een volledige snapshot. Read-only: we sturen niets terug.
 */

import { currentJob } from './api';
import type { ApiEvent, Device, SignalEvent, Snapshot } from './api';
import { verbinding } from './verbinding.svelte';

const RECONNECT_MIN = 500;
const RECONNECT_MAX = 10_000;
const MAX_EVENTS = 25;

export class StatusConnection {
	snapshot = $state<Snapshot | null>(null);
	events = $state<SignalEvent[]>([]);
	connected = $state(false);
	lastUpdate = $state<number | null>(null);
	/** Welk serverproces we aan de lijn hebben; verandert alleen bij een herstart. */
	instance = $state<string | null>(null);

	#socket: WebSocket | null = null;
	#retryDelay = RECONNECT_MIN;
	#retryTimer: ReturnType<typeof setTimeout> | null = null;
	#stopped = false;

	get device(): Device | null {
		const devices = this.snapshot?.devices ?? [];
		return devices.find((d) => d.active) ?? devices[0] ?? null;
	}

	/**
	 * De job waar de bediening over gaat — lopend óf stilstaand.
	 *
	 * Dit filterde op `running`, en dat vlaggetje gaat bij Lihuiyu op `false`
	 * zodra je pauzeert. Gevolg: de job verdween uit de statusbalk, uit het
	 * Job-paneel en van de telefoon, er was geen knop om te hervatten, en
	 * "Job starten" werd weer actief bovenop werk dat alleen maar stilstond.
	 */
	get activeJob() {
		return currentJob(this.device);
	}

	connect() {
		this.#stopped = false;
		verbinding.nuProberen = () => this.#nu();
		this.#open();
	}

	/**
	 * Meteen opnieuw proberen in plaats van de backoff uitzitten.
	 *
	 * Na een halve minuut wachten we tien seconden tussen pogingen. Wie net de
	 * server heeft herstart wil niet tien seconden naar een dood scherm kijken,
	 * en heeft bovendien informatie die wij niet hebben: hij weet dát hij hem
	 * herstart heeft.
	 */
	#nu() {
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#retryDelay = RECONNECT_MIN;
		this.#tellen(0);
		this.#open();
	}

	close() {
		this.#stopped = true;
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#tellen(0);
		this.#socket?.close();
		this.#socket = null;
		this.connected = false;
	}

	#open() {
		if (this.#stopped) return;
		const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
		const socket = new WebSocket(`${protocol}//${location.host}/api/ws`);
		this.#socket = socket;

		socket.onopen = () => {
			this.connected = true;
			verbinding.online = true;
			verbinding.sinds = null;
			this.#tellen(0);
			this.#retryDelay = RECONNECT_MIN;
		};

		socket.onmessage = (message) => {
			let payload: ApiEvent;
			try {
				payload = JSON.parse(message.data);
			} catch {
				return;
			}
			this.lastUpdate = Date.now();
			if (payload.type === 'hello') {
				this.#hallo(payload.instance);
			} else if (payload.type === 'snapshot') {
				this.snapshot = payload.data;
			} else {
				this.events = [payload, ...this.events].slice(0, MAX_EVENTS);
			}
		};

		socket.onclose = () => {
			this.connected = false;
			verbinding.online = false;
			verbinding.sinds ??= Date.now();
			this.#socket = null;
			this.#scheduleReconnect();
		};

		socket.onerror = () => socket.close();
	}

	/**
	 * De server stelt zich voor (gat E2).
	 *
	 * Hier zat een stille fout: de WebSocket verbond na een herstart keurig
	 * terug, de statusbalk werd weer groen, en de pagina toonde daarna
	 * onverstoorbaar het ontwerp van vóór de herstart — dat aan de andere kant
	 * niet meer bestaat. Je tekent verder in een document dat weg is.
	 *
	 * Zelfde `instance` = hetzelfde proces, dus een netwerkhik: de snapshot die
	 * er meteen achteraan komt herstelt alles wat live is, en er valt niets op
	 * te halen. Een ander `instance` betekent een nieuwe engine met een lege
	 * boom, en dan is er niets meer te redden aan de pagina zoals hij is. We
	 * herladen niet uit onszelf — dat gooit ongesaveld werk weg zonder dat
	 * iemand erom vroeg — maar zetten de vlag waar de app op reageert.
	 */
	#hallo(instance: string) {
		if (!instance) return;
		if (this.instance === null) {
			this.instance = instance;
			return;
		}
		if (this.instance !== instance) {
			this.instance = instance;
			verbinding.herstart = true;
		}
	}

	#scheduleReconnect() {
		if (this.#stopped || this.#retryTimer) return;
		this.#tellen(this.#retryDelay);
		this.#retryTimer = setTimeout(() => {
			this.#retryTimer = null;
			this.#open();
		}, this.#retryDelay);
		this.#retryDelay = Math.min(this.#retryDelay * 2, RECONNECT_MAX);
	}

	/**
	 * De aftelklok naar de volgende poging.
	 *
	 * Een app die stilstaat zonder te zeggen dat hij iets doet, ziet eruit als
	 * een app die vastgelopen is. Eén zichtbaar getal is het verschil tussen
	 * "hij is bezig" en "hij is dood".
	 */
	#tellen(ms: number) {
		if (this.#tikker) clearInterval(this.#tikker);
		this.#tikker = null;
		verbinding.overSeconden = Math.ceil(ms / 1000);
		if (ms <= 0) return;
		this.#tikker = setInterval(() => {
			verbinding.overSeconden = Math.max(0, verbinding.overSeconden - 1);
			if (verbinding.overSeconden === 0 && this.#tikker) {
				clearInterval(this.#tikker);
				this.#tikker = null;
			}
		}, 1000);
	}

	#tikker: ReturnType<typeof setInterval> | null = null;
}
