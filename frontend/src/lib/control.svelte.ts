/**
 * Write actions towards the API.
 *
 * The API leaves writing open as long as it listens on localhost; as soon as it binds
 * wider (phone/tablet) a token is required. We keep that token in localStorage so the
 * PWA does not ask for it again every session.
 */

import { apiError, t } from './i18n/core.ts';
import type { Capabilities } from './api';
import { connection } from './connection.svelte';

const TOKEN_KEY = 'openkerf.token';

/** A place on the bed this machine remembers (gap J6). */
export type Position = { name: string; x_mm: number; y_mm: number };

/**
 * The user's zero point (gap J12), as loose module state.
 *
 * Two screens need it: the Job panel, which sets it, and the canvas, which shows
 * where the work lands. Those two are not inside each other and the page between them
 * does not belong to this round, so rather than threading a prop through three layers
 * it lives here — one value, two readers.
 */
/** What the machine knows about where the printed sheet lies. */
export type PrintCut = {
	marks: {
		id: string;
		drawn: { x_mm: number; y_mm: number } | null;
		measured: { x_mm: number; y_mm: number } | null;
	}[];
	/** How far the first mark moved: what you can check with a ruler. */
	offset_mm: { x_mm: number; y_mm: number } | null;
	aligned: boolean;
	angle_deg: number | null;
	dx_mm: number | null;
	dy_mm: number | null;
	distance_error_mm: number | null;
	tolerance_mm: number;
	max_angle_deg: number;
	/** Why an alignment that was there is gone: the marks, or the machine. */
	lapsed: string | null;
};

class Nulpunt {
	point = $state<{ x_mm: number; y_mm: number } | null>(null);
	#loaded = false;

	/** Fetched once per page; whoever wants it again passes `again`. */
	async laad(again = false) {
		if (this.#loaded && !again) return;
		this.#loaded = true;
		try {
			const response = await fetch('/api/machine/origin');
			if (!response.ok) return;
			this.point = (await response.json()).origin ?? null;
		} catch {
			// Keep quiet: without a server there is nothing to send anyway, and the
			// connection card already says so.
		}
	}
}

export const origin = new Nulpunt();

export class Controller {
	capabilities = $state<Capabilities | null>(null);
	token = $state('');
	busy = $state<string | null>(null);
	error = $state<string | null>(null);
	/**
	 * The server has refused our token.
	 *
	 * Without this you were stuck: `needsToken` is only true when there is *no* token,
	 * so with a wrong token the input field disappeared and every action failed with a
	 * 401 with no way back. Now the field returns as soon as the server
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

	/** Should the token field be on screen? Also when there *is* a token, a wrong one. */
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

	/**
	 * Same as `#post`, but with the answer.
	 *
	 * `#post` reports only whether it worked, and for most buttons that is all there
	 * is to know. An import is the exception: what came in is in the answer.
	 */
	async #postJson(
		path: string,
		action: string,
		body?: FormData
	): Promise<Record<string, unknown> | null> {
		this.busy = action;
		this.error = null;
		try {
			const response = await fetch(path, { method: 'POST', headers: this.#headers(), body });
			if (response.status === 401) this.rejected = true;
			if (!response.ok) {
				this.error = await describeFailure(response, this.token !== '');
				return null;
			}
			this.rejected = false;
			return (await response.json().catch(() => ({}))) as Record<string, unknown>;
		} catch (e) {
			this.error = onbereikbaar(e);
			return null;
		} finally {
			this.busy = null;
		}
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
	 * Sending the head around the outline of the work. No laser, only movement.
	 *
	 * The machine can report that it is still busy; that lands in `error` here, because
	 * otherwise you think you have seen the frame while a
	 * corner ontbrak.
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

	/**
	 * The job as a file in the machine's memory. It puts it there and starts nothing.
	 *
	 * What comes back is the name the panel will show, which is not always the name
	 * that went in: eight characters, capitals, no spaces. The screen has already
	 * worked that out with `machineName` so the two agree, and it is the answer that
	 * gets shown — a name computed twice and reported from the wrong copy is exactly
	 * the sort of thing this pair exists to prevent.
	 *
	 * Every refusal of this route is a 409 with a code, so `describeFailure` says it
	 * in the reader's language along with all the others; the two that break off
	 * halfway bring the numbers and the flag their sentence needs.
	 */
	async upload(name: string): Promise<{ name: string; bytes: number; chunks: number } | null> {
		this.busy = 'upload';
		this.error = null;
		try {
			const response = await fetch('/api/machine/upload', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...this.#headers() },
				body: JSON.stringify({ name })
			});
			if (response.status === 401) this.rejected = true;
			if (!response.ok) {
				this.error = await describeFailure(response, this.token !== '');
				return null;
			}
			this.rejected = false;
			return (await response.json()) as { name: string; bytes: number; chunks: number };
		} catch (e) {
			this.error = onbereikbaar(e);
			return null;
		} finally {
			this.busy = null;
		}
	}

	/** Called on a successful start — the wow moment hangs off this. */
	onStarted: (() => void) | null = null;

	async start() {
		const ok = await this.#post('/api/job/start', 'start');
		// On the press of the button, not on the polling: a short job is over before
		// the status ever shows it as "running".
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
	 * Opening or closing the connection to the machine.
	 *
	 * Not every driver knows it: Ruida has `ruida_connect`, the USB families
	 * `usb_connect`, and grbl opens by itself as soon as work goes to it. What the
	 * capabilities set to false should not be a button.
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

	// -------------------------------------------------- moving to a point

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
	 * Sending the head to an absolute place on the bed (gap J6).
	 *
	 * Carries both "to the origin" and the saved positions. The jog buttons go through
	 * the page because that has to update the canvas; this is a jump to a point and does
	 * not need it.
	 */
	moveTo(xMm: number, yMm: number) {
		return this.#json('/api/machine/move', 'move', 'POST', { x_mm: xMm, y_mm: yMm });
	}

	/**
	 * Positions this machine remembers.
	 *
	 * They live on the device service in the engine, not in the browser: a position
	 * belongs to the machine with the jig on it, not to the laptop you
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

	/** Without coordinates: where the head is now. */
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

	// -------------------------------------------------- the zero point (gap J12)
	//
	// LightBurn's Set Origin: you put a zero point on your workpiece and the work
	// burns from there. That is the operation when aligning on an offcut — the board
	// lies where it lies, and you do not want to drag your whole drawing onto it.
	//
	// The zero point lives on the machine (like the saved positions), not in the
	// browser: it belongs to *this* laser with *this* piece of wood in it.

	get origin() {
		return origin.point;
	}

	loadOrigin() {
		return origin.laad(true);
	}

	/** Without coordinates: where the head is now. */
	async setOrigin(xMm?: number, yMm?: number) {
		const body = xMm === undefined || yMm === undefined ? {} : { x_mm: xMm, y_mm: yMm };
		const uitslag = await this.#json('/api/machine/origin', 'set-origin', 'POST', body);
		if (uitslag) origin.point = { x_mm: uitslag.x_mm, y_mm: uitslag.y_mm };
		return uitslag;
	}

	async clearOrigin() {
		const uitslag = await this.#json('/api/machine/origin', 'clear-origin', 'DELETE');
		if (uitslag) origin.point = null;
		return uitslag;
	}

	// ------------------------------------------- print and cut (gap H2)
	//
	// The other half of the same idea as the zero point: there the material lies
	// somewhere and you say where, here the material already carries marks and the
	// machine measures where. Two points, so it can turn as well as shift — which the
	// zero point cannot, and which is exactly what a printed sheet needs.
	//
	// Lives on the machine too, and only in its memory: a pose is a statement about
	// where a sheet lies *now*.

	printcut = $state<PrintCut | null>(null);

	async loadPrintCut() {
		try {
			const response = await fetch('/api/printcut');
			if (response.ok) this.printcut = await response.json();
		} catch {
			// Same silence as the zero point: the connection card already says it.
		}
	}

	/** The two shapes in the drawing that are on the material as well. */
	async setPrintCutMarks(ids: string[]) {
		const result = await this.#json('/api/printcut/marks', 'printcut-marks', 'POST', { ids });
		if (result) this.printcut = result;
		return result;
	}

	/** Where the head is standing now: over mark 1 (0) or mark 2 (1). */
	async measurePrintCut(index: number) {
		const result = await this.#json('/api/printcut/measure', 'printcut-measure', 'POST', {
			index
		});
		if (result) this.printcut = result;
		return result;
	}

	async clearPrintCut() {
		const result = await this.#json('/api/printcut/clear', 'printcut-clear', 'POST');
		if (result) this.printcut = result;
		return result;
	}

	// ---------------------------- adjusting during a running job (gap J11)
	//
	// Only when the driver has a realtime channel. On a Ruida `capabilities.adjust` is
	// false and these buttons do not exist — see machine.py for why that is not a
	// shortcoming of ours.

	adjust = $state<{ power: number | null; speed: number | null }>({
		power: null,
		speed: null
	});

	get canAdjust() {
		const may = this.capabilities?.adjust;
		return Boolean(may?.power || may?.speed);
	}

	async loadAdjustment() {
		try {
			const response = await fetch('/api/job/adjust');
			if (!response.ok) return;
			const data = await response.json();
			this.adjust = { power: data.power ?? null, speed: data.speed ?? null };
		} catch {
			// See loadOrigin.
		}
	}

	/** `factor` multiplies what the layer says; 1 is "as designed". */
	async setAdjustment(wat: 'power' | 'speed', factor: number) {
		const geknipt = Math.min(2, Math.max(0.1, Math.round(factor * 100) / 100));
		const uitslag = await this.#json('/api/job/adjust', `adjust-${wat}`, 'POST', {
			[wat]: geknipt
		});
		if (uitslag) this.adjust = { power: uitslag.power ?? null, speed: uitslag.speed ?? null };
		return uitslag;
	}

	/**
	 * Importing a drawing: it is added to the sheet, not put in its place.
	 *
	 * Hands back the ids of what came in, so the interface can select it. Whoever
	 * imports wants to move the new work somewhere, and among shapes that were
	 * already there you cannot see which ones just arrived.
	 */
	async load(file: File): Promise<string[] | null> {
		const form = new FormData();
		form.append('file', file);
		const body = await this.#postJson('/api/job/load', 'load', form);
		if (body === null) return null;
		const added = body.added;
		return Array.isArray(added) ? added.filter((id): id is string => typeof id === 'string') : [];
	}
}

/**
 * A failed fetch is almost never "a network error".
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
	const rows = output
		.map((r) => r.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').trim())
		.filter((r) => r && !/^(plan|spool|load|estop|abort|pause|resume)\b/.test(r));
	return (rows.length ? rows : output).join(' · ');
}
