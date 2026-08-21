/**
 * Tiles: burning a board that is bigger than the bed.
 *
 * The division is computed and not stored — it is fetched again as soon as the
 * design or the board size changes. The running series comes from the status
 * payload, so canvas, top bar and phone all see the same state.
 */

import { apiError, t } from './i18n/core.ts';

export type TileRect = { x0_mm: number; y0_mm: number; x1_mm: number; y1_mm: number };
export type Tile = {
	index: number;
	row: number;
	column: number;
	burn: TileRect;
	/** How far the board has to shift relative to the previous tile. Null on the
	 *  first one. The server works this out, because it is the step between the
	 *  windows and not the one between the burn areas — see `_tile_json`. */
	shift_mm: { x: number; y: number } | null;
};
export type Mark = {
	boundary: number;
	/** Whether the overlap zone is tall and narrow. Decides which side the number
	 *  of a mark sits on — burned *and* on the canvas, so the two agree. */
	along_y: boolean;
	points: { x_mm: number; y_mm: number }[];
};

export type TileLayout = { tiles: Tile[]; marks: Mark[]; crossings: number };
export type TileRun = {
	tiles: number;
	current: number;
	done: number[];
	aligned: boolean;
	stale: boolean;
	message: string;
	angle_deg: number | null;
	distance_error_mm: number | null;
};

export class TilingStore {
	layout = $state<TileLayout | null>(null);
	run = $state<TileRun | null>(null);
	busy = $state(false);
	error = $state<string | null>(null);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	/** The tile whose turn it is now, or nothing. */
	get current(): Tile | null {
		if (!this.run || !this.layout) return null;
		return this.layout.tiles[this.run.current] ?? null;
	}

	async load() {
		try {
			const response = await fetch('/api/tiling');
			this.layout = response.ok ? await response.json() : null;
		} catch {
			this.layout = null;
		}
	}

	/**
	 * Where the head is *now*, read from the server.
	 *
	 * Not from the status snapshot: that is up to two seconds old, and when
	 * tapping a mark that is the difference between "where the head is" and "where
	 * it was". Measured with the grbl mock: the panel thought (5,5) while the
	 * server read (0,235) — 230 mm off, and the second tap did use the server's
	 * live position. Two sources for one measurement is exactly the failure this
	 * whole feature has to rule out, so both taps now read the same thing.
	 */
	async liveHead(): Promise<{ x_mm: number; y_mm: number } | null> {
		try {
			const response = await fetch('/api/devices');
			if (!response.ok) return null;
			const all = await response.json();
			const active = all.find((d: { active?: boolean }) => d.active) ?? all[0];
			const mm = active?.position?.mm;
			return Array.isArray(mm) ? { x_mm: mm[0], y_mm: mm[1] } : null;
		} catch {
			return null;
		}
	}

	/** The series comes from the status payload; this is called from there. */
	adopt(state: TileRun | null) {
		this.run = state;
	}

	async #send(path: string, body?: unknown) {
		this.busy = true;
		this.error = null;
		try {
			const token = this.#token();
			const response = await fetch(path, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = apiError(response, (await response.json().catch(() => null))?.detail);
				return false;
			}
			this.run = this.#normalise(await response.json());
			return true;
		} catch {
			// Without this there is nothing to see when the connection drops: the
			// failure flies out uncaught, `error` stays empty and the user stands at
			// the machine looking at a button that did nothing. In a workshop that is
			// not an edge case.
			this.error = t('error.noMachine');
			return false;
		} finally {
			this.busy = false;
		}
	}

	/**
	 * A series that has finished or been cancelled is no longer a series.
	 *
	 * `cancel` answers with `{cancelled: true}` and a closing `advance` with
	 * `{finished: true}` — both without the fields of a running series. Adopting
	 * those raw would briefly put the store in a shape that means nothing (`tiles`
	 * and `aligned` suddenly empty) until the next status report overwrites it a
	 * second later. Here that is simply `null`, which is what it is.
	 */
	#normalise(data: unknown): TileRun | null {
		const body = data as Record<string, unknown> | null;
		if (!body || body.cancelled || body.finished) return null;
		return body as unknown as TileRun;
	}

	start = () => this.#send('/api/tiling/start');
	/** `confirm: true` confirms that an already burned tile may go again. */
	burn = (confirm = false) => this.#send('/api/tiling/burn', confirm ? { confirm: true } : undefined);
	advance = () => this.#send('/api/tiling/advance');
	cancel = () => this.#send('/api/tiling/cancel');

	/**
	 * The offer on the canvas: switch tiling on and start straight away.
	 *
	 * In two steps because they are two things — a setting on the sheet, and a
	 * series that runs — but to the user it is one answer to one question. Sending
	 * them off to a setting that is nowhere on screen is exactly what this button
	 * has to prevent.
	 */
	async enableAndStart(sheetId: string) {
		this.busy = true;
		this.error = null;
		try {
			const token = this.#token();
			const headers = {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			};
			const on = await fetch(`/api/sheets/${sheetId}`, {
				method: 'PATCH',
				headers,
				body: JSON.stringify({ tiling: { enabled: true } })
			});
			if (!on.ok) {
				this.error = apiError(on, (await on.json().catch(() => null))?.detail);
				return false;
			}
		} catch {
			this.error = t('error.noMachine');
			return false;
		} finally {
			this.busy = false;
		}
		await this.load();
		return this.start();
	}

	/**
	 * "Here": the current head position as a tapped point.
	 *
	 * For the first tile that is the corner of the board, after that a mark. Two
	 * marks means tapping twice; the server keeps track of how many there are.
	 */
	alignHere = (reference: 'plate_corner' | 'markers', earlier: { x_mm: number; y_mm: number }[] = []) =>
		this.#send('/api/tiling/align', { reference, points: earlier, use_current: true });
}
