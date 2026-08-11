/**
 * Het ontwerp zoals het canvas het tekent.
 *
 * Geometrie komt in de interne eenheid van de engine (Tat, 65535 per inch) als
 * SVG-paddata. Omrekenen zou betekenen dat we padstrings moeten herschrijven;
 * in plaats daarvan schaalt het canvas één keer met `units_per_mm`.
 */

export type DesignElement = {
	id: string;
	type: string;
	label: string;
	hidden: boolean;
	stroke: string | null;
	fill: string | null;
	bounds: [number, number, number, number] | null;
	path: string;
	/** Groep waar dit element in zit; een raster is één groep. */
	group_id: string | null;
	/** Gezet voor vector-tekst: de bron waaruit het pad gerenderd is. */
	text: {
		text: string;
		font: string;
		font_size_mm: number | null;
		spacing: number;
		align: 'start' | 'middle' | 'end' | string;
	} | null;
	/** Gezet voor een lijn: de twee eindpunten, want een lijn is geen kader. */
	line: { x1_mm: number; y1_mm: number; x2_mm: number; y2_mm: number } | null;
	/** Gezet voor een afbeelding: kader en resolutie. */
	image: {
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
		pixels: [number, number] | null;
		dpi: number | null;
	} | null;
	/** Hatch of wobble waar dit element in zit. */
	effect: { id: string | null; type: string; label: string } | null;
	operation_id: string | null;
	operation_ids: string[];
};

export type DesignOperation = {
	id: string;
	type: string;
	label: string;
	color: string | null;
	speed: number | null;
	power: number | null;
	passes: number | null;
	/** Alleen zinvol bij raster- en afbeeldingslagen. */
	dpi: number | null;
	overscan: string | null;
	bidirectional: boolean;
	output: boolean;
	element_ids: string[];
	/** Gezet als deze laag een cel van een testraster is. */
	grid?: {
		grid_id: number;
		row: number;
		column: number;
		speed_mm_s: number;
		power_percent: number;
	} | null;
};

export type Design = {
	units_per_mm: number;
	/** Zijn er wijzigingen sinds het laatst opslaan of openen? */
	dirty: boolean;
	elements: DesignElement[];
	operations: DesignOperation[];
};

/** Vaste laagkleuren uit DESIGN-SYSTEM.md, gebruikt als een operatie er geen heeft. */
export const LAYER_COLORS = readLayerColors();

/**
 * De laagkleuren komen uit tokens.css, zodat canvas en paneel dezelfde bron
 * lezen — dat is wat het design system voorschrijft. Buiten de browser (bij
 * het bouwen) valt hij terug op de reeks zoals hij daar staat.
 */
function readLayerColors(): string[] {
	// @tokens-mirror: exacte spiegel van --layer-1..10 in tokens.css. Alleen in
	// gebruik tijdens het bouwen, wanneer er geen document is om uit te lezen.
	const fallback = [
		'#E5484D', '#F76B15', '#FFC53D', '#46A758', '#12A594',
		'#0090FF', '#8E4EC6', '#E93D82', '#8D6E63', '#607D8B'
	];
	if (typeof window === 'undefined') return fallback;
	const style = getComputedStyle(document.documentElement);
	const read = fallback.map(
		(_, i) => style.getPropertyValue(`--layer-${i + 1}`).trim()
	);
	return read.every(Boolean) ? read : fallback;
}

const REFRESH_SIGNALS = new Set(['tree_changed', 'rebuild_tree', 'element_property_update']);

export function isDesignSignal(code: string) {
	return REFRESH_SIGNALS.has(code);
}

export class DesignStore {
	design = $state<Design | null>(null);
	loading = $state(false);
	selectedIds = $state<string[]>([]);
	/**
	 * Voorvertoning tijdens het slepen, in mm. Het canvas schrijft hem, de
	 * bovenbalk en statusbalk lezen hem — zo lopen de coördinaten mee terwijl
	 * je sleept, zonder dat er per muisbeweging een opdracht naar de engine gaat.
	 */
	preview = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	/** Gezet door de pagina om de URL mee te laten lopen met de selectie. */
	onSelect: ((ids: string[]) => void) | null = null;

	#pending = false;

	get elements() {
		return this.design?.elements ?? [];
	}

	/** Eerste selectie; voor panelen die één element tonen. */
	get dirty() {
		return this.design?.dirty ?? false;
	}

	get isEmpty() {
		return this.elements.length === 0;
	}

	get selected(): DesignElement | null {
		return this.elements.find((e) => e.id === this.selectedIds[0]) ?? null;
	}

	get selectedId(): string | null {
		return this.selectedIds[0] ?? null;
	}

	get selectedElements(): DesignElement[] {
		return this.elements.filter((e) => this.selectedIds.includes(e.id));
	}

	isSelected(id: string) {
		return this.selectedIds.includes(id);
	}

	/**
	 * Een groep is één ding. Klik je een lid aan, dan krijg je de hele groep —
	 * anders sleep je een los vierkant uit een testraster.
	 */
	#expand(id: string): string[] {
		const element = this.elements.find((e) => e.id === id);
		if (!element?.group_id) return [id];
		return this.elements.filter((e) => e.group_id === element.group_id).map((e) => e.id);
	}

	select(id: string | null) {
		const next = id ? this.#expand(id) : [];
		if (same(next, this.selectedIds)) return;
		this.selectedIds = next;
		this.onSelect?.(this.selectedIds);
	}

	/**
	 * Meerdere elementen in één keer, bijvoorbeeld uit een sleepkader.
	 *
	 * Niet select() gevolgd door toggle(): die tweede zou een groep die de
	 * eerste net toevoegde meteen weer weghalen, waardoor een sleepkader over
	 * een groep niets leek te selecteren.
	 */
	selectMany(ids: string[]) {
		const expanded = new Set<string>();
		for (const id of ids) this.#expand(id).forEach((member) => expanded.add(member));
		const next = [...expanded];
		if (same(next, this.selectedIds)) return;
		this.selectedIds = next;
		this.onSelect?.(this.selectedIds);
	}

	/** Shift-klik: toevoegen of juist weghalen. */
	toggle(id: string) {
		const members = this.#expand(id);
		const inside = members.every((m) => this.selectedIds.includes(m));
		this.selectedIds = inside
			? this.selectedIds.filter((x) => !members.includes(x))
			: [...this.selectedIds, ...members.filter((m) => !this.selectedIds.includes(m))];
		this.onSelect?.(this.selectedIds);
	}

	/** Wat de gebruiker nú ziet: de sleep-voorvertoning, anders de selectie. */
	get liveBox() {
		return this.preview ?? this.selectedSize;
	}

	/**
	 * Omhullende van de hele selectie in mm. Bij meerdere elementen is dat het
	 * gezamenlijke kader — precies waar de engine ook op werkt bij een resize.
	 */
	get selectedSize(): { x: number; y: number; width: number; height: number } | null {
		const perMm = this.design?.units_per_mm;
		const boxes = this.selectedElements.map((e) => e.bounds).filter(Boolean);
		if (!perMm || boxes.length === 0) return null;
		const x0 = Math.min(...boxes.map((b) => b![0]));
		const y0 = Math.min(...boxes.map((b) => b![1]));
		const x1 = Math.max(...boxes.map((b) => b![2]));
		const y1 = Math.max(...boxes.map((b) => b![3]));
		return {
			x: x0 / perMm,
			y: y0 / perMm,
			width: (x1 - x0) / perMm,
			height: (y1 - y0) / perMm
		};
	}

	get operations() {
		return this.design?.operations ?? [];
	}

	/**
	 * Kleur per operatie: eigen kleur, anders een vaste laagkleur op volgorde.
	 *
	 * De engine geeft soms een kleur met alfa mee (`#0000ff00`, volledig
	 * doorzichtig) voor een operatie die nooit getekend werd. Die is als
	 * laagkleur onbruikbaar — dan pakken we de palet-kleur op volgorde.
	 */
	colorFor(operationId: string | null): string {
		const operations = this.operations;
		const index = operations.findIndex((o) => o.id === operationId);
		if (index < 0) return 'var(--text-2)';
		const eigen = operations[index].color;
		const bruikbaar =
			eigen && !(/^#[0-9a-f]{6}0{2}$/i.test(eigen.trim()));
		return bruikbaar ? eigen : LAYER_COLORS[index % LAYER_COLORS.length];
	}

	/**
	 * Hoe een element op het bed getekend wordt.
	 *
	 * In MeerK40t kan één element in meerdere operaties zitten (de engine
	 * classificeert automatisch op kleur). "De laag" bestaat dus strikt genomen
	 * niet — daarom telt de bovenste, net als bij overlappende lagen in elk
	 * ander tekenprogramma.
	 *
	 * Een element zonder laag wordt gestippeld grijs: dat is geen ontbrekende
	 * kleur maar een waarschuwing. Zo'n vorm wordt niet gebrand.
	 */
	strokeFor(element: { operation_ids?: string[]; operation_id?: string | null }): {
		color: string;
		dashed: boolean;
	} {
		const ids = element.operation_ids?.length
			? element.operation_ids
			: element.operation_id
				? [element.operation_id]
				: [];
		if (!ids.length) return { color: 'var(--text-2)', dashed: true };
		const volgorde = this.operations;
		// De bovenste laag is de eerste in de boom, niet de eerste in de lijst
		// die het element toevallig meekreeg.
		let beste = -1;
		for (const id of ids) {
			const i = volgorde.findIndex((o) => o.id === id);
			if (i >= 0 && (beste < 0 || i < beste)) beste = i;
		}
		if (beste < 0) return { color: 'var(--text-2)', dashed: true };
		return { color: this.colorFor(volgorde[beste].id), dashed: false };
	}

	/** Loopt op bij elke herlaadslag; het canvas hangt hem aan afbeeldings-URL's
	 *  zodat een bewerkte afbeelding niet uit de browsercache komt. */
	revision = $state(0);

	async load() {
		// Signalen komen in bursts binnen; één herlaadslag per burst is genoeg.
		if (this.loading) {
			this.#pending = true;
			return;
		}
		this.loading = true;
		try {
			const response = await fetch('/api/design');
			if (response.ok) {
				this.design = await response.json();
				this.revision += 1;
				// Selecties die door een wijziging verdwenen zijn, laten we los;
				// id's die er nog zijn blijven staan.
				const alive = new Set(this.elements.map((e) => e.id));
				const kept = this.selectedIds.filter((id) => alive.has(id));
				if (kept.length !== this.selectedIds.length) this.selectedIds = kept;
			}
		} catch {
			// Verbinding weg: de statusbalk meldt dat al, hier niets doen.
		} finally {
			this.loading = false;
			if (this.#pending) {
				this.#pending = false;
				void this.load();
			}
		}
	}
}

function same(a: string[], b: string[]) {
	return a.length === b.length && a.every((v, i) => v === b[i]);
}
