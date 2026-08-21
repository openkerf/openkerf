/**
 * The camera image of the bed.
 *
 * The image itself does not pass through this code: the browser fetches an MJPEG
 * stream in an ordinary `<img>` and decodes it itself. That is why the picture does
 * not stutter — there is no JavaScript loop fetching frames.
 *
 * What *is* here is the state around it: is it running, is it calibrated, and which
 * source the `<img>` should be given.
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
	/** On/off apart from "is the camera running": you can click it away for a bit. */
	shown = $state(false);
	opacity = $state(0.6);
	/** Goes up to make the browser open a fresh stream. */
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
			// A new stream: otherwise the browser hangs on to the old connection the
			// server has just closed.
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

	/** While calibrating you want to see the unprocessed image. */
	async setCorrected(corrected: boolean) {
		const state = await this.#post('/api/camera/corrected', { corrected });
		if (state) this.generation += 1;
		return state;
	}
}
