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
	elements: DesignElement[];
	operations: DesignOperation[];
};

/** Vaste laagkleuren uit DESIGN-SYSTEM.md, gebruikt als een operatie er geen heeft. */
export const LAYER_COLORS = [
	'#E5484D',
	'#F76B15',
	'#FFC53D',
	'#46A758',
	'#12A594',
	'#0091FF',
	'#6E56CF',
	'#E93D82',
	'#8D6E63',
	'#607D8B'
];

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
	 * Let op: dit is de kleur van de *laagrij*, niet van het element op het
	 * canvas. In MeerK40t is de relatie many-to-many — één element kan in
	 * meerdere operaties zitten (de engine classificeert automatisch op kleur),
	 * dus "de kleur van de laag waar dit element in zit" bestaat niet. Het
	 * canvas tekent daarom op de eigen streekkleur van het element, net als de
	 * scene van MeerK40t zelf.
	 */
	colorFor(operationId: string | null): string {
		const operations = this.operations;
		const index = operations.findIndex((o) => o.id === operationId);
		if (index < 0) return 'var(--text-2)';
		return operations[index].color ?? LAYER_COLORS[index % LAYER_COLORS.length];
	}

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
