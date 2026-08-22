/**
 * The rotary, as loose module state.
 *
 * Machine-wide, like the zero point in `control.svelte.ts`, and for the same reason it
 * lives here rather than in a component: three screens need it and none of them is inside
 * another. The machine settings page sets it, the Job panel asks it whether homing is safe,
 * and the pre-flight says out loud what it is going to do.
 *
 * The API is the authority; this object never computes the scale that goes into a job. Its
 * `state` is exactly what `/api/machine/rotary` answered.
 */

import { apiError, t } from './i18n/core.ts';
import { ROTARY_OFF, type RotaryState } from './rotary.ts';

class RotaryStore {
	state = $state<RotaryState>(ROTARY_OFF);
	busy = $state(false);
	error = $state<string | null>(null);
	#loaded = false;

	get active() {
		return this.state.active;
	}

	/** Fetched once per page; whoever wants it fresh passes `again`. */
	async load(again = false) {
		if (this.#loaded && !again) return;
		this.#loaded = true;
		try {
			const response = await fetch('/api/machine/rotary');
			if (!response.ok) return;
			this.state = { ...ROTARY_OFF, ...(await response.json()) };
		} catch {
			// Keep quiet: without a server nothing can be burned either, and the
			// connection card already says so. What must not happen is a rotary that
			// reports itself as *on* because a fetch failed — hence the untouched state.
		}
	}

	async #post(path: string, body: unknown): Promise<boolean> {
		this.busy = true;
		this.error = null;
		try {
			const token = typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			const response = await fetch(path, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify(body)
			});
			if (!response.ok) {
				const data = await response.json().catch(() => null);
				this.error =
					typeof data?.detail === 'string'
						? apiError(response, data.detail)
						: t('rotary.failed', { status: response.status });
				return false;
			}
			this.state = { ...ROTARY_OFF, ...(await response.json()) };
			return true;
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return false;
		} finally {
			this.busy = false;
		}
	}

	/** Change what you pass; the rest stays as it was. */
	save(fields: Partial<RotaryState>) {
		return this.#post('/api/machine/rotary', fields);
	}

	/** "I meant this, I measured that" -> the new Y factor, computed by the engine. */
	calibrate(commandedMm: number, measuredMm: number) {
		return this.#post('/api/machine/rotary/calibrate', {
			commanded_mm: commandedMm,
			measured_mm: measuredMm
		});
	}
}

export const rotary = new RotaryStore();
