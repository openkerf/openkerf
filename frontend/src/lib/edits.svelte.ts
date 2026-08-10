/**
 * Bewerkingen op elementen: verplaatsen, schalen, ongedaan maken.
 *
 * Let op de undo-eigenaardigheid van de engine: undo herstelt een snapshot van
 * de boom, en de herstelde nodes komen terug zónder id. Hernummeren geeft
 * daarna *andere* id's dan ervoor. De API meldt dat met `ids_invalidated`, en
 * wij laten de selectie dan los — anders zou een bewaard id later een ander
 * element kunnen aanwijzen.
 */

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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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

	rotate(ids: string[] | string, angleDeg: number) {
		return this.#post('/api/design/rotate', { ids, angle_deg: angleDeg });
	}

	assign(ids: string[] | string, operationId: string) {
		return this.#post('/api/design/assign', { ids, operation_id: operationId });
	}

	unassign(ids: string[] | string, operationId: string) {
		return this.#post('/api/design/unassign', { ids, operation_id: operationId });
	}

	/** Tekenen: de vorm komt op het bed en is meteen geselecteerd. */
	draw(shape: Record<string, unknown>) {
		return this.#post('/api/design/elements', shape);
	}

	remove(ids: string[] | string) {
		return this.#post('/api/design/elements/delete', { ids });
	}

	duplicate(ids: string[] | string) {
		return this.#post('/api/design/elements/duplicate', { ids });
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

	async removeLayer(id: string) {
		return this.#send(`/api/design/operations/${encodeURIComponent(id)}`, 'DELETE');
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return { ok: false, idsInvalidated: false };
		} finally {
			this.busy = false;
		}
	}

	undo() {
		return this.#post('/api/design/undo');
	}

	redo() {
		return this.#post('/api/design/redo');
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return 'Geen of onjuiste token — bewerken is geblokkeerd.';
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return body.detail;
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
	} catch {
		/* val terug op de generieke tekst */
	}
	return `De engine weigerde de bewerking (${response.status}).`;
}
