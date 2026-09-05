/**
 * The design as the canvas draws it.
 *
 * Geometry arrives in the engine's internal unit (Tat, 65535 per inch) as SVG
 * path data. Converting it would mean rewriting path strings; instead the canvas
 * scales once with `units_per_mm`.
 */

/**
 * What a shape is called in the app.
 *
 * The engine gives it a label like "Rect meerk40t:5 #0000ff": the type, the
 * internal id and the stroke colour. That is how it appeared in the panel, and it
 * did not fit — you read "Rect meerk40t:5 #00…". It also says nothing you cannot
 * already see, and the two things it *does* give away (an internal id, a colour
 * that is not the layer colour) are exactly the two things a user does not need to
 * know.
 *
 * What a shape is called here: what it *is*, and for text what it says.
 */
import { t, type MessageKey } from './i18n/core.ts';
import type { CurrentProject } from './projects.svelte.ts';

const KINDS: Record<string, MessageKey> = {
	'elem rect': 'shape.rect',
	'elem ellipse': 'shape.ellipse',
	'elem circle': 'shape.circle',
	'elem line': 'shape.line',
	'elem polyline': 'shape.polyline',
	'elem path': 'shape.path',
	'elem point': 'shape.point',
	'elem text': 'shape.text',
	'elem image': 'shape.image',
	group: 'shape.group'
};

export function elementName(element: {
	type: string;
	text: { text: string } | null;
	image?: unknown;
	label?: string;
}): string {
	if (element.text?.text) {
		const short = element.text.text.trim();
		return t('shape.textNamed', {
			text: short.length > 22 ? short.slice(0, 21) + '…' : short
		});
	}
	if (element.image) return t('shape.image');
	const kind = KINDS[element.type];
	if (kind) return t(kind);
	// Unknown type: the engine's label is better than nothing then, but without the
	// internal id and the colour code behind it.
	const clean = (element.label ?? element.type)
		.replace(/\s*(meerk40t:\d+|#[0-9a-f]{3,8})/gi, '')
		.trim();
	return clean || element.type;
}

export type DesignElement = {
	id: string;
	type: string;
	label: string;
	hidden: boolean;
	/** Locked in the engine's own node flag: no moving, sizing or deleting. */
	locked?: boolean;
	stroke: string | null;
	fill: string | null;
	bounds: [number, number, number, number] | null;
	path: string;
	/**
	 * How many loose pieces the shape consists of. A CAD export is often one path
	 * with dozens of panels in it; more than 1 means splitting does something.
	 */
	subpaths: number;
	/** The group this element is in; a grid is one group. */
	group_id: string | null;
	/** Set for vector text: the source the path was rendered from. */
	text: {
		text: string;
		font: string;
		font_size_mm: number | null;
		spacing: number;
		align: 'start' | 'middle' | 'end' | string;
	} | null;
	/** Set for a line: the two end points, because a line is not a box. */
	line: { x1_mm: number; y1_mm: number; x2_mm: number; y2_mm: number } | null;
	/** Set for an image: frame and resolution. */
	image: {
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
		pixels: [number, number] | null;
		dpi: number | null;
	} | null;
	/** The hatch or wobble this element is part of. */
	effect: { id: string | null; type: string; label: string } | null;
	/**
	 * How the shape sits: the angle in degrees within [0, 360) and whether it is
	 * mirrored. It comes from the engine's matrix, so it is the state of the
	 * document and not a running total of what the panel happened to send. Null when
	 * the matrix gives nothing away.
	 */
	pose: { angle_deg: number; mirrored: boolean } | null;
	/**
	 * The bridges (tabs) that keep this part in the sheet: small gaps left in the
	 * cut. `null` for a shape whose type carries none — a line, a point, text, an
	 * image — so the panel can say that instead of offering a field that does
	 * nothing.
	 *
	 * `path` is the contour with the gaps already cut out, in the same native units
	 * as `path`, and empty when there are no bridges. The canvas strokes that one
	 * and keeps `path` for the fill and the hit zone.
	 */
	bridges: {
		count: number;
		length_mm: number;
		positions_percent: number[];
		path_length_mm: number;
		path: string;
	} | null;
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
	/** Only meaningful on grid and image layers. */
	dpi: number | null;
	overscan: string | null;
	bidirectional: boolean;
	/** Air assist during this layer (decision B11). */
	air_assist: boolean;
	/** How far the Z axis drops per pass, in mm. `null` is off. */
	z_step_mm: number | null;
	output: boolean;
	element_ids: string[];
	/** Set when this layer is a cell of a test grid. */
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
	/** Are there changes since the last save or open? */
	dirty: boolean;
	/** The project this design would save as — `null` for one that has never been
	 *  saved on this server. See `ProjectsStore.follow` in `$lib/projects.svelte`,
	 *  which every surface naming the open project reads from. */
	project?: CurrentProject | null;
	elements: DesignElement[];
	operations: DesignOperation[];
};

/**
 * What a palette colour last did on this machine (decision B2).
 *
 * Note the difference from a preset: this hangs on machine + colour and carries no
 * provenance. A preset hangs on machine + material + thickness and says something
 * was once burned. The UI has to keep those apart, because habit is not
 * evidence.
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

/** Fixed layer colours from DESIGN-SYSTEM.md, used when an operation has none. */
export const LAYER_COLORS = readLayerColors();

/**
 * The layer colours come from tokens.css, so that canvas and panel read the same
 * source — which is what the design system prescribes. Outside the browser (during
 * the build) it falls back to the series as it stands there.
 */
function readLayerColors(): string[] {
	// @tokens-mirror: an exact mirror of --layer-1..10 in tokens.css. Only in use
	// during the build, when there is no document to read from.
	const fallback = [
		'#E5484D', '#F76B15', '#FFC53D', '#0F9B32', '#12A594',
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
 * Keeping a layer colour readable on the bed it lies on.
 *
 * Most imported drawings are black. On the dark bed that is black on black, and
 * then you can no longer see the outline of your own workpiece. Choosing a
 * different colour is not allowed — the layer colour belongs to the user — so we
 * shift the same colour in luminance until it comes loose from the background.
 * Black becomes grey, dark blue becomes blue; the layer stays recognisable.
 *
 * The threshold is 3.0 and no lower: a line on the bed is a graphical object, and
 * WCAG 1.4.11 asks 3:1 for that. At 2.6 exactly the colours that are the problem
 * came through untouched — purple (--layer-7) gets 2.78 on the dark bed and orange
 * 2.97 on the light one, so those were *not* adjusted while sitting under the
 * norm.
 */
const THRESHOLD = 3.0;

function parseColour(colour: string): [number, number, number] | null {
	const hex = colour.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
	if (hex) {
		const h = hex[1];
		const wide = h.length === 3 ? h.split('').map((c) => c + c) : h.match(/../g)!;
		return wide.map((c) => parseInt(c, 16)) as [number, number, number];
	}
	const rgb = colour.match(/rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i);
	if (rgb) return [+rgb[1], +rgb[2], +rgb[3]];
	return null;
}

function luminance([r, g, b]: [number, number, number]) {
	const k = [r, g, b].map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
}

function contrast(a: [number, number, number], b: [number, number, number]) {
	const la = luminance(a);
	const lb = luminance(b);
	return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The bed colour of the active theme, read again as soon as that switches. */
let bedColour: { theme: string; rgb: [number, number, number] } | null = null;

function bed(): [number, number, number] | null {
	if (typeof window === 'undefined') return null;
	const theme = document.documentElement.dataset.theme ?? '';
	if (bedColour?.theme === theme) return bedColour.rgb;
	const rgb = parseColour(getComputedStyle(document.documentElement).getPropertyValue('--bed'));
	if (!rgb) return null;
	bedColour = { theme, rgb };
	return rgb;
}

/**
 * Remember the outcome per colour and theme.
 *
 * This function runs once per element per redraw, and again for *everything* on a
 * theme switch. On five thousand paths that cost 145 ms — over the stopwatch bound,
 * and visible as a stutter. The outcome depends only on the colour and the bed
 * colour, and a design has a handful of different layer colours at most, so
 * remembering saves nearly all the work. The key carries the theme, so a switch
 * does not hand back the old value.
 */
const remembered = new Map<string, string>();

export function readable(colour: string): string {
	const theme = typeof document === 'undefined' ? '' : (document.documentElement.dataset.theme ?? '');
	const key = `${theme}|${colour}`;
	const known = remembered.get(key);
	if (known !== undefined) return known;
	const outcome = computeReadable(colour);
	// A design has a handful of colours; this bound is only here so a pathological
	// case does not eat the memory.
	if (remembered.size < 512) remembered.set(key, outcome);
	return outcome;
}

function computeReadable(colour: string): string {
	const background = bed();
	const own = parseColour(colour);
	if (!background || !own) return colour;
	if (contrast(own, background) >= THRESHOLD) return colour;
	// Away from the bed: towards white on a dark bed, towards black on a light one.
	const pool = luminance(background) < 0.2 ? 255 : 0;
	for (let part = 15; part <= 75; part += 5) {
		const f = part / 100;
		const mixed = own.map((c) => c + (pool - c) * f) as [number, number, number];
		if (contrast(mixed, background) >= THRESHOLD) {
			return `rgb(${mixed.map((c) => Math.round(c)).join(' ')})`;
		}
	}
	return pool === 255 ? 'rgb(235 235 235)' : 'rgb(30 30 30)';
}

/**
 * The ink that suits a layer colour — black or white, whichever is furthest away.
 *
 * The number on a layer chip was fixed at --on-color, so always white. On yellow
 * (--layer-3) that is 1.58:1 and then you simply cannot read the digit. For eight
 * of the ten layer colours black wins, for purple and brown white does; that choice
 * hangs on the colour and not on the theme, because the chip shows the layer colour
 * unchanged in both themes.
 */
/**
 * Is there nothing here that will burn?
 *
 * The question the app means by "empty", and it is not `elements.length === 0`:
 * shapes can lie on the bed with every layer switched off, or all of them in a layer
 * that does not go along. The top bar asked it that first way and the Job panel asked
 * the estimate (`parts === 0`), while the comment above both calls to `jobPhase` said
 * they were the same source. On a bed with the layers off, one said "ready" and the
 * other "nothing".
 *
 * Asked of the design rather than of the estimate, so it needs nothing fetched and
 * cannot change its mind halfway through a recalculation.
 */
export function burnsNothing(
	operations: { output: boolean; element_ids: string[] }[]
): boolean {
	return !operations.some((op) => op.output && op.element_ids.length > 0);
}

/**
 * The colours the strip under the canvas shows.
 *
 * The palette first, in its own order — those ten are what you draw in — and behind
 * it every layer colour the palette does not know. An imported SVG brings its own
 * colours, and a layer in one of those had no swatch at all while the swatches beside
 * it were carrying layer numbers and speeds. A strip that says which layer it is
 * about may not leave a layer out.
 *
 * The cells of a test grid are left out on purpose: they are layers in the engine,
 * but not layers you draw in.
 */
export function stripColours(
	palette: string[],
	operations: { color?: string | null; grid?: unknown }[]
): string[] {
	const shown = palette.map((c) => c.trim().toLowerCase());
	const seen = new Set(shown);
	for (const op of operations) {
		if (op.grid) continue;
		const colour = (op.color ?? '').trim().toLowerCase();
		if (!colour || seen.has(colour)) continue;
		seen.add(colour);
		shown.push(colour);
	}
	return shown;
}

export function inkOn(colour: string): string {
	const own = parseColour(colour);
	if (!own) return 'var(--on-color)';
	const white = contrast(own, [255, 255, 255]);
	const black = contrast(own, [0, 0, 0]);
	return white >= black ? 'var(--on-color)' : 'var(--void)';
}

/**
 * The layer number as it appears everywhere in the app (gap J7).
 *
 * One source, because this number occurs in three places: the chip in the layer
 * list, the label beside the shape on the canvas and the chip in the preflight. If
 * those drifted, the safety net for colour blindness would point at the wrong layer
 * — worse than no number.
 */
export function layerNumber(
	design: { operations?: DesignOperation[] } | null | undefined,
	operationId: string | null | undefined
): number | null {
	if (!design?.operations || !operationId) return null;
	const index = design.operations.filter((o) => !o.grid).findIndex((o) => o.id === operationId);
	return index < 0 ? null : index + 1;
}

/** Does this bounding box (in mm) stick out of a frame of `width × height`? */
export function outsideFrame(
	box: { x: number; y: number; width: number; height: number },
	frame: { width: number; height: number },
	slack = 0.5
): boolean {
	return (
		box.x < -slack ||
		box.y < -slack ||
		box.x + box.width > frame.width + slack ||
		box.y + box.height > frame.height + slack
	);
}

/** The bridges the selection has, as one answer. */
export type BridgeSummary = {
	/** Does at least one shape in the selection carry bridges at all? */
	carries: boolean;
	/** Does every shape that can carry them have them? */
	has: boolean;
	/** Do the shapes disagree about their bridges? Then a number typed here levels them. */
	mixed: boolean;
	/** The count and length they agree on, or the default when there are none yet. */
	count: number;
	lengthMm: number;
	/**
	 * The shortest contour in the selection, in millimetres.
	 *
	 * The shortest one, because that is the shape the API's bound trips over first: the
	 * bridges may take at most half the path, and refusing is per shape.
	 */
	shortestMm: number;
	/** How many shapes in the selection can carry bridges at all. */
	shapes: number;
	/**
	 * Do those shapes all have the same contour length?
	 *
	 * The read-back sentence binds on the shortest contour, which is right — that is the
	 * one the API's bound trips over first — but it may then only claim to be about *one*
	 * shape when they are all the same size. Measured with a 200 mm rectangle and a
	 * 125.7 mm circle selected: the sentence said "a contour of 125.7 mm" and the
	 * rectangle went unmentioned.
	 */
	sameContour: boolean;
	/**
	 * The explicit places, when there is one shape and its bridges are not simply spread
	 * evenly. `null` for the even spread — then the count says everything and a list of
	 * percentages would only be noise.
	 */
	places: number[] | null;
};

/** The default bridge, the same one the API and the menu row use: four of two millimetres. */
export const DEFAULT_BRIDGES = { count: 4, lengthMm: 2 };

export function bridgeSummary(elements: DesignElement[]): BridgeSummary {
	const carriers = elements.map((element) => element.bridges).filter(Boolean) as NonNullable<
		DesignElement['bridges']
	>[];
	if (!carriers.length)
		return {
			carries: false,
			has: false,
			mixed: false,
			count: DEFAULT_BRIDGES.count,
			lengthMm: DEFAULT_BRIDGES.lengthMm,
			shortestMm: 0,
			shapes: 0,
			sameContour: true,
			places: null
		};

	const withBridges = carriers.filter((b) => b.count > 0);
	const first = withBridges[0] ?? null;
	const mixed =
		withBridges.length !== carriers.length ||
		carriers.some(
			(b) => b.count !== carriers[0].count || Math.abs(b.length_mm - carriers[0].length_mm) > 0.001
		);

	// One shape, and its places are not the even spread the count would give: then the
	// panel shows the places, because the count alone would be a lie about where they are.
	let places: number[] | null = null;
	if (carriers.length === 1 && first) {
		const even = Array.from(
			{ length: first.count },
			(_, i) => Math.round(((i + 0.5) * 100) / first.count * 10000) / 10000
		);
		const same = first.positions_percent.every((v, i) => Math.abs(v - even[i]) < 0.01);
		if (!same) places = first.positions_percent;
	}

	return {
		carries: true,
		has: withBridges.length > 0,
		mixed,
		count: first?.count ?? DEFAULT_BRIDGES.count,
		lengthMm: first?.length_mm ?? carriers[0].length_mm ?? DEFAULT_BRIDGES.lengthMm,
		shortestMm: Math.min(...carriers.map((b) => b.path_length_mm)),
		shapes: carriers.length,
		// A tenth of a millimetre, because that is the precision the sentence prints in: two
		// contours that round to the same number are the same contour to the reader.
		sameContour: carriers.every(
			(b) => Math.abs(b.path_length_mm - carriers[0].path_length_mm) < 0.05
		),
		places
	};
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
	 * A preview while dragging, in mm. The canvas writes it, the top bar and status
	 * bar read it — that is how the coordinates keep up while you drag, without a
	 * command going to the engine per mouse move.
	 */
	preview = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	/** Set by the page to make the URL follow the selection. */
	onSelect: ((ids: string[]) => void) | null = null;

	/**
	 * The active theme, as a reactive value.
	 *
	 * Stroke colours are weighed against the bed colour (see `readable`), and that
	 * changes when the theme is switched. CSS variables switch along by themselves,
	 * but a colour we have computed sits in the DOM as a fixed value — without this
	 * the canvas kept the old colours after a switch.
	 */
	theme = $state(typeof document === 'undefined' ? '' : (document.documentElement.dataset.theme ?? ''));

	constructor() {
		if (typeof document === 'undefined') return;
		new MutationObserver(() => {
			this.theme = document.documentElement.dataset.theme ?? '';
		}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
	}

	#pending = false;
	/** The re-entry lock of `load()`; deliberately not `$state` — see load(). */
	#busy = false;

	get elements() {
		return this.design?.elements ?? [];
	}

	/** Are there unsaved changes? */
	get dirty() {
		return this.design?.dirty ?? false;
	}

	get isEmpty() {
		return this.elements.length === 0;
	}

	/** Nothing that will burn — see `burnsNothing`. Not the same as `isEmpty`. */
	get burnsNothing() {
		return burnsNothing(this.operations);
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
	 * A group is one thing. Click a member and you get the whole group — otherwise
	 * you drag a single square out of a test grid.
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
	 * Several elements at once, from a drag box for instance.
	 *
	 * Not select() followed by toggle(): the second would immediately remove a group
	 * the first had just added, which made a drag box over a group look as if it
	 * selected nothing.
	 */
	selectMany(ids: string[]) {
		const expanded = new Set<string>();
		for (const id of ids) this.#expand(id).forEach((member) => expanded.add(member));
		const next = [...expanded];
		if (same(next, this.selectedIds)) return;
		this.selectedIds = next;
		this.onSelect?.(this.selectedIds);
	}

	/** Shift-click: add, or take away again. */
	toggle(id: string) {
		const members = this.#expand(id);
		const inside = members.every((m) => this.selectedIds.includes(m));
		this.selectedIds = inside
			? this.selectedIds.filter((x) => !members.includes(x))
			: [...this.selectedIds, ...members.filter((m) => !this.selectedIds.includes(m))];
		this.onSelect?.(this.selectedIds);
	}

	/** What the user sees right now: the drag preview, otherwise the selection. */
	get liveBox() {
		return this.preview ?? this.selectedSize;
	}

	/**
	 * The bounding box of the whole selection in mm. With several elements that is
	 * the joint box — exactly what the engine works on during a resize too.
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
	 * The colour per operation: its own, otherwise a fixed layer colour in order.
	 *
	 * The engine sometimes hands over a colour with alpha (`#0000ff00`, fully
	 * transparent) for an operation that was never drawn. That is unusable as a layer
	 * colour — then we take the palette colour in order.
	 */
	colorFor(operationId: string | null): string {
		// Touched so Svelte recomputes this colour on a theme switch.
		void this.theme;
		const operations = this.operations;
		const index = operations.findIndex((o) => o.id === operationId);
		if (index < 0) return 'var(--text-2)';
		const own = operations[index].color;
		const usable = own && !/^#[0-9a-f]{6}0{2}$/i.test(own.trim());
		return readable(usable ? own : LAYER_COLORS[index % LAYER_COLORS.length]);
	}

	/**
	 * Layers you do not want to see for a moment (decision B4).
	 *
	 * "Visible" is something other than "burns along". Keeping an alignment box on
	 * the canvas without burning it is a standard trick; with one switch for both
	 * that is impossible. `output` lives in the engine and therefore survives
	 * everything — this is a way of looking and stays here.
	 *
	 * Deliberately not kept in localStorage: layer ids are handed out per document
	 * and reused, so a stored list could make the wrong layer invisible in the next
	 * design. A shape that has vanished for no visible reason is a worse evil than
	 * clicking the eye again.
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
	 * How an element is drawn on the bed.
	 *
	 * In MeerK40t one element can sit in more than one operation (the engine
	 * classifies automatically by colour). So "the layer" strictly speaking does not
	 * exist — which is why the topmost one counts, as with overlapping layers in any
	 * other drawing program.
	 *
	 * An element without a layer is drawn dotted grey: that is not a missing colour
	 * but a warning. Such a shape does not get burned.
	 */
	strokeFor(element: {
		operation_ids?: string[];
		operation_id?: string | null;
		fill?: string | null;
	}): {
		color: string;
		dashed: boolean;
		/** The layer is set to "does not burn": visible, but not burned. */
		dimmed: boolean;
		/** False when *every* layer of this element is set to hidden. */
		visible: boolean;
		/**
		 * The shape is burned as an area, not as a line (gap R1).
		 *
		 * Where on a cut or engrave layer the head follows the contour, a grid
		 * layer sweeps the *area* away. Showing that as an outline is not merely less
		 * pretty — it is a different result from what comes out of the machine.
		 *
		 * Two conditions, because both decide what burns: the layer has to be a grid
		 * layer *and* the shape has to have a fill. A shape without a fill burns only
		 * its outline in a grid layer too — measured in
		 * `test_an_unfilled_shape_burns_its_outline_and_not_its_middle` — so that one
		 * stays a line here.
		 */
		filled: boolean;
	} {
		const loose = {
			color: 'var(--text-2)',
			dashed: true,
			dimmed: false,
			visible: true,
			filled: false
		};
		const ids = element.operation_ids?.length
			? element.operation_ids
			: element.operation_id
				? [element.operation_id]
				: [];
		if (!ids.length) return loose;
		const order = this.operations;
		// The topmost layer is the first in the tree, not the first in the list the
		// element happened to be given. Hidden layers do not count towards the colour:
		// otherwise a layer you cannot see decides how it looks.
		let best = -1;
		let exists = false;
		for (const id of ids) {
			const i = order.findIndex((o) => o.id === id);
			if (i < 0) continue;
			exists = true;
			if (this.isLayerHidden(id)) continue;
			if (best < 0 || i < best) best = i;
		}
		if (!exists) return loose;
		// In a layer, but in no visible one: then we do not draw it.
		if (best < 0) return { ...loose, dashed: false, visible: false };
		return {
			color: this.colorFor(order[best].id),
			dashed: false,
			dimmed: !order[best].output,
			visible: true,
			filled: order[best].type === 'op raster' && Boolean(element.fill)
		};
	}

	/** Goes up on every reload; the canvas hangs it on image URLs so that an edited
	 *  image does not come out of the browser cache. */
	revision = $state(0);

	/** The palette with its memory; `null` as long as it has not loaded yet. */
	palette = $state<PaletteInfo | null>(null);

	/**
	 * What a layer can do on *this* machine (decision B11).
	 *
	 * Only what the driver knows reaches the screen — the same rule as with the Z
	 * axis. Everything off by default: better a switch that is briefly absent than a
	 * switch that does nothing.
	 */
	layerCapabilities = $state<{ air_assist: boolean; z_step: boolean }>({
		air_assist: false,
		z_step: false
	});

	async loadCapabilities() {
		try {
			const response = await fetch('/api/design/capabilities');
			if (response.ok) this.layerCapabilities = await response.json();
		} catch {
			// Unreachable is not the same as "cannot do it", but the screen has to show
			// something — and then rather nothing than a dead switch.
		}
	}

	/** The layer number as the chip shows it; see `layerNumber` (gap J7). */
	numberFor(operationId: string | null): number | null {
		return layerNumber(this.design, operationId);
	}

	/** What this colour did before, or nothing when it has never been used. */
	memoryFor(color: string): PaletteMemory | null {
		const wanted = color.trim().toLowerCase();
		return this.palette?.colors.find((c) => c.color === wanted)?.memory ?? null;
	}

	/** The layer that carries this colour now, if there is one. */
	layerWithColor(color: string): DesignOperation | null {
		const wanted = color.trim().toLowerCase();
		return (
			this.operations.find(
				(o) => !o.grid && (o.color ?? '').trim().toLowerCase() === wanted
			) ?? null
		);
	}

	async loadPalette() {
		try {
			const response = await fetch('/api/design/palette');
			if (response.ok) this.palette = await response.json();
		} catch {
			// No memory is not a fault: the strip works without it too.
		}
	}

	async load() {
		// Signals arrive in bursts; one reload per burst is enough.
		//
		// The lock is deliberately *not* `$state`. It used to be `this.loading`, and
		// that turned every `$effect` calling load() into a loop: the effect reads
		// `loading` as a dependency, load() sets it to true, the effect is thereby
		// invalidated and calls again — and once it goes back to false, once more. One
		// drawn shape was enough to start it, and after that it never stopped: measured
		// 300 to 430 requests per second to /api/design, even after the work had been
		// thrown away again. A plain field is not tracked and breaks the circle.
		// Measurement: `node gauntlet/canvas-lus.mjs`.
		if (this.#busy) {
			this.#pending = true;
			return;
		}
		this.#busy = true;
		this.loading = true;
		try {
			const response = await fetch('/api/design');
			if (response.ok) {
				this.design = await response.json();
				this.revision += 1;
				// Selections that a change made disappear are let go; ids that are still
				// there stay.
				const alive = new Set(this.elements.map((e) => e.id));
				const kept = this.selectedIds.filter((id) => alive.has(id));
				if (kept.length !== this.selectedIds.length) this.selectedIds = kept;
				// The memory follows the tree: an adjusted speed is at once what that
				// colour "does now", including in the strip under the canvas.
				void this.loadPalette();
				// And what the machine can do: switching machines changes which switches
				// belong in a layer row (decision B11).
				void this.loadCapabilities();
			}
		} catch {
			// No connection card: the status bar already reports that; do nothing here.
		} finally {
			this.#busy = false;
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
