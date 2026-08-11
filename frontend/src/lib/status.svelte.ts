/**
 * Live verbinding met de OpenKerf API.
 *
 * De WebSocket stuurt een snapshot bij connect, daarna kernel-signalen en elke
 * 2 s opnieuw een volledige snapshot. Read-only: we sturen niets terug.
 */

import { currentJob } from './api';
import type { ApiEvent, Device, SignalEvent, Snapshot } from './api';

const RECONNECT_MIN = 500;
const RECONNECT_MAX = 10_000;
const MAX_EVENTS = 25;

export class StatusConnection {
	snapshot = $state<Snapshot | null>(null);
	events = $state<SignalEvent[]>([]);
	connected = $state(false);
	lastUpdate = $state<number | null>(null);

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
		this.#open();
	}

	close() {
		this.#stopped = true;
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
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
			if (payload.type === 'snapshot') {
				this.snapshot = payload.data;
			} else {
				this.events = [payload, ...this.events].slice(0, MAX_EVENTS);
			}
		};

		socket.onclose = () => {
			this.connected = false;
			this.#socket = null;
			this.#scheduleReconnect();
		};

		socket.onerror = () => socket.close();
	}

	#scheduleReconnect() {
		if (this.#stopped || this.#retryTimer) return;
		this.#retryTimer = setTimeout(() => {
			this.#retryTimer = null;
			this.#open();
		}, this.#retryDelay);
		this.#retryDelay = Math.min(this.#retryDelay * 2, RECONNECT_MAX);
	}
}
