/**
 * Het camerabeeld van het bed.
 *
 * Het beeld zelf komt niet door deze code heen: de browser haalt een MJPEG-
 * stroom op in een gewone `<img>` en decodeert die zelf. Dat is de reden dat
 * het beeld niet hapert — er is geen JavaScript-lus die plaatjes ophaalt.
 *
 * Wat hier wél staat is de toestand eromheen: draait hij, is hij geijkt, en
 * welke bron de `<img>` moet krijgen.
 */

import { apiError, t } from './i18n/core.ts';

export type CameraState = {
	available: boolean;
	running: boolean;
	reason?: string;
	uri?: string | null;
	calibrated?: boolean;
	corrected?: boolean;
	perspective?: number[][];
	frame?: { width: number; height: number } | null;
};

export class CameraStore {
	state = $state<CameraState>({ available: false, running: false });
	busy = $state(false);
	error = $state<string | null>(null);
	/** Aan/uit los van "draait de camera": je kunt hem even wegklikken. */
	shown = $state(false);
	opacity = $state(0.6);
	/** Loopt op om de browser een verse stroom te laten openen. */
	generation = $state(0);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	get src(): string | null {
		if (!this.shown || !this.state.running) return null;
		return `/api/camera/stream.mjpeg?v=${this.generation}`;
	}

	async load() {
		try {
			const response = await fetch('/api/camera');
			if (response.ok) this.state = await response.json();
		} catch {
			this.state = { available: false, running: false };
		}
	}

	async #post(path: string, body?: unknown, method = 'POST') {
		this.busy = true;
		this.error = null;
		try {
			const token = this.#token();
			const response = await fetch(path, {
				method,
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error =
					apiError(response, (await response.json().catch(() => null))?.detail);
				return null;
			}
			const state = await response.json();
			this.state = state;
			return state;
		} catch (e) {
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			this.busy = false;
		}
	}

	async start(uri?: string) {
		const state = await this.#post('/api/camera/start', uri ? { uri } : {});
		if (state) {
			this.shown = true;
			// Nieuwe stroom: anders blijft de browser aan de oude connection
			// hangen die de server net heeft afgesloten.
			this.generation += 1;
		}
		return state;
	}

	stop() {
		this.shown = false;
		return this.#post('/api/camera/stop');
	}

	calibrate(points: number[][]) {
		return this.#post('/api/camera/calibrate', { points });
	}

	resetCalibration() {
		return this.#post('/api/camera/calibrate', undefined, 'DELETE');
	}

	/** Tijdens het ijken wil je juist het onbewerkte beeld zien. */
	async setCorrected(corrected: boolean) {
		const state = await this.#post('/api/camera/corrected', { corrected });
		if (state) this.generation += 1;
		return state;
	}
}
