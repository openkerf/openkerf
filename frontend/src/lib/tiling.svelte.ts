/**
 * Tegels: een plaat branden die groter is dan het bed.
 *
 * De opdeling is berekend en niet opgeslagen — hij wordt opnieuw opgehaald
 * zodra het ontwerp of de plaatmaat verandert. De lopende reeks komt uit de
 * statuspayload, zodat canvas, bovenbalk en telefoon dezelfde stand zien.
 */

export type TileRect = { x0_mm: number; y0_mm: number; x1_mm: number; y1_mm: number };
export type Tile = { index: number; row: number; column: number; burn: TileRect };
export type Mark = { boundary: number; points: { x_mm: number; y_mm: number }[] };

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

	/** De tegel die nu aan de beurt is, of niets. */
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

	/** De reeks komt uit de statuspayload; deze wordt daar aangeroepen. */
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
				this.error = (await response.json().catch(() => null))?.detail ?? 'Dat lukte niet.';
				return false;
			}
			this.run = this.#normaliseer(await response.json());
			return true;
		} catch {
			// Zonder dit valt er bij een wegvallende verbinding niets te zien:
			// de fout vliegt ongevangen naar buiten, `error` blijft leeg en de
			// gebruiker staat aan de machine naar een knop te kijken die niets
			// deed. In een werkplaats is dat geen randgeval.
			this.error = 'Geen verbinding met de machine. Probeer het opnieuw.';
			return false;
		} finally {
			this.busy = false;
		}
	}

	/**
	 * Een reeks die afgelopen of afgebroken is, is geen reeks meer.
	 *
	 * `cancel` antwoordt met `{cancelled: true}` en een afrondende `advance` met
	 * `{finished: true}` — allebei zonder de velden van een lopende reeks. Die
	 * rauw overnemen zou de store even in een vorm zetten die nergens op slaat
	 * (`tiles` en `aligned` ineens leeg), tot de volgende statusmelding hem een
	 * seconde later overschrijft. Hier is dat gewoon `null`, wat het is.
	 */
	#normaliseer(data: unknown): TileRun | null {
		const body = data as Record<string, unknown> | null;
		if (!body || body.cancelled || body.finished) return null;
		return body as unknown as TileRun;
	}

	start = () => this.#send('/api/tiling/start');
	burn = () => this.#send('/api/tiling/burn');
	advance = () => this.#send('/api/tiling/advance');
	cancel = () => this.#send('/api/tiling/cancel');

	/**
	 * "Hier": de huidige kopstand als aangetikt punt.
	 *
	 * Voor de eerste tegel is dat de hoek van de plaat, daarna een merk. Twee
	 * merken betekent twee keer aantikken; de server houdt bij hoeveel er zijn.
	 */
	alignHere = (reference: 'plate_corner' | 'markers', earlier: { x_mm: number; y_mm: number }[] = []) =>
		this.#send('/api/tiling/align', { reference, points: earlier, use_current: true });
}
