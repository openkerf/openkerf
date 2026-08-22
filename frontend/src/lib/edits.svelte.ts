/**
 * Edits on elements: moving, scaling, undoing.
 *
 * Mind the engine's undo peculiarity: undo restores a snapshot of the tree, and the
 * restored nodes come back *without* ids. Renumbering then gives *different* ids from
 * before. The API reports that with `ids_invalidated`, and we let the selection go —
 * otherwise a stored id would later point at a different
 * point at an element.
 */

import { apiError, t } from './i18n/core.ts';

export type EditResult = { ok: boolean; idsInvalidated: boolean };

export class EditController {
	busy = $state(false);
	error = $state<string | null>(null);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	#headers(): Record<string, string> {
		const headers: Record<string, string> = { 'Content-Type': 'application/json' };
		const token = this.#token();
		if (token) headers.Authorization = `Bearer ${token}`;
		return headers;
	}

	async #post(path: string, body?: unknown): Promise<EditResult> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, {
				method: 'POST',
				headers: this.#headers(),
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = await describe(response);
				return { ok: false, idsInvalidated: false };
			}
			const data = await response.json();
			return { ok: true, idsInvalidated: Boolean(data?.ids_invalidated) };
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return { ok: false, idsInvalidated: false };
		} finally {
			this.busy = false;
		}
	}

	move(ids: string[] | string, dxMm: number, dyMm: number) {
		return this.#post('/api/design/move', { ids, dx_mm: dxMm, dy_mm: dyMm });
	}

	resize(ids: string[] | string, xMm: number, yMm: number, widthMm: number, heightMm: number) {
		return this.#post('/api/design/resize', {
			ids,
			x_mm: xMm,
			y_mm: yMm,
			width_mm: widthMm,
			height_mm: heightMm
		});
	}

	/**
	 * Rotating about the centre of the selection.
	 *
	 * With `absolute` the angle is a destination and not a step: the server works out
	 * how much still has to be added from the state the shapes are in *now*. That is
	 * what makes an angle field usable — typing the same number gives the same picture,
	 * however often you have clicked.
	 */
	rotate(ids: string[] | string, angleDeg: number, absolute = false) {
		return this.#post('/api/design/rotate', {
			ids,
			angle_deg: angleDeg,
			absolute
		});
	}

	assign(ids: string[] | string, operationId: string) {
		return this.#post('/api/design/assign', { ids, operation_id: operationId });
	}

	unassign(ids: string[] | string, operationId: string) {
		return this.#post('/api/design/unassign', { ids, operation_id: operationId });
	}

	/** Drawing: the shape lands on the bed and is selected at once. */
	draw(shape: Record<string, unknown>) {
		return this.#post('/api/design/elements', shape);
	}

	remove(ids: string[] | string) {
		return this.#post('/api/design/elements/delete', { ids });
	}

	duplicate(ids: string[] | string) {
		return this.#post('/api/design/elements/duplicate', { ids });
	}

	/**
	 * One click on a palette swatch (decision B2).
	 *
	 * With a selection it moves to the layer of that colour, which is created if need
	 * be from what that colour did on this machine before. Without a selection it sets
	 * the colour for new work.
	 */
	async paletteColor(color: string, ids: string[] = []) {
		const result = await this.#post('/api/design/palette', {
			color,
			ids: ids.length ? ids : undefined
		});
		return result.ok;
	}

	addLayer(type: string, label?: string, speed?: number, powerPercent?: number) {
		return this.#post('/api/design/operations', {
			type,
			label,
			speed,
			power_percent: powerPercent
		});
	}

	async updateLayer(id: string, fields: Record<string, unknown>) {
		return this.#send(`/api/design/operations/${encodeURIComponent(id)}`, 'PATCH', fields);
	}

	/** A layer up or down in the burn order — engrave before cut. */
	async moveLayer(id: string, direction: 'up' | 'down') {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/move`, {
			direction
		});
	}

	/**
	 * Dragging a layer to a place in the list (gap L1).
	 *
	 * A destination and not a number of steps: while dragging, the list knows where the
	 * layer has to end up, and converting that into steps goes wrong as soon as a test
	 * grid sits in between.
	 */
	async dropLayerAt(id: string, index: number) {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/move`, { index });
	}

	/** Engraving before cutting, in one action (gap L2). */
	async sortLayers() {
		return this.#post('/api/design/operations/sort');
	}

	/**
	 * Changing the kind of operation of an existing layer (gap L3).
	 *
	 * The layer gets a new id from this — the engine cannot change the type of a node,
	 * so the server makes a new one and moves the shapes. Whoever holds the old id
	 * points at nothing afterwards.
	 */
	async retypeLayer(id: string, type: string) {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/type`, { type });
	}

	async removeLayer(id: string) {
		return this.#send(`/api/design/operations/${encodeURIComponent(id)}`, 'DELETE');
	}

	/**
	 * Every ordinary layer in one operation (point 4 from the second test round).
	 *
	 * The shapes stay; they are in no layer afterwards. Cells of a test grid stay put —
	 * those go out as a board, not as a single layer.
	 */
	async removeAllLayers() {
		return this.#send('/api/design/operations', 'DELETE');
	}

	async #send(path: string, method: string, body?: unknown): Promise<EditResult> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, {
				method,
				headers: this.#headers(),
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = await describe(response);
				return { ok: false, idsInvalidated: false };
			}
			return { ok: true, idsInvalidated: false };
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return { ok: false, idsInvalidated: false };
		} finally {
			this.busy = false;
		}
	}

	updateText(id: string, fields: Record<string, unknown>) {
		return this.#send(`/api/design/elements/${encodeURIComponent(id)}/text`, 'PATCH', fields);
	}

	updateLine(id: string, fields: Record<string, number>) {
		return this.#send(`/api/design/elements/${encodeURIComponent(id)}/line`, 'PATCH', fields);
	}

	/** Moving one node. Returns the id: this turns a shape into a path, and it gets a
	 *  new id then. */
	async moveNode(
		id: string,
		index: number,
		xMm: number,
		yMm: number
	): Promise<{ id: string } | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(`/api/design/elements/${encodeURIComponent(id)}/nodes`, {
				method: 'PATCH',
				headers: this.#headers(),
				body: JSON.stringify({ index, x_mm: xMm, y_mm: yMm })
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	/**
	 * The three other node edits, and the handle.
	 *
	 * All four hand back the JSON and not just `ok`, for the same reason `moveNode` does:
	 * a rectangle becomes a path the moment one of its nodes is touched, and then it has a
	 * new id. A caller that does not follow that id loses the selection in mid-work.
	 */
	addNode(id: string, where: { segmentIndex?: number; t?: number; xMm?: number; yMm?: number }) {
		return this.#node(`/api/design/elements/${encodeURIComponent(id)}/nodes`, 'POST', {
			segment_index: where.segmentIndex,
			t: where.t,
			x_mm: where.xMm,
			y_mm: where.yMm
		});
	}

	removeNode(id: string, index: number) {
		return this.#node(
			`/api/design/elements/${encodeURIComponent(id)}/nodes/${index}`,
			'DELETE'
		);
	}

	/** A segment's kind: a corner into a curve and back. */
	setSegmentKind(id: string, index: number, kind: 'line' | 'quad' | 'cubic') {
		return this.#node(
			`/api/design/elements/${encodeURIComponent(id)}/segments/${index}/kind`,
			'PATCH',
			{ kind }
		);
	}

	/** Dragging a curve's handle. `which` is 1 or 2; a quad and an arc only have a 1. */
	moveControl(id: string, index: number, which: number, xMm: number, yMm: number) {
		return this.#node(
			`/api/design/elements/${encodeURIComponent(id)}/segments/${index}/control`,
			'PATCH',
			{ which, x_mm: xMm, y_mm: yMm }
		);
	}

	async #node(
		path: string,
		method: string,
		body?: Record<string, unknown>
	): Promise<{ id: string; was?: string; index?: number } | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, {
				method,
				headers: this.#headers(),
				body: body === undefined ? undefined : JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	offset(ids: string[], distanceMm: number) {
		return this.#post('/api/design/offset', { ids, distance_mm: distanceMm });
	}

	simplify(ids: string[]) {
		return this.#post('/api/design/simplify', { ids });
	}

	/**
	 * CornersDialog afronden of afschuinen.
	 *
	 * Returns the answer itself instead of only `ok`, because there are two things in
	 * it the user has to see: how many corners were skipped (sides too short, or an arc
	 * meeting at the corner), and which ids they have become — bevelling turns them into
	 * a path, and that gets a new id.
	 */
	/**
	 * Giving a shape an area, or taking it away.
	 *
	 * Needed to grid something you drew yourself: the rasteriser fills what has a
	 * fill and otherwise only draws a line around the shape.
	 */
	async fill(
		ids: string[],
		filled: boolean
	): Promise<{ filled: number; cleared: number; skipped: number } | null> {
		return this.#postJson('/api/design/fill', { ids, filled });
	}

	/** Splitting a path into its loose pieces. */
	async split(
		ids: string[]
	): Promise<{ ids: string[]; count: number; skipped: number } | null> {
		return this.#postJson('/api/design/split', { ids });
	}

	/** Putting the selection in one layer, and out of all the others. */
	async singleLayer(
		ids: string[],
		kind: 'cut' | 'engrave' | 'raster'
	): Promise<{
		operation_id: string;
		type: string;
		assigned: number;
		removed: number;
		created: boolean;
	} | null> {
		return this.#postJson('/api/design/single-layer', { ids, type: kind });
	}

	/**
	 * Bridges (tabs) in a cut line, on the whole selection at once.
	 *
	 * Millimetres go in; the API turns them into the engine's own units. Either a
	 * count — then the engine spreads them evenly and keeps doing so when the shape
	 * is resized — or an explicit list of percentages along the path.
	 */
	async setBridges(
		ids: string[],
		fields: { count?: number; length_mm?: number; positions_percent?: number[] }
	): Promise<{ bridged: number; skipped: number; count: number; length_mm: number } | null> {
		return this.#postJson('/api/design/bridges', { ids, ...fields });
	}

	async clearBridges(ids: string[]): Promise<{ cleared: number; ids: string[] } | null> {
		return this.#postJson('/api/design/bridges/clear', { ids });
	}

	/** Lege layers gone. */
	async prune(): Promise<{ removed: number; ids: string[] } | null> {
		return this.#postJson('/api/design/operations/prune', {});
	}

	/**
	 * A POST whose answer itself is needed.
	 *
	 * `#post` above returns only ok/idsInvalidated; these operations report how much
	 * they did, and that number appears in the panel.
	 */
	async #postJson<T>(pad: string, body: unknown): Promise<T | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(pad, {
				method: 'POST',
				headers: this.#headers(),
				body: JSON.stringify(body)
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	async corners(
		ids: string[],
		style: 'round' | 'chamfer',
		sizeMm: number
	): Promise<{ rounded: string[]; paths: string[]; skipped: number } | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch('/api/design/corners', {
				method: 'POST',
				headers: this.#headers(),
				body: JSON.stringify({ ids, style, size_mm: sizeMm })
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	effect(ids: string[], effect: string) {
		return this.#post('/api/design/effect', { ids, effect });
	}

	mirror(ids: string[], axis: 'horizontal' | 'vertical') {
		return this.#post('/api/design/mirror', { ids, axis });
	}

	boolean(ids: string[], operation: string) {
		return this.#post('/api/design/boolean', { ids, operation });
	}

	align(ids: string[], mode: string) {
		return this.#post('/api/design/align', { ids, mode });
	}

	group(ids: string[]) {
		return this.#post('/api/design/group', { ids });
	}

	ungroup(ids: string[]) {
		return this.#post('/api/design/ungroup', { ids });
	}

	home(physical = false) {
		return this.#post('/api/machine/home', { physical });
	}

	jog(dxMm: number, dyMm: number) {
		return this.#post('/api/machine/jog', { dx_mm: dxMm, dy_mm: dyMm });
	}

	unlock() {
		return this.#post('/api/machine/unlock');
	}

	undo() {
		return this.#post('/api/design/undo');
	}

	redo() {
		return this.#post('/api/design/redo');
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return t('error.noToken');
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return apiError(response, body.detail);
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
	} catch {
		/* fall back to the generic sentence */
	}
	return t('error.editRefused', { status: response.status });
}
