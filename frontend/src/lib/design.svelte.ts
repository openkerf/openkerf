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
	/**
	 * Hoe de vorm staat: de hoek in graden binnen [0, 360) en of hij
	 * gespiegeld is. Komt uit de matrix van de engine, dus het is de stand van
	 * het document en geen optelsom van wat het paneel toevallig gestuurd
	 * heeft. Null als de matrix niets prijsgeeft.
	 */
	pose: { angle_deg: number; mirrored: boolean } | null;
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

/**
 * Wat een paletkleur op deze machine het laatst deed (besluit B2).
 *
 * Let op het verschil met een preset: dit hangt aan machine + kleur en draagt
 * geen herkomst. Een preset hangt aan machine + materiaal + dikte en zegt dat
 * er ooit iets gebrand is. De UI moet dat uit elkaar houden, want gewoonte is
 * geen bewijs.
 */
export type PaletteMemory = {
	speed_mm_s?: number;
	power_percent?: number;
	type?: string;
	machine_name?: string;
	updated_at?: string;
};

export type PaletteInfo = {
	machine: { key: string; name: string | null };
	default_color: string | null;
	colors: { color: string; memory: PaletteMemory | null }[];
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

/**
 * Een laagkleur leesbaar houden op het bed waar hij op ligt.
 *
 * De meeste geïmporteerde tekeningen zijn zwart. Op het donkere bed is zwart op
 * zwart, en dan zie je de omtrek van je eigen werkstuk niet meer. Een andere
 * kleur kiezen mag niet — de laagkleur is van de gebruiker — dus schuiven we
 * dezelfde kleur op in helderheid tot hij loskomt van de achtergrond. Zwart
 * wordt grijs, donkerblauw wordt blauw; de laag blijft herkenbaar.
 *
 * De drempel is 3,0 en niet lager: een lijn op het bed is een grafisch object,
 * en WCAG 1.4.11 vraagt daar 3:1 voor. Op 2,6 kwamen precies de kleuren
 * ongemoeid door die het probleem zijn — paars (--layer-7) haalt 2,78 op het
 * donkere bed en oranje 2,97 op het lichte, en die werden dus níet bijgesteld
 * terwijl ze onder de norm zitten.
 */
const DREMPEL = 3.0;

function ontleed(kleur: string): [number, number, number] | null {
	const hex = kleur.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
	if (hex) {
		const h = hex[1];
		const breed = h.length === 3 ? h.split('').map((c) => c + c) : h.match(/../g)!;
		return breed.map((c) => parseInt(c, 16)) as [number, number, number];
	}
	const rgb = kleur.match(/rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i);
	if (rgb) return [+rgb[1], +rgb[2], +rgb[3]];
	return null;
}

function helderheid([r, g, b]: [number, number, number]) {
	const k = [r, g, b].map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
}

function verschil(a: [number, number, number], b: [number, number, number]) {
	const la = helderheid(a);
	const lb = helderheid(b);
	return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** De bedkleur van het actieve thema, opnieuw gelezen zodra dat wisselt. */
let bedKleur: { thema: string; rgb: [number, number, number] } | null = null;

function bed(): [number, number, number] | null {
	if (typeof window === 'undefined') return null;
	const thema = document.documentElement.dataset.theme ?? '';
	if (bedKleur?.thema === thema) return bedKleur.rgb;
	const rgb = ontleed(getComputedStyle(document.documentElement).getPropertyValue('--bed'));
	if (!rgb) return null;
	bedKleur = { thema, rgb };
	return rgb;
}

export function leesbaar(kleur: string): string {
	const ondergrond = bed();
	const eigen = ontleed(kleur);
	if (!ondergrond || !eigen) return kleur;
	if (verschil(eigen, ondergrond) >= DREMPEL) return kleur;
	// Weg van het bed: op een donker bed naar wit, op een licht bed naar zwart.
	const pool = helderheid(ondergrond) < 0.2 ? 255 : 0;
	for (let deel = 15; deel <= 75; deel += 5) {
		const f = deel / 100;
		const gemengd = eigen.map((c) => c + (pool - c) * f) as [number, number, number];
		if (verschil(gemengd, ondergrond) >= DREMPEL) {
			return `rgb(${gemengd.map((c) => Math.round(c)).join(' ')})`;
		}
	}
	return pool === 255 ? 'rgb(235 235 235)' : 'rgb(30 30 30)';
}

/**
 * De inkt die op een laagkleur past — zwart of wit, wat het verst weg staat.
 *
 * Het nummer op een laagchip stond vast op --on-color, dus altijd wit. Op geel
 * (--layer-3) is dat 1,58:1 en dan lees je het cijfer domweg niet. Voor acht
 * van de tien laagkleuren wint zwart, voor paars en bruin wint wit; die keuze
 * hangt aan de kleur en niet aan het thema, want de chip toont de laagkleur in
 * beide thema's ongewijzigd.
 */
export function inktOp(kleur: string): string {
	const eigen = ontleed(kleur);
	if (!eigen) return 'var(--on-color)';
	const wit = verschil(eigen, [255, 255, 255]);
	const zwart = verschil(eigen, [0, 0, 0]);
	return wit >= zwart ? 'var(--on-color)' : 'var(--void)';
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

	/**
	 * Het actieve thema, als reactieve waarde.
	 *
	 * Lijnkleuren worden tegen de bedkleur afgewogen (zie `leesbaar`), en die
	 * verandert bij het omschakelen. CSS-variabelen wisselen vanzelf mee, maar
	 * een kleur die wij hebben uitgerekend staat als vaste waarde in de DOM —
	 * zonder dit bleef het canvas na het omschakelen op de oude kleuren staan.
	 */
	theme = $state(typeof document === 'undefined' ? '' : (document.documentElement.dataset.theme ?? ''));

	constructor() {
		if (typeof document === 'undefined') return;
		new MutationObserver(() => {
			this.theme = document.documentElement.dataset.theme ?? '';
		}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
	}

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
		// Aanraken zodat Svelte deze kleur opnieuw uitrekent bij een themawissel.
		void this.theme;
		const operations = this.operations;
		const index = operations.findIndex((o) => o.id === operationId);
		if (index < 0) return 'var(--text-2)';
		const eigen = operations[index].color;
		const bruikbaar =
			eigen && !(/^#[0-9a-f]{6}0{2}$/i.test(eigen.trim()));
		return leesbaar(bruikbaar ? eigen : LAYER_COLORS[index % LAYER_COLORS.length]);
	}

	/**
	 * Lagen die je even niet wilt zien (besluit B4).
	 *
	 * "Zichtbaar" is iets anders dan "brandt mee". Een uitlijnkader dat je op
	 * het canvas houdt zonder het te branden, is een standaardtruc; met één
	 * schakelaar voor allebei kan dat niet. `output` staat in de engine en
	 * overleeft dus alles — dit is een kijkstand en blijft hier.
	 *
	 * Bewust niet bewaard in localStorage: laag-id's worden per document
	 * uitgedeeld en hergebruikt, dus een bewaarde lijst kan bij het volgende
	 * ontwerp de verkeerde laag onzichtbaar maken. Een verdwenen vorm zonder
	 * aanwijsbare reden is een erger kwaad dan opnieuw op het oog klikken.
	 */
	hiddenLayers = $state<string[]>([]);

	isLayerHidden(operationId: string) {
		return this.hiddenLayers.includes(operationId);
	}

	toggleLayer(operationId: string) {
		this.hiddenLayers = this.isLayerHidden(operationId)
			? this.hiddenLayers.filter((id) => id !== operationId)
			: [...this.hiddenLayers, operationId];
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
		/** Laag staat op "brandt niet mee": wel te zien, niet te branden. */
		dimmed: boolean;
		/** Vals als élke laag van dit element op onzichtbaar staat. */
		visible: boolean;
	} {
		const los = { color: 'var(--text-2)', dashed: true, dimmed: false, visible: true };
		const ids = element.operation_ids?.length
			? element.operation_ids
			: element.operation_id
				? [element.operation_id]
				: [];
		if (!ids.length) return los;
		const volgorde = this.operations;
		// De bovenste laag is de eerste in de boom, niet de eerste in de lijst
		// die het element toevallig meekreeg. Onzichtbare lagen tellen niet mee
		// voor de kleur: anders bepaalt een laag die je niet ziet hoe het eruit
		// ziet.
		let beste = -1;
		let bestaat = false;
		for (const id of ids) {
			const i = volgorde.findIndex((o) => o.id === id);
			if (i < 0) continue;
			bestaat = true;
			if (this.isLayerHidden(id)) continue;
			if (beste < 0 || i < beste) beste = i;
		}
		if (!bestaat) return los;
		// Wel in een laag, maar in geen enkele zichtbare: dan tekenen we hem niet.
		if (beste < 0) return { ...los, dashed: false, visible: false };
		return {
			color: this.colorFor(volgorde[beste].id),
			dashed: false,
			dimmed: !volgorde[beste].output,
			visible: true
		};
	}

	/** Loopt op bij elke herlaadslag; het canvas hangt hem aan afbeeldings-URL's
	 *  zodat een bewerkte afbeelding niet uit de browsercache komt. */
	revision = $state(0);

	/** Het palet met zijn geheugen; `null` zolang het nog niet geladen is. */
	palette = $state<PaletteInfo | null>(null);

	/** Wat deze kleur eerder deed, of niets als hij nog nooit gebruikt is. */
	memoryFor(color: string): PaletteMemory | null {
		const gezocht = color.trim().toLowerCase();
		return this.palette?.colors.find((c) => c.color === gezocht)?.memory ?? null;
	}

	/** De laag die deze kleur nu draagt, als er een is. */
	layerWithColor(color: string): DesignOperation | null {
		const gezocht = color.trim().toLowerCase();
		return (
			this.operations.find(
				(o) => !o.grid && (o.color ?? '').trim().toLowerCase() === gezocht
			) ?? null
		);
	}

	async loadPalette() {
		try {
			const response = await fetch('/api/design/palette');
			if (response.ok) this.palette = await response.json();
		} catch {
			// Geen geheugen is geen storing: de strook werkt ook zonder.
		}
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
				this.revision += 1;
				// Selecties die door een wijziging verdwenen zijn, laten we los;
				// id's die er nog zijn blijven staan.
				const alive = new Set(this.elements.map((e) => e.id));
				const kept = this.selectedIds.filter((id) => alive.has(id));
				if (kept.length !== this.selectedIds.length) this.selectedIds = kept;
				// Het geheugen loopt mee met de boom: een bijgestelde snelheid is
				// meteen wat die kleur "nu doet", ook in de strook onder het canvas.
				void this.loadPalette();
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
