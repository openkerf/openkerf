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

	#pending = false;

	get elements() {
		return this.design?.elements ?? [];
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
			if (response.ok) this.design = await response.json();
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
