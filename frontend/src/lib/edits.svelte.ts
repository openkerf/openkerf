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

	/**
	 * Draaien om het midden van de selectie.
	 *
	 * Met `absolute` is de hoek een bestemming en geen stap: de server rekent
	 * uit hoeveel er nog bij moet vanaf de stand die de vormen nú hebben. Dat
	 * is wat een hoekveld bruikbaar maakt — hetzelfde getal intikken levert
	 * hetzelfde beeld op, hoe vaak je ook geklikt hebt.
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

	/**
	 * Eén klik op een paletvakje (besluit B2).
	 *
	 * Mét selectie verhuist die naar de laag van die kleur, die zo nodig wordt
	 * aangemaakt op wat die kleur op deze machine eerder deed. Zonder selectie
	 * zet hij de kleur voor nieuw werk.
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

	/** Een laag omhoog of omlaag in de brandvolgorde — graveren vóór snijden. */
	async moveLayer(id: string, direction: 'up' | 'down') {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/move`, {
			direction
		});
	}

	/**
	 * Een laag naar een plek in de lijst slepen (gat L1).
	 *
	 * Een bestemming en geen aantal stappen: bij het slepen weet de lijst waar
	 * de laag terecht moet, en dat omrekenen naar stapjes gaat mis zodra er een
	 * testraster tussen staat.
	 */
	async dropLayerAt(id: string, index: number) {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/move`, { index });
	}

	/** Graveren vóór snijden, in één handeling (gat L2). */
	async sortLayers() {
		return this.#post('/api/design/operations/sort');
	}

	/**
	 * Het soort bewerking van een bestaande laag wijzigen (gat L3).
	 *
	 * De laag krijgt hierdoor een nieuw id — de engine kan het type van een
	 * knoop niet wisselen, dus de server maakt er een nieuwe en verhuist de
	 * vormen. Wie het oude id vasthoudt, wijst daarna nergens meer naar.
	 */
	async retypeLayer(id: string, type: string) {
		return this.#post(`/api/design/operations/${encodeURIComponent(id)}/type`, { type });
	}

	async removeLayer(id: string) {
		return this.#send(`/api/design/operations/${encodeURIComponent(id)}`, 'DELETE');
	}

	/**
	 * Alle gewone lagen in één handeling (punt 4 uit de tweede testronde).
	 *
	 * De vormen blijven; ze zitten daarna in geen enkele laag. Cellen van een
	 * testraster blijven staan — die gaan er als bord uit, niet als losse laag.
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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

	/** Eén knooppunt verleggen. Geeft het id terug: een vorm wordt hierdoor een
	 *  pad en krijgt dan een nieuw id. */
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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
	 * Hoeken afronden of afschuinen.
	 *
	 * Geeft het antwoord zelf terug in plaats van alleen `ok`, want er staan twee
	 * dingen in die de gebruiker moet zien: hoeveel hoeken zijn overgeslagen
	 * (te korte zijden, of een boog die op de hoek uitkomt), en welke id's het
	 * geworden zijn — afschuinen maakt er een pad van, en dat krijgt een nieuw id.
	 */
	/** Een pad opdelen in zijn losse stukken. */
	async split(
		ids: string[]
	): Promise<{ ids: string[]; count: number; skipped: number } | null> {
		return this.#postJson('/api/design/split', { ids });
	}

	/** De selectie in één laag zetten, en uit alle andere halen. */
	async singleLayer(
		ids: string[],
		kind: 'cut' | 'engrave'
	): Promise<{
		operation_id: string;
		type: string;
		assigned: number;
		removed: number;
		created: boolean;
	} | null> {
		return this.#postJson('/api/design/single-layer', { ids, type: kind });
	}

	/** Lege lagen weg. */
	async prune(): Promise<{ removed: number; ids: string[] } | null> {
		return this.#postJson('/api/design/operations/prune', {});
	}

	/**
	 * POST waarvan het antwoord zelf nodig is.
	 *
	 * `#post` hierboven geeft alleen ok/idsInvalidated terug; deze handelingen
	 * melden hoeveel ze gedaan hebben, en dat getal staat in het paneel.
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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
			this.error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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

	clear() {
		return this.#post('/api/design/clear');
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
