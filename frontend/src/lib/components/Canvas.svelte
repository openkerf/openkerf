<script lang="ts">
	import { currentJob } from '$lib/api';
	import type { Device } from '$lib/api';
	import { headTrail } from '$lib/status.svelte';
	import { origin } from '$lib/control.svelte';
	import { elementName, type DesignStore } from '$lib/design.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import type { TilingStore, Tile } from '$lib/tiling.svelte';
	import LayerPalette from './LayerPalette.svelte';
	import Menu from './Menu.svelte';
	import type { Menu as MenuList } from '$lib/actions';
	import {
		surroundingTargets,
		snapBox,
		snapPoint,
		SNAP_LABEL,
		type SnapGuide
	} from '$lib/snapping';
	import { penPath, penPreview, HANDLE_THRESHOLD_PX, type PenPoint } from '$lib/pen';

	let {
		onPointerMm,
		device,
		design,
		edits,
		canEdit = false,
		tool = 'select',
		onEdited,
		onDrawn,
		onTextAt,
		cropping = $bindable(false),
		onCrop,
		onPath,
		cameraSrc = null,
		cameraOpacity = 0.6,
		sheet = null,
		sheetId = null,
		tiling = null,
		onContextObject,
		onContextCanvas,
		onContextNode,
		onDeeper,
		control = $bindable(null)
	}: {
		/** Where the pointer is, in mm on the bed. `null` when it is gone. */
		onPointerMm?: (point: { x: number; y: number } | null) => void;
		device: Device | null;
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		tool?: string;
		onEdited?: () => void;
		onDrawn?: (shape: Record<string, unknown>) => void;
		onTextAt?: (at: { x: number; y: number }) => void;
		/** On while cropping: the drag frame crops instead of selecting. */
		cropping?: boolean;
		onCrop?: (rect: { x: number; y: number; width: number; height: number }) => void;
		onPath?: (points: number[][], closed: boolean) => Promise<void> | void;
		/** Source of the camera image, or null when the camera is off. */
		cameraSrc?: string | null;
		cameraOpacity?: number;
		/** The active sheet: the piece of material inside the bed. */
		sheet?: { name: string; width: number; height: number } | null;
		/** The active sheet's id — needed to switch tiling on. */
		sheetId?: string | null;
		/** Tile division and running series — for the drawing and the offer as soon as
		 *  the sheet is bigger than the bed. */
		tiling?: TilingStore | null;
		/** Right-click on a shape. The canvas selects it first if it was not selected;
		 *  the page then decides what is in the menu. */
		onContextObject?: (event: MouseEvent, under: string[]) => void;
		/** Where you are in a pile of shapes after an Alt+click; null clears it again. */
		onDeeper?: (info: { index: number; total: number } | null) => void;
		/** Right-click on the bed itself, with the place in mm: the menu promises "paste
		 *  here", and then it has to know where "here" is. */
		onContextCanvas?: (event: MouseEvent, point: { x: number; y: number }) => void;
		/** Right-click on a node of the shape being edited. The canvas takes the node in
		 *  hand first; the page then builds the menu from `nodeMenu`. */
		onContextNode?: (event: MouseEvent, index: number) => void;
		/**
		 * Operating the view from outside.
		 *
		 * The zooming lives here — the scale, the pan and the measures of the work area
		 * are here — but it also belongs in the canvas context menu and in the shortcuts,
		 * and those are handled in the page. Instead of lifting that state upwards the
		 * canvas hands back a handle: one object with the four zoom states and the two
		 * switches.
		 */
		control?: {
			zoom: (what: 'all' | 'selection' | 'bed' | 'hundred') => void;
			step: (factor: number) => void;
			snap: () => void;
			layerNumbers: () => void;
			/** The node verbs, so the shortcuts in the page reach them: the node in hand
			 *  lives here, with the points it belongs to. */
			node: (verb: 'add' | 'remove' | 'curve' | 'corner') => void;
			/** Take back the last point of the line being drawn. */
			penBack: () => void;
			state: () => {
				snap: boolean;
				layerNumbers: boolean;
				/** Is the pen in the middle of a line? Then Delete and Escape are its. */
				penDrawing: boolean;
				/** Which node the node tool has in hand, or -1. */
				nodeIndex: number;
				nodeCount: number;
				nodeClosed: boolean;
				/** The kind of the segment after the node in hand, or null. */
				nodeKind: 'line' | 'quad' | 'cubic' | 'arc' | null;
			};
		} | null;
	} = $props();

	const FALLBACK = { width: 500, height: 300 };

	// Above the derivations that use it: the scale depends on the actual size of the
	// work area, not the other way round.
	let canvasWidth = $state(0);
	let canvasHeight = $state(0);

	let bed = $derived({
		width: device?.bed?.width_mm ?? FALLBACK.width,
		height: device?.bed?.height_mm ?? FALLBACK.height
	});

	/** Air between the bed and the edge of the work area, in screen pixels. */
	const MARGIN = 32;

	// Fitting means: the bed fills the work area that is there. A fixed 640px (which is
	// what used to be here) leaves two thirds unused on a wide screen and on a tablet
	// runs under the right-hand panel — the bed was cut off.
	let fitScale = $derived(
		Math.min(
			(Math.max(canvasWidth, 320) - MARGIN * 2) / bed.width,
			(Math.max(canvasHeight, 240) - MARGIN * 2) / bed.height
		)
	);
	let zoom = $state(1);
	let pan = $state({ x: 0, y: 0 });
	let scale = $derived(fitScale * zoom);

	/** Eén schermpixel, uitgedrukt in millimeters. */
	let mmPerPx = $derived(1 / scale);

	// Text in the bed SVG measures in millimetres, so a fixed size grows with the zoom:
	// zoom in ten times and a label becomes ten times as large and covers half the
	// workpiece. Converting back to a constant screen size is the only measure that
	// holds.
	let labelSize = $derived(11 / scale);

	// The same trap as with the label: a handle of "2.4" in an SVG that measures in
	// millimetres is 2.4 mm, so 5 px zoomed out and 50 px zoomed in. So everything you
	// have to hit with a mouse or a finger is converted back to screen pixels. Sizes in
	// px: handle 10, hit zone 24 (touch target), stem 16. With a finger 24 px is too
	// small; the design system demands a 44 px touch target on touch screens. The handle
	// itself stays just as small — you have to see it, not hit it.
	let grofAanwijzen = $state(false);
	$effect(() => {
		if (typeof window === 'undefined' || !window.matchMedia) return;
		const ask = window.matchMedia('(pointer: coarse)');
		grofAanwijzen = ask.matches;
		const luister = () => (grofAanwijzen = ask.matches);
		ask.addEventListener('change', luister);
		return () => ask.removeEventListener('change', luister);
	});

	let handleR = $derived(5 * mmPerPx);
	let hitR = $derived((grofAanwijzen ? 22 : 12) * mmPerPx);
	let stalk = $derived((grofAanwijzen ? 26 : 16) * mmPerPx);

	function zoomAt(factor: number, clientX?: number, clientY?: number) {
		const next = Math.min(20, Math.max(0.2, zoom * factor));
		if (next === zoom) return;
		if (clientX !== undefined && clientY !== undefined && frame) {
			// Keep the point under the cursor in place. That needs the distance to the
			// *centre of the bed*, because everything grows around it. It used to be the
			// distance to the corner of the canvas area, and that is half a canvas width
			// out: the point under the pointer ran away about 15 px per tick. Calculate
			// the centre rather than measuring it: on a run of wheel ticks the DOM is one
			// tick behind, and then every tick zooms to a point the previous tick had
			// already moved.
			const area = frame.getBoundingClientRect();
			const ratio = next / zoom;
			const dx = clientX - (area.left + RULER + canvasWidth / 2 + pan.x);
			const dy = clientY - (area.top + RULER + canvasHeight / 2 + pan.y);
			pan = { x: pan.x - dx * (ratio - 1), y: pan.y - dy * (ratio - 1) };
		}
		zoom = next;
	}

	/**
	 * One CSS millimetre is 96/25.4 pixels. That is the measure in which a browser works
	 * out `1mm`, so it is also the only sensible meaning of "100%" in a web app: a 10 mm
	 * line on the bed is then 10 mm on the screen.
	 *
	 * Before this the button was called 100% but did "fit the bed", and the number beside
	 * it was the zoom relative to *that* state. Two things were wrong there: 1:1 could not
	 * be reached, and 100% meant something other than everywhere else. Now the percentage
	 * is a real scale and "the whole bed" has a rule of its own.
	 */
	const PX_PER_MM = 96 / 25.4;

	/** The scale as a percentage of true size. */
	let procent = $derived(Math.round((scale / PX_PER_MM) * 100));

	/** The whole bed in view — the opening state. */
	function bedFit() {
		zoom = 1;
		pan = { x: 0, y: 0 };
	}

	/** True size: 1 mm on the bed is 1 mm on the screen. */
	function honderd() {
		naarProcent(100);
	}

	/** To a requested percentage, around the centre of the view. */
	function naarProcent(target: number) {
		const fresh = (target / 100) * (PX_PER_MM / fitScale);
		const factor = fresh / zoom;
		if (!Number.isFinite(factor) || factor <= 0) return;
		// Around the centre of the work area, not around the cursor: there is no cursor
		// when this comes from a menu or a shortcut.
		zoomAt(factor);
	}

	/**
	 * Bringing a rectangle in millimetres into view, filling it.
	 *
	 * The bed is centred in the area; the pan shifts that. To centre a region we work
	 * back which pan is needed for it at the new scale — otherwise the view jumps away as
	 * soon as you zoom in.
	 */
	function fitTo(x: number, y: number, w: number, h: number) {
		if (!canvasWidth || !canvasHeight || w <= 0 || h <= 0) return;
		// canvasWidth is the area *inside* the rulers; subtracting those again made
		// everything called "fitting" a notch too small.
		const target = Math.min(
			(canvasWidth - MARGIN * 2) / w,
			(canvasHeight - MARGIN * 2) / h
		);
		zoom = Math.min(20, Math.max(0.2, target / fitScale));

		// Centring on the calculated position did not hold: there is more between the
		// measuring point of `canvasWidth` and the top-left corner of the bed than the
		// ruler alone. Rather than recomputing that chain (and being wrong again at the
		// next layout change) we measure *after* drawing where the bed really is and
		// correct the difference in one step.
		requestAnimationFrame(() => {
			if (!frame) return;
			const area = frame.getBoundingClientRect();
			const bedvlak = frame.querySelector('.bed')?.getBoundingClientRect();
			if (!bedvlak) return;
			const perMm = bedvlak.width / bed.width;
			const midX = bedvlak.x + (x + w / 2) * perMm;
			const midY = bedvlak.y + (y + h / 2) * perMm;
			pan = {
				x: pan.x + (area.x + area.width / 2 - midX),
				y: pan.y + (area.y + area.height / 2 - midY)
			};
		});
	}

	/** Everything that is there, or the whole bed when there is nothing. */
	function passend() {
		const box = omvat(design.elements ?? []);
		if (box) fitTo(box.x, box.y, box.width, box.height);
		else fitTo(0, 0, bed.width, bed.height);
	}

	/**
	 * To the selection, and otherwise to everything.
	 *
	 * That fallback is not laziness but exactly what LightBurn's "Frame Selection" does:
	 * one key that always does something sensible, instead of a key that goes quiet as
	 * soon as nothing is selected.
	 */
	function naarSelectie() {
		const chosen = (design.elements ?? []).filter((e) => design.isSelected(e.id));
		const box = omvat(chosen);
		if (box) fitTo(box.x, box.y, box.width, box.height);
		else passend();
	}

	/** The bounding rectangle in mm of a collection of elements. */
	function omvat(elementen: { bounds: [number, number, number, number] | null }[]) {
		const perMm = design.design?.units_per_mm ?? 1;
		let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
		for (const e of elementen) {
			if (!e.bounds) continue;
			x0 = Math.min(x0, e.bounds[0] / perMm);
			y0 = Math.min(y0, e.bounds[1] / perMm);
			x1 = Math.max(x1, e.bounds[2] / perMm);
			y1 = Math.max(y1, e.bounds[3] / perMm);
		}
		if (!Number.isFinite(x0)) return null;
		// A single line has no width; give it something to fit into.
		return { x: x0, y: y0, width: Math.max(x1 - x0, 1), height: Math.max(y1 - y0, 1) };
	}

	/** Only the arrow picks shapes up; with a drawing tool in hand a click inside an
	 *  existing shape should simply draw. */
	let selectTool = $derived(tool === 'select' || tool === 'nodes');

	/** Tools that put something in a place; snapping belongs with those. */
	let tekengereedschap = $derived(
		tool === 'rect' || tool === 'circle' || tool === 'line' || tool === 'text' ||
			tool === 'point' || tool === 'pen' || tool === 'measure'
	);

	let frame = $state<HTMLElement | null>(null);
	let panning = $state<{ x: number; y: number; from: { x: number; y: number } } | null>(null);

	function startPan(event: PointerEvent) {
		panning = { x: event.clientX, y: event.clientY, from: { ...pan } };
		(event.target as Element).setPointerCapture?.(event.pointerId);
	}

	function movePan(event: PointerEvent) {
		if (!panning) return;
		pan = {
			x: panning.from.x + (event.clientX - panning.x),
			y: panning.from.y + (event.clientY - panning.y)
		};
	}

	/**
	 * Panning with the space bar.
	 *
	 * The middle button and Alt-dragging already did this, but the space bar is the grip
	 * everybody knows — LightBurn, Illustrator, Inkscape, Figma and Photoshop all five do
	 * it this way, and on a trackpad without a middle button it is the only one that works
	 * with one hand. Alt-dragging stays, because that is the grip that *also* inverts
	 * snapping and we do not want to take that away.
	 *
	 * As long as space is held the cursor is a hand and a left click drags the view
	 * instead of a selection frame.
	 */
	let space = $state(false);
	let head = $derived(device?.position.mm ?? null);
	let selection = $derived(design.selectedSize);
	/**
	 * Is everything in the selection locked?
	 *
	 * A locked shape keeps its outline — you must be able to see what you selected —
	 * but loses its handles and its drag surface. Leaving them there would let you
	 * drag a shape the API then refuses: the movement on screen and the refusal in the
	 * panel disagree for as long as it takes to let go, and the user believes the
	 * screen.
	 */
	let selectionLocked = $derived(
		design.selectedIds.length > 0 &&
			design.selectedIds.every((id) => design.elements.find((e) => e.id === id)?.locked)
	);

	// ── Progress on the canvas (gap J3) ───────────────────────────────────────
	//
	// The promise from DESIGN-SYSTEM v2 was that the contour draws itself while the
	// machine cuts it. What is needed for that — the order in which the engine works
	// through the shapes — comes out nowhere; we get a percentage and a stream of head
	// positions. So we draw what is measured and not what is pretty: the trail the head
	// really travelled (see `HeadTrail` in status.svelte.ts), plus the progress as a ring
	// *around* the head.
	//
	// What this deliberately does not do: pretend it is a kerf. The signal does not say
	// whether the laser was on, so the jump between two shapes is in it just the same.
	// Hence it is called a trail, it is one thin line and not in the layer colour, and
	// the strip under the canvas says in words what you are seeing.
	let job = $derived(currentJob(device));
	let progressPart = $derived.by(() => {
		if (!job) return null;
		const part = job.progress;
		if (part === null || part === undefined || !Number.isFinite(part)) return null;
		return Math.min(1, Math.max(0, part));
	});

	/** The trail in millimetres, ready to lay down as a polyline. */
	let trail = $derived.by(() => {
		if (!job) return '';
		const points = headTrail.points;
		if (points.length < 4) return '';
		const perMm = design.design?.units_per_mm ?? 1;
		const stukken = [];
		for (let i = 0; i < points.length; i += 2) {
			stukken.push(`${(points[i] / perMm).toFixed(2)},${(points[i + 1] / perMm).toFixed(2)}`);
		}
		return stukken.join(' ');
	});

	/**
	 * The last metre of the trail, at full strength: that is where it is happening now.
	 *
	 * Keep it short. With sixty points a rectangle lit up its whole outline — measured on
	 * the trial job — and then there is no difference left between "it has been here" and
	 * "it is here now", while that is precisely the only thing this piece adds.
	 */
	const FRESH_POINTS = 14;
	let spoorKop = $derived.by(() => {
		if (!job) return '';
		const points = headTrail.points;
		if (points.length < 4) return '';
		const perMm = design.design?.units_per_mm ?? 1;
		const from = Math.max(0, points.length - 2 * FRESH_POINTS);
		const stukken = [];
		for (let i = from; i < points.length; i += 2) {
			stukken.push(`${(points[i] / perMm).toFixed(2)},${(points[i + 1] / perMm).toFixed(2)}`);
		}
		return stukken.join(' ');
	});

	/** Radius and circumference of the progress ring, converted back to screen pixels. */
	const RING_PX = 13;
	let ringR = $derived(RING_PX * mmPerPx);
	let ringCircumference = $derived(2 * Math.PI * ringR);

	// ── The user's zero point (gap J12) ───────────────────────────────────────
	//
	// The zero point moves the work on its way to the machine. That must not live in a
	// panel alone: then you draw in one place and it burns in another, and that is exactly
	// the kind of surprise this feature is meant to prevent. So the bed carries the point
	// itself *and* a dotted frame where the work will land.
	$effect(() => {
		origin.laad();
	});
	let originPoint = $derived(origin.point);
	/** Where the work will lie: the bounding box, shifted by the zero point. */
	let burnsHere = $derived.by(() => {
		if (!originPoint || (!originPoint.x_mm && !originPoint.y_mm)) return null;
		const box = omvat(design.elements ?? []);
		if (!box) return null;
		return { ...box, x: box.x + originPoint.x_mm, y: box.y + originPoint.y_mm };
	});

	// Only with exactly one selected line: that one you edit by its points.
	let selectedLine = $derived(
		design.selectedIds.length === 1 ? (design.selected?.line ?? null) : null
	);
	let endpointDrag = $state<{ index: number } | null>(null);
	let lineHandles = $derived.by(() => {
		if (!selectedLine || !canEdit) return null;
		const live = endpointPreview ?? selectedLine;
		return [
			{ x: live.x1_mm, y: live.y1_mm },
			{ x: live.x2_mm, y: live.y2_mm }
		];
	});
	let endpointPreview = $state<
		{ x1_mm: number; y1_mm: number; x2_mm: number; y2_mm: number } | null
	>(null);

	function startEndpoint(event: PointerEvent, index: number) {
		if (!selectedLine) return;
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		endpointDrag = { index };
		endpointPreview = { ...selectedLine };
	}

	function moveEndpoint(event: PointerEvent) {
		if (!endpointDrag || !endpointPreview) return;
		const at = snapped(pointerMm(event, true), event);
		endpointPreview =
			endpointDrag.index === 0
				? { ...endpointPreview, x1_mm: at.x, y1_mm: at.y }
				: { ...endpointPreview, x2_mm: at.x, y2_mm: at.y };
	}

	async function endEndpoint() {
		const drag = endpointDrag;
		const target = endpointPreview;
		endpointDrag = null;
		endpointPreview = null;
		guides = [];
		if (!drag || !target || !design.selectedId) return;
		await edits.updateLine(design.selectedId, target);
		onEdited?.();
	}

	// Nodes: the points of the shape itself, not the bounding frame. They come from the
	// API because the engine keeps the shape as segments and a rectangle only gets points
	// once you turn it into a path.
	let nodePoints = $state<{ index: number; x_mm: number; y_mm: number }[]>([]);
	let nodeDrag = $state<{ index: number; x: number; y: number } | null>(null);

	/**
	 * The pieces between the points, which is where a curve actually lives.
	 *
	 * A control point belongs to a segment and not to a node — a quad keeps one, a cubic
	 * two — so without this list the tool could show a curve but never touch it.
	 */
	type Segment = {
		index: number;
		kind: 'line' | 'quad' | 'cubic' | 'arc';
		start: number;
		end: number;
		controls: { which: number; x_mm: number; y_mm: number }[];
	};
	let nodeSegments = $state<Segment[]>([]);
	let nodeClosed = $state(false);
	/** The node in hand. A verb needs to know *which* node, and clicking one is how you
	 *  say it; -1 means none. */
	let nodePicked = $state(-1);
	let controlDrag = $state<{ segment: number; which: number; x: number; y: number } | null>(
		null
	);

	/** The piece that leaves the node in hand — the one the verbs work on. */
	let segmentAfter = $derived(nodeSegments.find((s) => s.start === nodePicked) ?? null);
	/** The pieces the node in hand touches; only those show their handles, or a path of
	 *  fifty points would put a hundred squares on the bed at once. */
	let handleSegments = $derived(
		nodePicked < 0
			? []
			: nodeSegments.filter((s) => s.start === nodePicked || s.end === nodePicked)
	);
	/**
	 * Why there are no nodes on screen.
	 *
	 * The tool has three quiet states — nothing chosen, more than one thing chosen, and a
	 * shape the engine does not edit per point — and in all three nothing visible
	 * happened. The tool did look pressed. Measured with two shapes selected: the panel
	 * shows the ordinary multiple selection and the word "node" appears nowhere on
	 * screen. One line under the bed says where you are and what the next step is.
	 */
	let nodeReason = $state<'none' | 'many' | 'noPoints' | 'failed' | null>(null);

	$effect(() => {
		const id = tool === 'nodes' && design.selectedIds.length === 1 ? design.selectedId : null;
		// design.revision: after a change the points may have moved.
		void design.revision;
		if (!id) {
			nodePoints = [];
			nodeSegments = [];
			nodePicked = -1;
			nodeReason =
				tool !== 'nodes' ? null : design.selectedIds.length === 0 ? 'none' : 'many';
			return;
		}
		let cancelled = false;
		fetch(`/api/design/elements/${encodeURIComponent(id)}/nodes`)
			// A refusal and a shape without points are two different things, and the reader
			// has to be told which one it is. Measured on a text turned into outlines: the
			// route answered HTTP 500 and the line under the bed advised "make it a path
			// first with Combine" about something that already was a path.
			.then((r) => (r.ok ? r.json() : 'failed'))
			.then((data) => {
				if (cancelled) return;
				const readable = data !== 'failed' && data;
				nodePoints = readable && data.editable ? data.points : [];
				nodeSegments = readable && data.editable ? (data.segments ?? []) : [];
				nodeClosed = Boolean(readable && data.closed);
				// The node in hand has to stay in hand across a reload — every edit reloads
				// this — but the shape may have fewer points than before.
				if (nodePicked >= nodePoints.length) nodePicked = -1;
				nodeReason = !readable ? 'failed' : data.editable ? null : 'noPoints';
			})
			.catch(() => {
				if (cancelled) return;
				nodePoints = [];
				nodeSegments = [];
				nodeReason = 'failed';
			});
		return () => {
			cancelled = true;
		};
	});

	// ── Tegels: board groter dan bed (Task 15) ─────────────────────────────────
	//
	// For a board that is itself bigger than the bed, "falls off the bed" is not an error
	// but a method — that is exactly what tiling exists for. The same comparison as
	// `outsiders` below, but on the sheet itself in
	// place of on a shape inside it.
	/**
	 * The seam whose marks you are tapping *now*, or null when no series is running.
	 *
	 * The marks you tap are those of the seam before the current tile: that one burned
	 * the previous tile. Without a series there is no "now" and everything is equally
	 * strong.
	 */
	let actieveGrens = $derived(tiling?.run ? tiling.run.current - 1 : null);

	let plateTooBig = $derived(
		Boolean(sheet && outsideFrame({ x: 0, y: 0, width: sheet.width, height: sheet.height }, bed))
	);

	// The division is a function of the board size, the bed size and the design (the seam
	// moves to the fewest crossings), so it has to come again as often as the drawing
	// itself.
	$effect(() => {
		void design.revision;
		void sheet;
		tiling?.load();
	});

	let tileLayout = $derived(tiling?.layout ?? null);
	let huidigeTegel = $derived(tiling?.run?.current ?? -1);
	let klareTegels = $derived(new Set(tiling?.run?.done ?? []));

	let tilePosition = $derived.by(() => {
		const m = new Map<string, Tile>();
		for (const t of tileLayout?.tiles ?? []) m.set(`${t.row},${t.column}`, t);
		return m;
	});

	/** Seam lines: one segment per row or column boundary. The division is a regular
	 *  lattice, so the segments of consecutive rows (or columns) join up into the same
	 *  continuous line. */
	let tileSeams = $derived.by(() => {
		const lijnen: { x1: number; y1: number; x2: number; y2: number }[] = [];
		for (const t of tileLayout?.tiles ?? []) {
			const toTheRight = tilePosition.get(`${t.row},${t.column + 1}`);
			if (toTheRight)
				lijnen.push({ x1: t.burn.x1_mm, y1: t.burn.y0_mm, x2: t.burn.x1_mm, y2: t.burn.y1_mm });
			const below = tilePosition.get(`${t.row + 1},${t.column}`);
			if (below)
				lijnen.push({ x1: t.burn.x0_mm, y1: t.burn.y1_mm, x2: t.burn.x1_mm, y2: t.burn.y1_mm });
		}
		return lijnen;
	});

	// The pen: a click sets a corner, a press-and-pull sets a curve, Enter or a click on
	// the start point closes it. Escape throws away what is there — stopping halfway must
	// leave no mess — and Backspace takes back the last point, because the alternative was
	// starting over for one misplaced click.
	//
	// The numbers themselves live in `$lib/pen.ts`: the preview and the request have to be
	// the same line, and that agreement is testable without a browser.
	let penPoints = $state<PenPoint[]>([]);
	/** The point being pressed right now, and where on screen the press began — that
	 *  distance is what tells a click from a pull. */
	let penPress = $state<{ point: PenPoint; sx: number; sy: number } | null>(null);

	function penDown(event: PointerEvent) {
		const at = snapped(pointerMm(event), event);
		penPress = { point: { x: at.x, y: at.y, handle: null }, sx: event.clientX, sy: event.clientY };
	}

	function penDrag(event: PointerEvent) {
		if (!penPress) return;
		const far = Math.hypot(event.clientX - penPress.sx, event.clientY - penPress.sy);
		// A handle is a direction, not a place: snapping it to the grid would make the
		// curve jump between the few tangents the grid allows.
		const handle = far < HANDLE_THRESHOLD_PX ? null : pointerMm(event);
		// The guide lines belong to the point that was just snapped; while the handle is
		// being pulled nothing snaps, so leaving them up promises a snap that is not
		// happening.
		if (handle) guides = [];
		penPress = { ...penPress, point: { ...penPress.point, handle } };
	}

	function penUp() {
		const press = penPress;
		penPress = null;
		if (!press) return;
		const point = press.point;
		const first = penPoints[0];
		if (first && penPoints.length > 2 && Math.hypot(point.x - first.x, point.y - first.y) < 3) {
			finishPen(true);
			return;
		}
		penPoints = [...penPoints, point];
	}

	async function finishPen(closed: boolean) {
		// A double-click finishes, and its second press has already put a point on top of
		// the first — a segment of no length that nobody can grab again.
		const points = penPoints.filter(
			(point, index) =>
				index === 0 ||
				Math.hypot(point.x - penPoints[index - 1].x, point.y - penPoints[index - 1].y) > 0.2
		);
		penPoints = [];
		penPress = null;
		hover = null;
		if (points.length < 2) return;
		await onPath?.(penPath(points, closed), closed);
	}

	// Measuring: two clicks, and the distance stays until you start again. Useful for
	// checking that a cut-out really fits before you cut.
	let measureFrom = $state<{ x: number; y: number } | null>(null);
	let measureTo = $state<{ x: number; y: number } | null>(null);

	let measured = $derived.by(() => {
		if (!measureFrom || !measureTo) return null;
		const dx = measureTo.x - measureFrom.x;
		const dy = measureTo.y - measureFrom.y;
		return { dx, dy, length: Math.hypot(dx, dy) };
	});

	function startNode(event: PointerEvent, index: number) {
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		// Touching a node takes it in hand, whether or not the press turns into a drag:
		// the verbs need to know which node you mean, and pressing one is how you say it.
		nodePicked = index;
		const point = nodePoints.find((p) => p.index === index);
		if (point) nodeDrag = { index, x: point.x_mm, y: point.y_mm };
	}

	function moveNode(event: PointerEvent) {
		if (!nodeDrag) return;
		const at = snapped(pointerMm(event, true), event);
		nodeDrag = { ...nodeDrag, x: at.x, y: at.y };
	}

	async function endNode() {
		const drag = nodeDrag;
		nodeDrag = null;
		guides = [];
		const id = design.selectedId;
		if (!drag || !id) return;
		const moved = await edits.moveNode(id, drag.index, drag.x, drag.y);
		// A shape becomes a path when dragged and then gets a new id; without this the
		// user loses their selection in the middle of the work.
		if (moved?.id && moved.id !== id) design.select(moved.id);
		onEdited?.();
	}

	function startControl(event: PointerEvent, segment: Segment, control: { which: number; x_mm: number; y_mm: number }) {
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		controlDrag = { segment: segment.index, which: control.which, x: control.x_mm, y: control.y_mm };
	}

	function dragControl(event: PointerEvent) {
		if (!controlDrag) return;
		// No snapping: a handle is a direction and a length, not a place on the bed. Snapped
		// to the grid the curve would jump between the few tangents the grid allows.
		const at = pointerMm(event, true);
		controlDrag = { ...controlDrag, x: at.x, y: at.y };
	}

	async function endControl() {
		const drag = controlDrag;
		controlDrag = null;
		const id = design.selectedId;
		if (!drag || !id) return;
		const moved = await edits.moveControl(id, drag.segment, drag.which, drag.x, drag.y);
		if (moved?.id && moved.id !== id) design.select(moved.id);
		onEdited?.();
	}

	/**
	 * The piece being bent, while it is being bent.
	 *
	 * Without it the handle moves and the line stays put until the server answers, and
	 * then a drag is a guess. Built from the same numbers the request carries.
	 */
	let controlPreview = $derived.by(() => {
		const drag = controlDrag;
		if (!drag) return '';
		const segment = nodeSegments.find((s) => s.index === drag.segment);
		const from = nodePoints.find((p) => p.index === segment?.start);
		const to = nodePoints.find((p) => p.index === segment?.end);
		if (!segment || !from || !to) return '';
		const at = (which: number) =>
			which === drag.which
				? { x: drag.x, y: drag.y }
				: (() => {
						const other = segment.controls.find((c) => c.which === which);
						return other ? { x: other.x_mm, y: other.y_mm } : { x: from.x_mm, y: from.y_mm };
					})();
		const head = `M ${from.x_mm} ${from.y_mm}`;
		if (segment.kind === 'cubic') {
			const one = at(1);
			const two = at(2);
			return `${head} C ${one.x} ${one.y} ${two.x} ${two.y} ${to.x_mm} ${to.y_mm}`;
		}
		const one = at(1);
		return `${head} Q ${one.x} ${one.y} ${to.x_mm} ${to.y_mm}`;
	});

	/**
	 * The node verbs. One place, called by the menu, the shortcuts and the double-click.
	 *
	 * Every one of them can turn the shape into a path and so give it a new id; following
	 * that is the difference between carrying on and losing the selection mid-work.
	 */
	async function nodeVerb(verb: 'add' | 'remove' | 'curve' | 'corner') {
		const id = design.selectedId;
		if (!id || !canEdit || nodePicked < 0) return;
		const after = segmentAfter;
		let result: { id: string; index?: number } | null = null;
		if (verb === 'remove') {
			result = await edits.removeNode(id, nodePicked);
			nodePicked = -1;
		} else if (!after) {
			return;
		} else if (verb === 'add') {
			result = await edits.addNode(id, { segmentIndex: after.index });
			if (result?.index !== undefined) nodePicked = result.index;
		} else {
			result = await edits.setSegmentKind(id, after.index, verb === 'curve' ? 'quad' : 'line');
		}
		if (result?.id && result.id !== id) design.select(result.id);
		onEdited?.();
	}

	/**
	 * A node taken in hand from the keyboard.
	 *
	 * Measured before this: 70 Tab presses from a fresh load reached none of the four
	 * grips, because every one of them was `tabindex="-1"`. Only a pointer could set
	 * `nodePicked`, so all four verbs were out of reach without a mouse and the refusal
	 * written for "no node in hand" could never be seen.
	 */
	function pickNodeByKey(event: KeyboardEvent, index: number) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			event.stopPropagation();
			nodePicked = index;
			return;
		}
		// The menu on this node, from the keyboard: the two combinations a browser gives a
		// focused element. Measured before this: Shift+F10 with the canvas focused opened
		// nothing at all, so the verbs had no keyboard route even once a node was picked.
		if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) {
			event.preventDefault();
			event.stopPropagation();
			nodePicked = index;
			const box = (event.currentTarget as Element).getBoundingClientRect();
			onContextNode?.(
				new MouseEvent('contextmenu', {
					clientX: Math.round(box.left + box.width / 2),
					clientY: Math.round(box.top + box.height / 2)
				}),
				index
			);
		}
	}

	/** A double-click on the line: a node exactly where you clicked. */
	async function addNodeAt(event: MouseEvent) {
		const id = design.selectedId;
		if (!id || !canEdit) return;
		const at = pointerMm(event, true);
		const added = await edits.addNode(id, { xMm: at.x, yMm: at.y });
		if (added?.id && added.id !== id) design.select(added.id);
		if (added?.index !== undefined) nodePicked = added.index;
		onEdited?.();
	}

	// Dragging. The preview offset is purely visual; only on release does one command go
	// to the engine, so that we do not pelt it with intermediate states.
	type Drag = {
		mode: 'move' | 'scale' | 'rotate';
		corner: number;
		startX: number;
		startY: number;
		dx: number;
		dy: number;
		/** Only when rotating: the centre on screen and the rotated angle. */
		centerX: number;
		centerY: number;
		startAngle: number;
		angle: number;
		origin: { x: number; y: number; width: number; height: number };
	};
	let drag = $state<Drag | null>(null);

	let preview = $derived.by(() => {
		if (!drag || !selection) return null;
		// When rotating the frame stays where it is; only the rotation is a preview. The
		// real bounds we can only know after the engine.
		if (drag.mode === 'rotate') return { ...drag.origin };
		if (drag.mode === 'move') {
			return { ...drag.origin, x: drag.origin.x + drag.dx, y: drag.origin.y + drag.dy };
		}
		// Scaling from the opposite corner, so that one stays put.
		const { x, y, width, height } = drag.origin;
		const left = drag.corner % 2 === 0;
		const top = drag.corner < 2;
		const newX = left ? x + drag.dx : x;
		const newY = top ? y + drag.dy : y;
		const newWidth = left ? width - drag.dx : width + drag.dx;
		const newHeight = top ? height - drag.dy : height + drag.dy;
		return { x: newX, y: newY, width: newWidth, height: newHeight };
	});

	let outline = $derived(preview ?? selection);

	/**
	 * Letting the shape itself follow along while moving.
	 *
	 * Only the frame moved along and the shape stayed put until the engine answered. As
	 * long as nothing snapped that was barely noticeable; with guide lines it is, because
	 * then the line points at an edge that is somewhere else at that moment and the
	 * snapping looks wrong. The path data is in Tats, so the shift in mm has to go back to
	 * that.
	 */
	function offset(id: string) {
		if (!drag || !preview || !design.isSelected(id)) return undefined;
		const per = design.design?.units_per_mm ?? 1;
		if (drag.mode === 'move') return `translate(${drag.dx * per} ${drag.dy * per})`;
		if (drag.mode !== 'scale') return undefined;
		// Scaling happens from the opposite corner; so that one stays put and is the fixed
		// point of the enlargement.
		const o = drag.origin;
		if (!o.width || !o.height) return undefined;
		const vastX = (drag.corner % 2 === 0 ? o.x + o.width : o.x) * per;
		const vastY = (drag.corner < 2 ? o.y + o.height : o.y) * per;
		const sx = preview.width / o.width;
		const sy = preview.height / o.height;
		return `translate(${vastX} ${vastY}) scale(${sx} ${sy}) translate(${-vastX} ${-vastY})`;
	}

	/**
	 * The selection frame, a few screen pixels clear of the shape.
	 *
	 * Exactly on the contour the dashed accent line lay over the element's layer colour,
	 * and then you can no longer see which layer it is in. The frame belongs around it,
	 * not on it — that way both stay readable.
	 */
	let frameBox = $derived.by(() => {
		if (!outline) return null;
		const pad = 5 * mmPerPx;
		return {
			x: Math.min(outline.x, outline.x + outline.width) - pad,
			y: Math.min(outline.y, outline.y + outline.height) - pad,
			width: Math.abs(outline.width) + pad * 2,
			height: Math.abs(outline.height) + pad * 2
		};
	});
	let rotation = $derived(drag?.mode === 'rotate' ? drag.angle : 0);
	let center = $derived(
		outline ? { x: outline.x + outline.width / 2, y: outline.y + outline.height / 2 } : null
	);

	// Share the preview so that the top bar counts the coordinates live.
	$effect(() => {
		design.preview = preview;
	});

	/** Where the bed was clicked, in millimetres. */
	function pointerMm(event: MouseEvent, fromChild = false) {
		const target = event.currentTarget as SVGElement;
		const svg = fromChild ? target.ownerSVGElement : (target as SVGSVGElement);
		const rect = (svg ?? target).getBoundingClientRect();
		return {
			x: ((event.clientX - rect.left) / rect.width) * bed.width,
			y: ((event.clientY - rect.top) / rect.height) * bed.height
		};
	}

	// A click places a shape of a fixed size; after that you drag or scale it. Dragging
	// to draw comes together with the drag selection.
	const DEFAULT_MM = 20;

	// The first point of a line under construction, plus where the pointer is now for
	// the preview.
	let lineStart = $state<{ x: number; y: number } | null>(null);
	let hover = $state<{ x: number; y: number } | null>(null);

	/** The pen's line as it stands, including the piece under the pointer. Below `hover`,
	 *  because it reads it. */
	let penLine = $derived(
		penPreview(
			penPress ? [...penPoints, penPress.point] : penPoints,
			penPress || !hover ? null : { x: hover.x, y: hover.y, handle: null }
		)
	);

	$effect(() => {
		if (tool !== 'line') lineStart = null;
		// Switching tools leaves no guide line behind that no longer belongs to anything.
		void tool;
		guides = [];
	});

	function drawAt(event: MouseEvent) {
		// Placing snaps just as well as dragging: a new shape should land on the grid line
		// where you put it, not 3.7 mm beside it.
		const at = snapped(pointerMm(event), event);
		const half = DEFAULT_MM / 2;
		if (tool === 'rect') {
			onDrawn?.({
				type: 'rect',
				x_mm: at.x - half,
				y_mm: at.y - half,
				width_mm: DEFAULT_MM,
				height_mm: DEFAULT_MM
			});
		} else if (tool === 'circle') {
			onDrawn?.({ type: 'circle', cx_mm: at.x, cy_mm: at.y, r_mm: half });
		} else if (tool === 'point') {
			// One click, one spot, and no size to give it — which is why it is the only
			// tool here that ignores `half`. It lands in a Dots layer, because that is the
			// only kind of layer that burns a point at all.
			onDrawn?.({ type: 'point', x_mm: at.x, y_mm: at.y });
		} else if (tool === 'line') {
			// A line has two points: the first click sets the start, the second the end.
			// Placing a fixed horizontal line made no sense.
			if (!lineStart) {
				lineStart = at;
				return;
			}
			const from = lineStart;
			lineStart = null;
			onDrawn?.({ type: 'line', x1_mm: from.x, y1_mm: from.y, x2_mm: at.x, y2_mm: at.y });
		} else if (tool === 'text') {
			// The options (typeface, height, spacing) come from a dialog of their own; a
			// browser prompt can only manage a bare line of text.
			onTextAt?.({ x: at.x, y: at.y });
		}
	}

	function mmPerPixel() {
		return 1 / scale;
	}

	function startDrag(event: PointerEvent, mode: 'move' | 'scale' | 'rotate', corner = 0) {
		if (!canEdit || !selection) return;
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);

		// For rotating we need the centre in screen coordinates; the canvas scales mm to
		// pixels, so convert them through the SVG rect.
		const svg = (event.target as SVGElement).ownerSVGElement;
		const rect = svg?.getBoundingClientRect();
		const cx = rect ? rect.left + ((selection.x + selection.width / 2) / bed.width) * rect.width : 0;
		const cy = rect ? rect.top + ((selection.y + selection.height / 2) / bed.height) * rect.height : 0;

		drag = {
			mode,
			corner,
			startX: event.clientX,
			startY: event.clientY,
			dx: 0,
			dy: 0,
			centerX: cx,
			centerY: cy,
			startAngle: Math.atan2(event.clientY - cy, event.clientX - cx),
			angle: 0,
			origin: { ...selection }
		};
	}

	function moveDrag(event: PointerEvent) {
		if (!drag) return;
		if (drag.mode === 'rotate') {
			const now = Math.atan2(event.clientY - drag.centerY, event.clientX - drag.centerX);
			let degrees = ((now - drag.startAngle) * 180) / Math.PI;
			// Shift klikt vast op steps from 15 degrees.
			if (event.shiftKey) degrees = Math.round(degrees / 15) * 15;
			drag.angle = degrees;
			return;
		}
		let dx = (event.clientX - drag.startX) * mmPerPixel();
		let dy = (event.clientY - drag.startY) * mmPerPixel();

		if (snapOff(event)) {
			guides = [];
		} else if (drag.mode === 'move') {
			// Verplaatsen: randen én hartlijnen mogen vastklikken, per as apart.
			const off = snapBox(drag.origin, { dx, dy }, targets, snapGrid, snapTolerance);
			dx = off.dx;
			dy = off.dy;
			guides = off.guides;
		} else {
			// Scaling: only the corner you are holding. The opposite corner stays put, so
			// it has no business among the candidates.
			const toTheLeft = drag.corner % 2 === 0;
			const fromTop = drag.corner < 2;
			const corner = {
				x: (toTheLeft ? drag.origin.x : drag.origin.x + drag.origin.width) + dx,
				y: (fromTop ? drag.origin.y : drag.origin.y + drag.origin.height) + dy
			};
			const off = snapPoint(corner, targets, snapGrid, snapTolerance);
			dx += off.x - corner.x;
			dy += off.y - corner.y;
			guides = off.guides;
		}

		drag.dx = dx;
		drag.dy = dy;
	}

	async function endDrag(event: PointerEvent) {
		if (!drag) return;
		const finished = drag;
		const target = preview;
		drag = null;
		guides = [];
		design.preview = null;
		if (design.selectedIds.length === 0 || !target) return;

		if (finished.mode === 'rotate') {
			// Below half a degree it is a tremble, not a rotation.
			if (Math.abs(finished.angle) >= 0.5) {
				await edits.rotate(design.selectedIds, finished.angle);
				onEdited?.();
			}
			return;
		}

		// Below half a pixel it is a click, not a drag.
		if (Math.abs(finished.dx) < 0.05 && Math.abs(finished.dy) < 0.05) {
			// And an Alt+click on the selection goes one shape deeper. The drag surface
			// lies over the shapes, so without this the second Alt+click never reaches
			// the contour below and the pile could be entered but not walked. Alt+drag
			// keeps meaning "move without snapping": that is this same handler with
			// movement in it.
			if (finished.mode === 'move' && event.altKey) pickUnder(event, design.selectedIds[0]);
			return;
		}

		if (finished.mode === 'move') {
			await edits.move(design.selectedIds, finished.dx, finished.dy);
		} else if (target.width > 0.1 && target.height > 0.1) {
			await edits.resize(design.selectedIds, target.x, target.y, target.width, target.height);
		}
		onEdited?.();
	}

	// Drag selection: everything the frame touches gets selected.
	let band = $state<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
	// After releasing, a click still fires in the same place. Without this flag that
	// would clear the selection the drag frame has just made.
	let bandJustEnded = false;

	/**
	 * Everything under the pointer, topmost first.
	 *
	 * Asking the browser instead of doing the sums ourselves: `elementsFromPoint`
	 * uses exactly the hit geometry that is on screen, so a rotated shape, a hole in
	 * a ring and the 12 px band around a hairline all count the way they look. Doing
	 * the geometry a second time in JavaScript would be a second opinion, and the
	 * two would differ on precisely the awkward cases.
	 */
	function stackAt(clientX: number, clientY: number): string[] {
		if (typeof document === 'undefined') return [];
		const ids: string[] = [];
		for (const node of document.elementsFromPoint(clientX, clientY)) {
			const id = (node as SVGElement).getAttribute?.('data-el');
			if (id && !ids.includes(id)) ids.push(id);
		}
		return ids;
	}

	/**
	 * What one shape lying over another asks for.
	 *
	 * A plain click takes the top one — that is what a click means. Alt+click walks
	 * down the pile: whatever is selected now, the next one below it is chosen, and
	 * from the bottom it starts again at the top. Inkscape, Affinity and Illustrator
	 * all do it this way, so the finger memory is already there.
	 *
	 * Alt also skips snapping for one drag. There is no clash: that is about moving,
	 * this is about a click that does not move.
	 */
	let deeperTimer: ReturnType<typeof setTimeout> | null = null;

	function pickUnder(event: MouseEvent, fallback: string) {
		const stack = stackAt(event.clientX, event.clientY);
		if (stack.length < 2) {
			design.select(fallback);
			return;
		}
		const now = design.selectedIds.length === 1 ? stack.indexOf(design.selectedIds[0]) : -1;
		const next = stack[(now + 1) % stack.length];
		design.select(next);
		// Say where you are in the pile, or the second Alt+click looks like nothing
		// happened — two shapes of the same size on top of each other look identical
		// until you read their names.
		//
		// Upward, to the line in the action bar that already says what is selected.
		// A strip below the bed would be honest but it lies *in the flow*: the canvas
		// would get shorter, the drawing would rescale, and the next Alt+click would
		// land somewhere else. Measured: the bed went from 1018×610 to 986×591 and the
		// pile was gone from under the pointer.
		onDeeper?.({ index: stack.indexOf(next) + 1, total: stack.length });
		if (deeperTimer) clearTimeout(deeperTimer);
		deeperTimer = setTimeout(() => onDeeper?.(null), 4000);
	}


	/**
	 * Where the pointer is captured as soon as there really is a drag.
	 *
	 * Not straight away on the press: an element that captures the pointer also gets the
	 * click that follows. Capture that on the SVG and every click on a shape comes in as
	 * "click beside everything" and nothing was selected any more. So only capture once
	 * the pointer moves — then it is a drag, not a click.
	 */
	let bandCatcher: Element | null = null;

	/**
	 * Where the press that may become the next click started, and whether it moved.
	 *
	 * The svg gets the click of every press-and-release whose two ends lie on different
	 * elements, and "clicked beside everything" is how it reads that. A drag is not that.
	 */
	let pressFrom: { x: number; y: number } | null = null;
	let pressDragged = false;

	function startBand(event: PointerEvent) {
		const at = pointerMm(event);
		band = { x1: at.x, y1: at.y, x2: at.x, y2: at.y };
		bandCatcher = event.currentTarget as Element;
	}

	function moveBand(event: PointerEvent) {
		if (!band) return;
		const at = pointerMm(event);
		if (bandCatcher && (Math.abs(at.x - band.x1) > 0.5 || Math.abs(at.y - band.y1) > 0.5)) {
			bandCatcher.setPointerCapture?.(event.pointerId);
			bandCatcher = null;
		}
		band = { ...band, x2: at.x, y2: at.y };
	}

	function endBand(event: PointerEvent) {
		bandCatcher = null;
		const held = event.currentTarget as Element;
		// releasePointerCapture throws when nothing is captured; releasing before the
		// click is necessary, otherwise that click is still redirected to the SVG.
		if (held?.hasPointerCapture?.(event.pointerId)) held.releasePointerCapture(event.pointerId);
		if (!band) return;
		const box = {
			x0: Math.min(band.x1, band.x2),
			y0: Math.min(band.y1, band.y2),
			x1: Math.max(band.x1, band.x2),
			y1: Math.max(band.y1, band.y2)
		};
		const dragged = box.x1 - box.x0 > 0.5 || box.y1 - box.y0 > 0.5;
		band = null;
		if (!dragged || !design.design) return;
		bandJustEnded = true;

		if (cropping) {
			cropping = false;
			onCrop?.({
				x: box.x0,
				y: box.y0,
				width: box.x1 - box.x0,
				height: box.y1 - box.y0
			});
			return;
		}

		const perMm = design.design.units_per_mm;
		const hit = design.elements.filter((element) => {
			if (!element.bounds || element.hidden) return false;
			const [ex0, ey0, ex1, ey1] = element.bounds.map((v) => v / perMm);
			// Overlap, not full containment: that way you do not have to drag exactly.
			return ex0 <= box.x1 && ex1 >= box.x0 && ey0 <= box.y1 && ey1 >= box.y0;
		});
		design.selectMany(hit.map((element) => element.id));
	}

	// Rulers. Two things the previous version did not do: the ticks are aligned to the
	// bed (the bed is centred *and* panned, so accounting for the pan alone does not
	// hold), and the step size follows the zoom — fixed at 50 mm you see a wall of
	// figures zoomed out and almost nothing zoomed in.
	const STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500];
	/** Width of the ruler strip; used in the CSS as well. */
	const RULER = 20;

	/** Top-left corner of the bed in screen pixels, within the canvas area. */
	let bedOrigin = $derived({
		x: (canvasWidth - bed.width * scale) / 2 + pan.x,
		y: (canvasHeight - bed.height * scale) / 2 + pan.y
	});

	/** The smallest step at which two labels are at least 55 px apart. */
	let rulerStep = $derived(STEPS.find((step) => step * scale >= 55) ?? 500);

	/**
	 * The subdivision below the main step: the largest round number that fits into it
	 * whole and that can still be told apart on screen.
	 *
	 * Blindly dividing by five gave a grid of 4 mm at a step of 20 mm — a measure nobody
	 * thinks in, and too close together to read anything off.
	 */
	let subStep = $derived(
		[...STEPS]
			.filter((s) => s < rulerStep && rulerStep % s === 0 && s * scale >= 12)
			.sort((a, b) => b - a)
			.pop() ?? 0
	);

	/**
	 * Ticks across the whole ruler, beside the bed as well (gap C4).
	 *
	 * The scale stopped at the bed edge, and then for a shape that
	 * lies beside it you cannot read off *how far* beside it — precisely the number you
	 * need to bring it back. LightBurn lets the scale run on with negative values; we do
	 * the same here.
	 *
	 * Counting in steps rather than adding millimetres: `value += 0.1` three hundred
	 * times produces 29.999999, and then the modulo test for "is this a major tick" flips
	 * arbitrarily.
	 */
	function ticks(fromMm: number, toMm: number, step: number, sub: number, lengthMm: number) {
		const fine = sub || step;
		const perHoofd = Math.max(1, Math.round(step / fine));
		const marks: { value: number; major: boolean; outside: boolean; label: string }[] = [];
		const firstMark = Math.ceil(fromMm / fine - 0.001);
		const last = Math.floor(toMm / fine + 0.001);
		// At an absurd zoom level do not draw thousands of ticks.
		if (last - firstMark > 400) return marks;
		for (let i = firstMark; i <= last; i++) {
			const value = i * fine;
			const major = ((i % perHoofd) + perHoofd) % perHoofd === 0;
			marks.push({
				value,
				major,
				// Off the bed: a tick and a figure, but lighter — that way you see at a
				// glance where the work area stops.
				outside: value < -0.001 || value > lengthMm + 0.001,
				label: major ? String(Math.round(value)) : ''
			});
		}
		return marks;
	}

	// What of the ruler is on screen, in millimetres. Zero lies on the bed corner, so
	// left of the bed is negative.
	let ticksX = $derived(
		ticks(
			-bedOrigin.x / scale,
			(canvasWidth - bedOrigin.x) / scale,
			rulerStep,
			subStep,
			bed.width
		)
	);
	let ticksY = $derived(
		ticks(
			-bedOrigin.y / scale,
			(canvasHeight - bedOrigin.y) / scale,
			rulerStep,
			subStep,
			bed.height
		)
	);

	// ── Off the bed or off the sheet ──────────────────────────────────────────
	//
	// Gap C2: a shape that crosses the bed or the sheet was reported nowhere. Two
	// different errors, and the difference counts: off the bed the machine *cannot* go,
	// off the sheet it can — but there is no material there. Hence two colours and two
	// sentences, and not one "watch out".
	const EDGE_SLACK = 0.5;

	function outsideFrame(
		box: { x: number; y: number; width: number; height: number },
		frame: { width: number; height: number }
	) {
		return (
			box.x < -EDGE_SLACK ||
			box.y < -EDGE_SLACK ||
			box.x + box.width > frame.width + EDGE_SLACK ||
			box.y + box.height > frame.height + EDGE_SLACK
		);
	}

	/** Per element: does it fall off the bed, or only off the sheet? */
	let outsiders = $derived.by(() => {
		const perMm = design.design?.units_per_mm;
		const off = new Map<string, 'bed' | 'sheet'>();
		if (!perMm) return off;
		for (const element of design.elements) {
			if (!element.bounds || element.hidden) continue;
			// Only work that really goes into the machine later. A shape that is in no
			// layer at all, or in a layer set to "does not burn", costs no material and no
			// time — outlining that in red is a false alarm, and false alarms teach a user
			// to ignore them. That it does not burn is already there: grey dotted on the
			// canvas.
			const streek = design.strokeFor(element);
			if (streek.dashed || streek.dimmed || !streek.visible) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			const box = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
			if (outsideFrame(box, bed)) off.set(element.id, 'bed');
			else if (sheet && outsideFrame(box, sheet)) off.set(element.id, 'sheet');
		}
		return off;
	});

	let shapesOffBed = $derived([...outsiders.values()].filter((v) => v === 'bed').length);
	let offSheet = $derived([...outsiders.values()].filter((v) => v === 'sheet').length);

	// ── Layer numbers beside the shape (gap C6) ───────────────────────────────
	//
	// The design system forbids information that sits in colour alone, and on the bed the
	// layer was exactly that. Under deuteranopia layers 4 and 10 are only 24 units apart
	// (measured by c6-a11y) — on a 1.2 px line that is nothing. The number is the same
	// safety net as on the chip in the panel.
	//
	// Why a number and not a line style per layer kind: on this canvas dashed already
	// means "is in no layer at all", and half transparent means "does not burn"
	// (decision B4). Adding a third dash pattern turns three meanings into one riddle,
	// and it would not say *which* of the four cut layers you are looking at either. The
	// number does say that, and it is exactly the same number as in the list and in the
	// pre-flight (gap J7).
	let numbersOn = $state(
		typeof window === 'undefined' || localStorage.getItem('openkerf.laagnummers') !== 'uit'
	);

	function nummersSchakel() {
		numbersOn = !numbersOn;
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.laagnummers', numbersOn ? 'aan' : 'uit');
		}
	}

	/**
	 * Where the numbers go, in millimetres.
	 *
	 * Only on shapes that have room for them on screen: a figure beside a four-pixel
	 * shape is a blot, and fifty blots make the bed unreadable. Anybody who wants to see
	 * it up close zooms in — then they appear by themselves.
	 */
	let layerLabels = $derived.by(() => {
		if (!numbersOn) return [];
		const perMm = design.design?.units_per_mm;
		if (!perMm) return [];
		const labels = [];
		for (const element of design.elements) {
			if (element.hidden || !element.bounds) continue;
			const streek = design.strokeFor(element);
			if (!streek.visible) continue;
			const ids = element.operation_ids?.length
				? element.operation_ids
				: element.operation_id
					? [element.operation_id]
					: [];
			// The layer that decides the colour is also the layer that gets the number.
			let beste: string | null = null;
			let bestIndex = -1;
			for (const id of ids) {
				const i = design.operations.findIndex((o) => o.id === id);
				if (i < 0 || design.isLayerHidden(id)) continue;
				if (bestIndex < 0 || i < bestIndex) {
					bestIndex = i;
					beste = id;
				}
			}
			const number = design.numberFor(beste);
			if (!number) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			// Gap C8: a shape that is smaller on screen than the figure does not get one —
			// with fifty small shapes the bed otherwise becomes a cloud of numbers that
			// points at nothing. But what you selected yourself is never noise: one figure
			// beside one shape is precisely the question you asked when you selected it.
			// So the size bound does not apply to the selection, and with that the double
			// encoding of C6 is reachable at every zoom level without zooming in.
			const klein = (x1 - x0) * scale < 22 || (y1 - y0) * scale < 14;
			if (klein && !design.isSelected(element.id)) continue;
			labels.push({
				id: element.id,
				number,
				colour: streek.color,
				x: x0,
				y: y0,
				dim: streek.dimmed
			});
		}
		return labels;
	});

	// ── Vastklikken ────────────────────────────────────────────────────────────
	//
	// The snap distance is in screen pixels and is converted back to millimetres here.
	// That is how LightBurn and Inkscape do it, and it is the only measure that holds: at
	// 400% a pixel is a quarter of a millimetre, so the snapping becomes four times more
	// precise by itself instead of four times coarser.
	const SNAP_PX = 9;
	let snapTolerance = $derived(SNAP_PX * mmPerPx);

	// To the finest grid line you can actually see at that moment. When the fine
	// subdivision is off because it falls too close together, the main step is the only
	// line there is — snapping to something invisible is a riddle.
	let snapGrid = $derived(subStep || rulerStep);

	/**
	 * The boxes of all the other shapes, in mm.
	 *
	 * What you are dragging yourself does not count: a shape does not snap to itself.
	 * Hidden shapes do not either — you cannot see them, so a guide line on them is
	 * inexplicable.
	 */
	let andereDozen = $derived.by(() => {
		const perMm = design.design?.units_per_mm ?? 1;
		return design.elements
			.filter((e) => e.bounds && !e.hidden && !design.isSelected(e.id))
			.map((e) => {
				const [x0, y0, x1, y1] = e.bounds!;
				return { x: x0 / perMm, y: y0 / perMm, width: (x1 - x0) / perMm, height: (y1 - y0) / perMm };
			});
	});

	let targets = $derived(
		surroundingTargets({ bed, sheet: sheet, anderen: andereDozen })
	);

	/** The guide lines that are visible *now*. Empty as soon as you let go. */
	let guides = $state<SnapGuide[]>([]);

	/**
	 * The guide lines as drawable segments.
	 *
	 * A line that hangs off a shape runs from that shape past whatever snaps to it, so
	 * that you see *which* two things are aligned — that is what Inkscape and Illustrator
	 * do as well. A grid, sheet or bed line has no counterpart and therefore runs across
	 * the whole bed.
	 */
	let guideLines = $derived.by(() => {
		const margin = 14 * mmPerPx;
		const live = preview ?? selection;
		// Where the eye is: the thing you are moving, or otherwise the cursor.
		const anchor = live
			? {
					x0: Math.min(live.x, live.x + live.width),
					x1: Math.max(live.x, live.x + live.width),
					y0: Math.min(live.y, live.y + live.height),
					y1: Math.max(live.y, live.y + live.height)
				}
			: hover
				? { x0: hover.x, x1: hover.x, y0: hover.y, y1: hover.y }
				: { x0: 0, x1: bed.width, y0: 0, y1: bed.height };
		const clamp = (v: number, layer: number, high: number) => Math.min(Math.max(v, layer), high);

		return guides.map((g) => {
			let from = 0;
			let until = g.axis === 'x' ? bed.height : bed.width;
			if (g.span) {
				from = Math.min(g.span[0], g.axis === 'x' ? anchor.y0 : anchor.x0);
				until = Math.max(g.span[1], g.axis === 'x' ? anchor.y1 : anchor.x1);
				from -= margin;
				until += margin;
			}
			// The little word hangs off the shape you are moving, not off the end of the
			// line: for a line that runs across the whole bed that end fell behind the
			// right-hand panel and you read "bed ed…".
			const text = SNAP_LABEL[g.kind];
			const wide = text.length * labelSize * 0.55;
			const vertical = g.axis === 'x';
			let tx = vertical ? g.pos : anchor.x1 + labelSize * 0.5;
			let textAnchor = vertical ? 'middle' : 'start';
			if (!vertical && tx + wide > bed.width) {
				tx = anchor.x0 - labelSize * 0.5;
				textAnchor = 'end';
			}
			return {
				key: `${g.axis}:${g.kind}:${g.pos.toFixed(3)}`,
				label: text,
				x1: vertical ? g.pos : from,
				x2: vertical ? g.pos : until,
				y1: vertical ? from : g.pos,
				y2: vertical ? until : g.pos,
				tx: vertical ? clamp(tx, wide / 2, bed.width - wide / 2) : clamp(tx, 0, bed.width),
				ty: vertical
					? clamp(anchor.y0 - labelSize * 1.1, labelSize, bed.height - labelSize * 0.3)
					: clamp(g.pos - labelSize * 0.4, labelSize, bed.height - labelSize * 0.3),
				anchor: textAnchor
			};
		});
	});

	/**
	 * Is snapping on? The button beside the zoom control switches it off for longer than
	 * one movement, and that choice is kept between sessions — LightBurn and xTool both
	 * have a switch for it, and anybody who wants to work without it should not have to
	 * hold a key down every time.
	 */
	let snapOn = $state(
		typeof window === 'undefined' || localStorage.getItem('openkerf.snap') !== 'uit'
	);

	function snapToggle() {
		snapOn = !snapOn;
		guides = [];
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.snap', snapOn ? 'aan' : 'uit');
		}
	}

	/**
	 * Alt inverts the state for that one movement: on, it holds the snapping back; off,
	 * it turns it on for a moment. That last part is how LightBurn does it too — a
	 * modifier that does nothing as soon as you have switched the feature off is a dead
	 * key.
	 */
	function snapOff(event: { altKey?: boolean } | null | undefined) {
		return snapOn === (event?.altKey === true);
	}

	/** Snapping a single point and setting the guide lines at the same time. */
	function snapped(at: { x: number; y: number }, event?: { altKey?: boolean } | null) {
		if (snapOff(event)) {
			guides = [];
			return at;
		}
		const off = snapPoint(at, targets, snapGrid, snapTolerance);
		guides = off.guides;
		return { x: off.x, y: off.y };
	}

	// The grid did not follow the zoom: it was fixed at 50 mm while the ruler jumped to
	// 20 or 100. Then no line falls on a figure and you cannot read anything off the bed.
	// Now the grid shares the ruler's step, with a fine subdivision that disappears as
	// soon as it falls too close together.
	let gridMajor = $derived(rulerStep * scale);
	let gridMinor = $derived(subStep * scale);
	let gridStyle = $derived(
		`background-size: ${gridMajor}px ${gridMajor}px, ${gridMajor}px ${gridMajor}px,` +
			(gridMinor > 0
				? ` ${gridMinor}px ${gridMinor}px, ${gridMinor}px ${gridMinor}px`
				: ' 0 0, 0 0')
	);

	/** Where the pointer is, as a tick on both rulers. */
	let pointer = $state<{ x: number; y: number } | null>(null);

	/** The dropdown behind the zoom percentage. */
	let zoomMenu = $state(false);
	let zoomMenuAt = $state({ x: 0, y: 0 });
	let zoomStanden = $derived<MenuList>([
		{
			items: [
				{ id: 'z-alles', label: t('action.zoomAll'), key: '3', run: passend },
				{
					id: 'z-selectie',
					label: t('action.zoomSelection'),
					key: '2',
					off: design.selectedIds.length ? undefined : t('reason.nothingSelected'),
					run: naarSelectie
				},
				{ id: 'z-bed', label: t('action.zoomBed'), key: '0', run: bedFit },
				{ id: 'z-100', label: t('action.zoomHundred'), key: '1', run: honderd }
			]
		},
		{
			items: [25, 50, 100, 200, 400].map((value) => ({
				id: `z-${value}`,
				label: `${value} %`,
				on: procent === value,
				run: () => naarProcent(value)
			}))
		}
	]);

	/**
	 * The height of everything below the canvas, as a CSS variable on the root.
	 *
	 * The camera pill floats above the canvas at a fixed distance from the
	 * bottom and reads this measure. By now there is more than one strip below the bed —
	 * the colour strip (B2) and the warning about work off the bed (C2) — so we measure
	 * the block as a whole. Measure, do not calculate: the height differs per device,
	 * because on touch screens the buttons are bigger and the line breaks.
	 */
	let bottomEdgeHeight = $state(0);
	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.style.setProperty('--palette-height', `${bottomEdgeHeight}px`);
		return () => document.documentElement.style.removeProperty('--palette-height');
	});

	/**
	 * The handle for the outside world.
	 *
	 * The page needs this for the canvas context menu and for the shortcuts; those are
	 * handled there because there is one table of shortcuts. The alternative was lifting
	 * the zoom state up to the page, and then the page would have to know how big the work
	 * area is and where the bed corner lies.
	 */
	$effect(() => {
		control = {
			zoom: (what) => {
				if (what === 'all') passend();
				else if (what === 'selection') naarSelectie();
				else if (what === 'bed') bedFit();
				else honderd();
			},
			step: (factor: number) => zoomAt(factor),
			snap: snapToggle,
			layerNumbers: nummersSchakel,
			node: nodeVerb,
			penBack: () => (penPoints = penPoints.slice(0, -1)),
			state: () => ({
				snap: snapOn,
				layerNumbers: numbersOn,
				penDrawing: penPoints.length > 0,
				nodeIndex: nodePicked,
				nodeCount: nodePoints.length,
				nodeClosed,
				nodeKind: segmentAfter?.kind ?? null
			})
		};
		return () => (control = null);
	});

	// Not through pointerMm: that computes from the SVG, and this happens on the
	// enclosing area that *also* contains the rulers. Compute from the bed corner.
	function pointerOnRulers(event: PointerEvent) {
		if (!frame) return null;
		const rect = frame.getBoundingClientRect();
		return {
			x: (event.clientX - rect.left - RULER - bedOrigin.x) / scale,
			y: (event.clientY - rect.top - RULER - bedOrigin.y) / scale
		};
	}
</script>

<!-- The zoom shortcuts used to be here and have moved to the page: since there is one
     table of shortcuts (`$lib/actions.ts`) there should also be one place that handles
     them. What stays here is what only exists here: finishing the pen, and the space bar
     you pan with. -->
<svelte:window
	onkeydown={(e) => {
		const target = e.target as HTMLElement | null;
		const ticking = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
		if (e.key === ' ' && !ticking && !space) {
			// Prevent the page scrolling along as long as space is the pan grip.
			e.preventDefault();
			space = true;
			return;
		}
		if (tool !== 'pen' || !penPoints.length) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			finishPen(false);
		} else if (e.key === 'Escape') {
			e.preventDefault();
			penPoints = [];
			penPress = null;
		} else if (e.key === 'Backspace' || e.key === 'Delete') {
			// One misplaced click used to mean starting the whole line again.
			e.preventDefault();
			penPoints = penPoints.slice(0, -1);
		}
	}}
	onkeyup={(e) => {
		if (e.key === ' ') {
			space = false;
			panning = null;
		}
	}}
	onblur={() => {
		// The window loses focus with space still held: then the keyup never comes and
		// the canvas stays stuck in pan mode.
		space = false;
		panning = null;
	}}
/>

<!-- The wheel zooms, alt or the middle button pans. Keyboard: the zoom buttons
     rechtsonder zijn gewone buttons. -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="canvas-wrap"
	class:panning={space}
	bind:this={frame}
	onwheel={(e) => {
		e.preventDefault();
		zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY);
	}}
	onpointerdown={(e) => {
		// Middle button, alt, or space held: drag to pan. Not with the pen in hand: there
		// Alt already means "this one point does not snap", and the press that follows is a
		// pull that makes a curve. Both on one gesture means the bed slides away under the
		// handle you are aiming.
		if (e.button === 1 || (e.altKey && tool !== 'pen') || (space && e.button === 0)) {
			e.preventDefault();
			startPan(e);
		}
	}}
	onpointermove={(e) => {
		movePan(e);
		pointer = pointerOnRulers(e);
			onPointerMm?.(pointer);
	}}
	onpointerleave={() => {
		pointer = null;
		if (!drag) guides = [];
	}}
	onpointerup={() => (panning = null)}
	oncontextmenu={(e) => {
		// Only when there was no shape under the cursor: that catches it itself and stops
		// the bubble. That way there is one right-click with two outcomes, and not one
		// menu that has to cover everything.
		e.preventDefault();
		onContextCanvas?.(e, pointerOnRulers(e as unknown as PointerEvent) ?? { x: 0, y: 0 });
	}}
>
	<div class="corner" aria-hidden="true">mm</div>
	<svg class="ruler-x" aria-hidden="true">
		<!-- The work area as a band on the ruler itself (gap C4). The scale now runs past
		     the bed, so something has to say *where* the bed stops — otherwise you read a
		     number off without knowing whether it is still on the machine. -->
		<rect
			class="werkgebied"
			x={bedOrigin.x}
			y="0"
			width={Math.max(0, bed.width * scale)}
			height="20"
		/>
		{#each ticksX as tick (tick.value)}
			{@const at = bedOrigin.x + tick.value * scale}
			{#if at >= -40 && at <= canvasWidth + 40}
				<!-- Ticks below the figure band, not through it: with ticks running to y=8
				     there was always one cutting through "100" and you read "109". Figures
				     live above, ticks below. -->
				<line class:outside={tick.outside} x1={at} x2={at} y1={tick.major ? 11 : 15} y2="20" />
				{#if tick.label}
					<text class:outside={tick.outside} x={at + 3} y="1">{tick.label}</text>
				{/if}
			{/if}
		{/each}
		{#if pointer}
			<line class="here" x1={bedOrigin.x + pointer.x * scale} x2={bedOrigin.x + pointer.x * scale} y1="0" y2="20" />
		{/if}
	</svg>
	<svg class="ruler-y" aria-hidden="true">
		<rect
			class="werkgebied"
			x="0"
			y={bedOrigin.y}
			width="20"
			height={Math.max(0, bed.height * scale)}
		/>
		{#each ticksY as tick (tick.value)}
			{@const at = bedOrigin.y + tick.value * scale}
			{#if at >= -40 && at <= canvasHeight + 40}
				<line class:outside={tick.outside} y1={at} y2={at} x1={tick.major ? 11 : 15} x2="20" />
				{#if tick.label}
					<text class:outside={tick.outside} x="1" y={at - 3} transform="rotate(-90 1 {at - 3})">{tick.label}</text>
				{/if}
			{/if}
		{/each}
		{#if pointer}
			<line class="here" y1={bedOrigin.y + pointer.y * scale} y2={bedOrigin.y + pointer.y * scale} x1="0" x2="20" />
		{/if}
	</svg>

	<div class="canvas" bind:clientWidth={canvasWidth} bind:clientHeight={canvasHeight}>
		<div
			class="bed"
			style="width: {bed.width * scale}px; height: {bed.height * scale}px;
			       left: {bedOrigin.x}px; top: {bedOrigin.y}px;
			       {gridStyle}"
		>
			{#if cameraSrc}
				<!-- The image has already been straightened to the bed rectangle by the
				     camera plugin, so it fits the bed one to one. An ordinary <img> with an
				     MJPEG source: the browser decodes it itself, we have nothing to
				     refresh. -->
				<img
					class="camera"
					src={cameraSrc}
					alt={t('camera.title')}
					style="opacity: {cameraOpacity}"
				/>
			{/if}

			{#if sheet && (sheet.width < bed.width - 0.5 || sheet.height < bed.height - 0.5)}
				<!-- The sheet lies inside the bed; everything outside it does not burn. -->
				<div
					class="sheet"
					style="width: {sheet.width * scale}px; height: {sheet.height * scale}px"
				>
					<span class="sheet-label mono">{sheet.name}</span>
				</div>
			{/if}

			<span class="bed-label mono">
				{t('canvas.bedSize', { width: bed.width.toFixed(0), height: bed.height.toFixed(0) })}
			</span>

			<!-- `!job`: while a job is running, "Empty bed — choose Import" is an invitation
			     at the wrong moment. Seen on a photo where the head's trail ran across the
			     bed while it said "Empty bed" underneath; that can happen as soon as the
			     design is cleared while the machine is still working on what had already
			     been spooled. -->
			{#if design.isEmpty && !cameraSrc && !job}
				<!-- An empty bed is a blank page: without text nobody knows where to start.
				     Catches no pointer, because you have to be able to draw through it. -->
				<div class="blank">
					<h2>{t('canvas.empty.title')}</h2>
					<p>{t('canvas.empty.body')}</p>
				</div>
			{/if}

			<!-- Clicking the empty canvas deselects. The keyboard equivalent is Escape,
			     caught at window level; the elements themselves are focusable and can be
			     selected with Enter/space. -->
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<svg
				viewBox="0 0 {bed.width} {bed.height}"
				style="position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible"
				role="img"
				aria-label={head
					? t('canvas.headAt', { x: i18n.number(head[0], 1), y: i18n.number(head[1], 1) })
					: t('canvas.headUnknown')}
				onclick={(e) => {
					if (e.target !== e.currentTarget) return;
					// The pen works on pointerdown/up, because a press that turns into a pull
					// is a curve and a click is a corner — a `click` event cannot tell them
					// apart.
					if (tool === 'pen') return;
					if (tool === 'measure') {
						const at = snapped(pointerMm(e), e);
						if (!measureFrom || measureTo) {
							measureFrom = at;
							measureTo = null;
						} else {
							measureTo = at;
						}
						return;
					}
					if (tool !== 'select' && tool !== 'nodes' && tool !== 'pen' && canEdit) {
						drawAt(e);
						return;
					}
					// Clicking beside an element clears the selection — except for the click
					// that immediately follows a drag frame.
					if (bandJustEnded) {
						bandJustEnded = false;
						return;
					}
					// And except when this "click" is the tail of a drag. A press that starts on
					// a shape and ends somewhere else delivers its click to the svg, because
					// that is the nearest ancestor of both. With the node tool in hand no
					// selection frame catches that drag, so it landed here: measured, a drag
					// from 90,40 mm across the top edge of a selected rectangle moved nothing
					// (bounds unchanged) and yet left the panel reading "Nothing selected." with
					// every knot gone from the bed.
					if (pressDragged) {
						pressDragged = false;
						return;
					}
					design.select(null);
				}}
				onpointerdown={(e) => {
					pressFrom = pointerMm(e);
					pressDragged = false;
					if (cropping && e.button === 0) {
						startBand(e);
						return;
					}
					if (tool === 'pen' && canEdit && e.button === 0 && e.target === e.currentTarget) {
						// The capture goes on the svg itself: the pull that follows may leave
						// the bed, and a handle that stops at the edge of the drawing is a
						// handle you cannot aim.
						(e.currentTarget as Element).setPointerCapture?.(e.pointerId);
						penDown(e);
						return;
					}
					// Above an element as well: dragging draws a frame, clicking without
					// dragging selects. Without this you could no longer draw a selection
					// inside a large frame as soon as that frame became clickable.
					if (tool === 'select' && !e.altKey && !space && e.button === 0) {
						startBand(e);
					}
				}}
				onpointermove={(e) => {
					// Where the tool would land, *with* snapping — that way you see the
						// guide line before the click and not only afterwards.
						if (tool === 'measure' && measureFrom && !measureTo) hover = snapped(pointerMm(e), e);
					else if (penPress) penDrag(e);
					else if (tool === 'pen' && penPoints.length) hover = snapped(pointerMm(e), e);
					else if (lineStart) hover = snapped(pointerMm(e), e);
						else if (canEdit && tekengereedschap) snapped(pointerMm(e), e);
					moveBand(e);
				}}
				onpointerup={(e) => {
					if (pressFrom) {
						const at = pointerMm(e);
						// Half a millimetre, the same threshold the selection frame uses to tell a
						// drag from a click.
						pressDragged =
							Math.abs(at.x - pressFrom.x) > 0.5 || Math.abs(at.y - pressFrom.y) > 0.5;
						pressFrom = null;
					}
					if (penPress) {
						penUp();
						return;
					}
					endBand(e);
				}}
				ondblclick={(e) => {
					// Finishing the pen. A double-click is two presses, so the second point
					// lands on the first; `finishPen` throws that duplicate away.
					if (tool === 'pen' && penPoints.length >= 2) {
						e.preventDefault();
						finishPen(false);
					}
				}}
			>
				<!-- The head's trail, *below* the design (gap J3).
				     First as a wide, soft band in the accent and only then the shapes over
				     it: that way what the machine has covered lights up without the layer
				     colour underneath disappearing — and that colour is the only thing that
				     says *which* operation it was. On top of a 1.2 px line the trail in
				     --text-2 was literally invisible on the trial job; measured and
				     weggegooid. -->
				{#if trail}
					<polyline
						class="trail-baan"
						points={trail}
						vector-effect="non-scaling-stroke"
						aria-hidden="true"
					/>
				{/if}

				<!-- The tile division (Task 15): seams as lines, the tile whose turn it is in
				     the ordinary colour, the rest dimmed, finished tiles a little less dimmed
				     than what is still to come, and the marks as a circle-with-cross. That way
				     you see at a glance what is already down and what is still coming. Only
				     with two or more tiles: with one tile there is nothing to divide. -->
				{#if tileLayout && tileLayout.tiles.length > 1}
					<g class="tiles" aria-hidden="true">
						{#each tileLayout.tiles as tile (tile.index)}
							{#if tile.index !== huidigeTegel}
								<rect
									class="tile-area"
									class:tile-ready={klareTegels.has(tile.index)}
									x={tile.burn.x0_mm}
									y={tile.burn.y0_mm}
									width={tile.burn.x1_mm - tile.burn.x0_mm}
									height={tile.burn.y1_mm - tile.burn.y0_mm}
								/>
							{/if}
						{/each}
						{#each tileSeams as seam, i (i)}
							<line
								class="tile-seam"
								x1={seam.x1}
								y1={seam.y1}
								x2={seam.x2}
								y2={seam.y2}
								vector-effect="non-scaling-stroke"
							/>
						{/each}
						{#each tileLayout.marks as mark (mark.boundary)}
							{#each mark.points as point, i (i)}
								<!-- The marks of the seam you are tapping *now* are at full strength;
								     the rest dim. Without that difference, three tiles give four marks
								     called 1, 2, 1, 2, and then a number is just as confusing as a
								     word for a position. The marks you tap are those of the seam before
								     the current tile — that one burned the previous tile. -->
								<g
									class="tile-mark"
									class:active={actieveGrens === null || mark.boundary === actieveGrens}
								>
									<circle cx={point.x_mm} cy={point.y_mm} r={4 * mmPerPx} />
									<line
										x1={point.x_mm - 4 * mmPerPx}
										y1={point.y_mm}
										x2={point.x_mm + 4 * mmPerPx}
										y2={point.y_mm}
									/>
									<line
										x1={point.x_mm}
										y1={point.y_mm - 4 * mmPerPx}
										x2={point.x_mm}
										y2={point.y_mm + 4 * mmPerPx}
									/>
									<!-- The same number that is burned beside the circle, on the same
									     side. At screen size, like the symbol itself: this is a pointer,
									     not a to-scale rendering. Text in an SVG that measures in
									     millimetres has to be counter-scaled, hence `mmPerPx` in the
									     font size. -->
									<text
										x={mark.along_y ? point.x_mm : point.x_mm + 7 * mmPerPx}
										y={mark.along_y ? point.y_mm + 13 * mmPerPx : point.y_mm + 4 * mmPerPx}
										font-size={11 * mmPerPx}
										text-anchor={mark.along_y ? 'middle' : 'start'}
									>{i + 1}</text>
								</g>
							{/each}
						{/each}
					</g>
				{/if}

				<!-- The design. One scale transform converts Tats to mm; the path data itself
				     stays untouched as the engine gave it. -->
				{#if design.design}
					<g transform="scale({1 / design.design.units_per_mm})">
						{#each design.elements as element (element.id)}
							<!-- While moving, the shape follows the frame; without that the guide
							     lines point at an edge that is not there yet. -->
							<g transform={offset(element.id)}>
							{#if !element.hidden && element.image && design.strokeFor(element).visible}
								{#if outsiders.get(element.id)}
									<!-- The same message as for a path, but an image has no contour to
									     make glow: then the frame is the subject. -->
									<rect
										class="outside-glow"
										class:sheetedge={outsiders.get(element.id) === 'sheet'}
										x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
										y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
										width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
										height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
										fill="none"
										vector-effect="non-scaling-stroke"
									/>
								{/if}
								<!-- Images have no path; the pixels come from the API. The transform
								     above works in Tats, so scale back. -->
								<image
									href="/api/design/elements/{encodeURIComponent(element.id)}/image.png?v={design.revision}"
									x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
									y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
									width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
									height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
									preserveAspectRatio="none"
								/>
								<rect
									class="hit"
									class:passive={!selectTool}
									data-el={element.id}
									role="button"
									tabindex="0"
									aria-label={t('canvas.selectImage')}
									x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
									y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
									width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
									height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
									fill="transparent"
									onclick={(e) => {
										e.stopPropagation();
										if (bandJustEnded) {
											bandJustEnded = false;
											return;
										}
										if (e.shiftKey) design.toggle(element.id);
										else if (e.altKey) pickUnder(e, element.id);
										else design.select(element.id);
									}}
									oncontextmenu={(e) => {
										e.preventDefault();
										e.stopPropagation();
										// Right-clicking something that was not selected selects it
										// first: otherwise there is a menu over one shape that acts on
										// *another* shape.
										if (!design.isSelected(element.id)) design.select(element.id);
										onContextObject?.(e, stackAt(e.clientX, e.clientY));
									}}
									onkeydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											design.select(element.id);
										}
									}}
								/>
							{:else if !element.hidden && design.strokeFor(element).visible}
								<!-- The layer's colour, not the element's: that way you see at a glance
								     what is cut and what is engraved. Without a layer, grey dotted —
								     that shape is not burned.
								     Decision B4: the dotted line stays reserved for *that*. A layer set
								     to "does not burn" is a different state and gets a rendering of its
								     own — thinner and half transparent — so that you do see it lying
								     there but never mistake it for work that is going into the
								     machine. -->
								{@const streek = design.strokeFor(element)}
								{@const outside = outsiders.get(element.id)}
								{#if outside}
									<!-- Gap C2: a glow in the colour of the objection, running under
									     the shape. So the layer colour stays visible — you still have
									     to be able to see which layer the thing is in — but the shape
									     itself now carries the warning, and not only a line of text in
									     a panel you can collapse. -->
									<path
										class="outside-glow"
										class:sheetedge={outside === 'sheet'}
										d={element.path}
										fill="none"
										vector-effect="non-scaling-stroke"
									/>
								{/if}
								<!-- A grid layer burns the area away, not an outline. Showing that
								     as a line says something other than what happens, so such a shape
								     gets its area: in the layer colour, half transparent, so that you
								     still see through it what lies underneath and the contour itself
								     keeps carrying the layer colour. It stays one `fill` on the path
								     that is there anyway — no second drawing, no rasteriser in the
								     loop, so the cost per pointer move does not change. -->
								<!-- Bridges (tabs): the shape is drawn with the gaps in it, because that
								     is what the machine cuts. The gaps come out of the API as a second
								     path — the contour minus the bridges, carved on the parameter, so a
								     curve stays a curve. Measured: 149 characters of `d` become 331 for
								     a rectangle with four bridges, where the engine's own gapped
								     geometry would be 114,661.

								     Two paths and not one, because the fill must stay whole: a raster
								     layer burns the area, and an area with four notches in its outline
								     is not what happens. So the fill comes off the ideal contour and
								     only the stroke off the carved one. -->
								{@const gapped = element.bridges?.path ?? ''}
								<path
									class:area={streek.filled}
									class:gedempt={streek.dimmed}
									d={element.path}
									fill={streek.filled ? streek.color : 'none'}
									fill-rule="nonzero"
									stroke={gapped ? 'none' : streek.color}
									stroke-dasharray={streek.dashed ? '6 4' : undefined}
									stroke-opacity={streek.dimmed ? 0.4 : 1}
									stroke-width={design.isSelected(element.id) ? 2 : streek.dimmed ? 0.9 : 1.2}
									vector-effect="non-scaling-stroke"
								/>
								{#if gapped}
									<path
										class:gedempt={streek.dimmed}
										d={gapped}
										fill="none"
										stroke={streek.color}
										stroke-dasharray={streek.dashed ? '6 4' : undefined}
										stroke-opacity={streek.dimmed ? 0.4 : 1}
										stroke-width={design.isSelected(element.id) ? 2 : streek.dimmed ? 0.9 : 1.2}
										vector-effect="non-scaling-stroke"
									/>
								{/if}
								<!-- An invisible hit zone: a 1 px contour cannot be clicked, certainly
								     not on a touch screen. -->
								<!--
									Only a *filled* shape catches a click on its inside.

									This used to be `fill="transparent"`, and a transparent fill still
									catches the pointer: the whole inside of every closed shape was
									clickable. So anything drawn inside a rectangle — a hole, a label,
									a part nested to save material — could not be picked up at all: the
									rectangle lies over it and swallowed the click. The way a laser
									cutter works, an outline is a line and not a surface, and that is
									how LightBurn and Illustrator treat it too. Filled shapes keep
									their face, because for those the surface *is* the work: that is
									what a raster layer burns.
								-->
								<path
									class="hit"
									class:passive={!selectTool}
									data-el={element.id}
									d={element.path}
									fill={streek.filled ? 'transparent' : 'none'}
									fill-rule="nonzero"
									stroke="transparent"
									stroke-width="12"
									vector-effect="non-scaling-stroke"
									role="button"
									tabindex="0"
									aria-label={t('canvas.selectShape', { name: elementName(element) })}
									aria-pressed={design.isSelected(element.id)}
									onclick={(e) => {
										e.stopPropagation();
										// The click after a drag frame must not replace the selection
										// that frame has just made.
										if (bandJustEnded) {
											bandJustEnded = false;
											return;
										}
										// Shift keeps the existing selection.
										if (e.shiftKey) design.toggle(element.id);
										// Alt goes one shape deeper into the pile under the pointer.
										else if (e.altKey) pickUnder(e, element.id);
										else design.select(element.id);
									}}
									ondblclick={(e) => {
										// A node exactly where you double-clicked, the way every drawing
										// program does it. Only with the node tool in hand and only on
										// the shape being edited: a double-click elsewhere means nothing
										// here and must not silently change a different shape.
										if (tool !== 'nodes' || !design.isSelected(element.id)) return;
										e.preventDefault();
										e.stopPropagation();
										addNodeAt(e);
									}}
									oncontextmenu={(e) => {
										e.preventDefault();
										e.stopPropagation();
										if (!design.isSelected(element.id)) design.select(element.id);
										onContextObject?.(e, stackAt(e.clientX, e.clientY));
									}}
									onkeydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											design.select(element.id);
										}
									}}
								/>
							{/if}
							</g>
						{/each}
					</g>

					<!-- The layer number beside the shape (gap C6). Outside the Tat scale,
					     because the text has to stay the same size at every zoom level. The
					     figure gets a border in the bed colour (`paint-order`), otherwise it
					     disappears against a grid line or against the shape below it. -->
					{#each layerLabels as label (label.id)}
						<!-- @svg-space: millimetre space, not CSS pixels; `labelSize` is the
						     converted-back screen size of --text-xs. -->
						<text
							style="font-size: {labelSize}px; fill: {label.colour}; fill-opacity: {label.dim ? 0.5 : 1}"
							class="layer-number mono"
							x={label.x + 2 * mmPerPx}
							y={label.y - 3 * mmPerPx}
						>{label.number}</text>
					{/each}

					<!-- Selection contour: the kerf line. Statically dashed, and only animated
					     while you drag — as DESIGN-SYSTEM.md prescribes. -->
					{#if outline && frameBox}
						<!-- While rotating the whole frame turns along as a preview; the real
						     shape follows as soon as the engine has applied it. -->
						<g
							class="selection"
							transform={rotation && center
								? `rotate(${rotation} ${center.x} ${center.y})`
								: undefined}
						>
							<rect
								class:kerf-anim={drag !== null}
								x={frameBox.x}
								y={frameBox.y}
								width={frameBox.width}
								height={frameBox.height}
							/>
							<!-- Drag surface: the whole selection frame moves the element.
							     Not with the node tool in hand: there you work on the points, and
							     this surface lies over the contour. Measured: the double-click
							     that should put a node on the line landed on this rectangle
							     instead, so adding a node did nothing at all. Moving a shape is
							     the arrow's job, one tool to the left. -->
							{#if canEdit && tool !== 'nodes' && !selectionLocked}
								<!-- Keyboard equivalent: the arrow keys move the
								     selectie (0,1 mm, met shift 1 mm). -->
								<rect
									class="grab"
									role="button"
									tabindex="-1"
									aria-label={t('canvas.dragMove')}
									x={frameBox.x}
									y={frameBox.y}
									width={frameBox.width}
									height={frameBox.height}
									onpointerdown={(e) => startDrag(e, 'move')}
									oncontextmenu={(e) => {
										// The selection's drag surface lies above the shapes, so a
										// right-click inside the selection lands here and not on the
										// contour below it. Without this rule you got the canvas menu
										// in the middle of your own selection.
										e.preventDefault();
										e.stopPropagation();
										onContextObject?.(e, stackAt(e.clientX, e.clientY));
									}}
									onpointermove={moveDrag}
									onpointerup={endDrag}
								/>
							{/if}
							{#if canEdit && center && !selectionLocked}
							<!-- Rotation handle: a stem above the frame, as a corner handle is for
							     resizing. Shift snaps to 15 degrees. -->
							<line
								class="stalk"
								x1={center.x}
								y1={frameBox.y}
								x2={center.x}
								y2={frameBox.y - stalk}
							/>
							<circle
								class="rotator"
								cx={center.x}
								cy={frameBox.y - stalk}
								r={handleR}
							/>
							<!-- A wider hit zone around it: at this scale 2 mm is only a few
							     pixels, and that cannot be grabbed with a mouse, let alone with a
							     finger. -->
							<circle
								class="rotator-hit"
								role="button"
								tabindex="-1"
								aria-label={t('canvas.dragRotate')}
								cx={center.x}
								cy={frameBox.y - stalk}
								r={hitR}
								onpointerdown={(e) => startDrag(e, 'rotate')}
								onpointermove={moveDrag}
								onpointerup={endDrag}
							/>
						{/if}
						<!-- On a line the end points are the handles; corner handles of an
						     imaginary frame would lie on top of them. -->
						{#each selectedLine || selectionLocked ? [] : [[frameBox.x, frameBox.y], [frameBox.x + frameBox.width, frameBox.y], [frameBox.x, frameBox.y + frameBox.height], [frameBox.x + frameBox.width, frameBox.y + frameBox.height]] as [hx, hy], corner (corner)}
								<rect
									class="handle"
									x={hx - handleR}
									y={hy - handleR}
									width={handleR * 2}
									height={handleR * 2}
								/>
								<!-- The hit zone is wider than the handle: 10 px visible is exactly
								     enough to see, and far too little to hit with a finger. -->
								<rect
									class="handle-hit"
									class:grabbable={canEdit}
									role="button"
									tabindex="-1"
									aria-label={t('canvas.dragScale')}
									x={hx - hitR}
									y={hy - hitR}
									width={hitR * 2}
									height={hitR * 2}
									onpointerdown={(e) => startDrag(e, 'scale', corner)}
									onpointermove={moveDrag}
									onpointerup={endDrag}
								/>
							{/each}
							<text
								class="mono"
								x={frameBox.x + frameBox.width / 2}
								y={frameBox.y + frameBox.height + labelSize * 1.3}
								text-anchor="middle"
								style="font-size: {labelSize}px"
							>
								{i18n.number(Math.abs(outline.width), 1)} × {i18n.number(Math.abs(outline.height), 1)} mm
							</text>
						</g>
					{/if}
				{/if}

				<!-- Guide lines: *what* something snaps to. Without this feedback snapping is
				     a riddle — you see something jump away and do not know where to. They
				     catch no pointer. -->
				<!-- The label is at full --text-xs (11 px): making it smaller to win room is
				     exactly what the pixel judge rejects. -->
				{#each guideLines as line (line.key)}
					<g class="guide">
						<line x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2} />
						<text
							class="mono"
							x={line.tx}
							y={line.ty}
								text-anchor={line.anchor}
							style="font-size: {labelSize}px"
						>
							{line.label}
						</text>
					</g>
				{/each}

				{#if lineStart && hover}
					<line
						class="pending"
						x1={lineStart.x}
						y1={lineStart.y}
						x2={hover.x}
						y2={hover.y}
					/>
				{/if}

				{#if endpointPreview}
					<!-- The line itself follows the handle while dragging; a jumping dot alone
					     says nothing about what you are making. -->
					<line
						class="pending"
						x1={endpointPreview.x1_mm}
						y1={endpointPreview.y1_mm}
						x2={endpointPreview.x2_mm}
						y2={endpointPreview.y2_mm}
					/>
					<!-- `.measure-label` and not `.measure`: that second one is the dotted
					     measuring line, and text with a dotted border around it is
					     unreadable. -->
					<text
						class="mono measure-label"
						x={(endpointPreview.x1_mm + endpointPreview.x2_mm) / 2}
						y={(endpointPreview.y1_mm + endpointPreview.y2_mm) / 2 - labelSize}
						text-anchor="middle"
						style="font-size: {labelSize}px"
					>
						{i18n.number(
							Math.hypot(
								endpointPreview.x2_mm - endpointPreview.x1_mm,
								endpointPreview.y2_mm - endpointPreview.y1_mm
							),
							1
						)} mm
					</text>
				{/if}

				{#if lineHandles}
					<!-- You grab a line by an end point, not by a corner of an imaginary
					     frame. -->
					{#each lineHandles as point, index (index)}
						<circle class="endpoint" cx={point.x} cy={point.y} r={handleR} />
						<circle
							class="grip"
							role="button"
							tabindex="-1"
							aria-label={t('canvas.dragEndpoint', { n: index + 1 })}
							cx={point.x}
							cy={point.y}
							r={hitR}
							onpointerdown={(e) => startEndpoint(e, index)}
							onpointermove={moveEndpoint}
							onpointerup={endEndpoint}
						/>
					{/each}
				{/if}

				{#if tool === 'nodes' && nodePoints.length}
					{#if controlPreview}
						<!-- The piece being bent, while it is being bent. -->
						<path class="pen-line" d={controlPreview} fill="none" />
					{/if}
					{#each handleSegments as segment (segment.index)}
						{#each segment.controls as control (control.which)}
							{@const live =
								controlDrag?.segment === segment.index && controlDrag.which === control.which
									? controlDrag
									: null}
							{@const at = live ? { x: live.x, y: live.y } : { x: control.x_mm, y: control.y_mm }}
							{@const anchor =
								nodePoints.find(
									(p) => p.index === (control.which === 1 ? segment.start : segment.end)
								) ?? null}
							{#if anchor}
								<!-- A handle without its tether is a dot in the air: the line to the
								     point it belongs to is what says *which* piece it bends. -->
								<line class="tether" x1={anchor.x_mm} y1={anchor.y_mm} x2={at.x} y2={at.y} />
							{/if}
							<!-- Square and not round, so a handle can never be mistaken for a node —
							     the two lie close together and mean different things. -->
							<rect
								class="handle-square"
								x={at.x - handleR}
								y={at.y - handleR}
								width={handleR * 2}
								height={handleR * 2}
							/>
							<circle
								class="grip"
								role="button"
								tabindex="-1"
								aria-label={t('canvas.dragHandle', { n: segment.index + 1 })}
								cx={at.x}
								cy={at.y}
								r={hitR}
								onpointerdown={(e) => startControl(e, segment, control)}
								onpointermove={dragControl}
								onpointerup={endControl}
							/>
						{/each}
					{/each}
					{#each nodePoints as point (point.index)}
						{@const live = nodeDrag?.index === point.index ? nodeDrag : null}
						<circle
							class="knot"
							class:picked={nodePicked === point.index}
							cx={live ? live.x : point.x_mm}
							cy={live ? live.y : point.y_mm}
							r={handleR}
						/>
						<circle
							class="grip"
							role="button"
							tabindex="0"
							aria-label={t('canvas.dragNode', { n: point.index + 1 })}
							aria-pressed={nodePicked === point.index}
							cx={live ? live.x : point.x_mm}
							cy={live ? live.y : point.y_mm}
							r={hitR}
							onpointerdown={(e) => startNode(e, point.index)}
							onpointermove={moveNode}
							onpointerup={endNode}
							onkeydown={(e) => pickNodeByKey(e, point.index)}
							oncontextmenu={(e) => {
								e.preventDefault();
								e.stopPropagation();
								nodePicked = point.index;
								onContextNode?.(e, point.index);
							}}
						/>
					{/each}
				{/if}

				{#if tool === 'pen' && (penPoints.length || penPress)}
					<!-- The line as a path and no longer a polyline: with a curve in it a
					     polyline would show a straight line where the machine is going to cut
					     a curve, and the preview is the only thing you have to judge it by. -->
					<path class="pen-line" d={penLine} fill="none" />
					{#each penPress ? [...penPoints, penPress.point] : penPoints as point, index (index)}
						<!-- `handleR` and not a fixed number: 1.6 in this SVG is 1.6 mm, so the
						     points of the pen drawing grew with the zoom and, zoomed in, covered
						     the path you were laying down. -->
						<circle class="pen-dot" cx={point.x} cy={point.y} r={handleR} />
						{#if point.handle}
							<!-- Both arms of the handle: the one you are pulling and its mirror,
							     because the mirror is what bends the piece you have already laid
							     down and you have to be able to see it doing that. -->
							<line
								class="pen-arm"
								x1={2 * point.x - point.handle.x}
								y1={2 * point.y - point.handle.y}
								x2={point.handle.x}
								y2={point.handle.y}
							/>
							<circle class="pen-grip" cx={point.handle.x} cy={point.handle.y} r={handleR} />
							<circle
								class="pen-grip"
								cx={2 * point.x - point.handle.x}
								cy={2 * point.y - point.handle.y}
								r={handleR}
							/>
						{/if}
					{/each}
				{/if}

				{#if tool === 'measure' && measureFrom}
					{@const to = measureTo ?? hover ?? measureFrom}
					<line
						class="measure"
						x1={measureFrom.x}
						y1={measureFrom.y}
						x2={to.x}
						y2={to.y}
					/>
					<text
						class="measure-label"
						x={(measureFrom.x + to.x) / 2}
						y={(measureFrom.y + to.y) / 2 - labelSize * 0.6}
						text-anchor="middle"
						style="font-size: {labelSize}px"
					>
						{i18n.number(Math.hypot(to.x - measureFrom.x, to.y - measureFrom.y), 1)} mm
					</text>
				{/if}

				{#if cropping}
					<!-- Catches the pointer, otherwise the drag starts on the image itself. -->
					<rect
						class="crop-catch"
						x="0"
						y="0"
						width={bed.width}
						height={bed.height}
						onpointerdown={(e) => startBand(e as PointerEvent)}
						onpointermove={(e) => moveBand(e as PointerEvent)}
						onpointerup={endBand}
						role="presentation"
					/>
				{/if}
				{#if band}
					<rect
						class="band"
						x={Math.min(band.x1, band.x2)}
						y={Math.min(band.y1, band.y2)}
						width={Math.abs(band.x2 - band.x1)}
						height={Math.abs(band.y2 - band.y1)}
					/>
				{/if}

				<!-- The origin (gap C5). LightBurn puts a fixed corner mark with axis letters
				     there, and with reason: with us 0,0 coincided with the head marker, so as
				     soon as the head moved there was nothing left saying where the machine
				     counts from. This mark never moves.

				     All measures converted back to screen pixels — in an SVG that measures in
				     millimetres "6" is six millimetres, and then the mark grows with the zoom
				     until it covers half the bed. -->
				<!-- @svg-space: axis letters in millimetre space, converted back to the screen
				     size of --text-xs. -->
				<g class="originMark" aria-hidden="true">
					<!-- Two axes with an arrowhead: X to the right, Y downwards. That is the
					     direction in which the machine counts, so that is what is drawn. -->
					<line x1="0" y1="0" x2={14 * mmPerPx} y2="0" />
					<line x1="0" y1="0" x2="0" y2={14 * mmPerPx} />
					<path class="point" d="M{14 * mmPerPx} 0 L{10 * mmPerPx} {-2.4 * mmPerPx} L{10 * mmPerPx} {2.4 * mmPerPx} Z" />
					<path class="point" d="M0 {14 * mmPerPx} L{-2.4 * mmPerPx} {10 * mmPerPx} L{2.4 * mmPerPx} {10 * mmPerPx} Z" />
					<!-- A little square on the point itself, not a ring: the head marker is
					     already a ring in the accent, and those two right on top of each other
					     (after homing the head is exactly here) could not be told apart. -->
					<rect
						class="knoop"
						x={-1.8 * mmPerPx}
						y={-1.8 * mmPerPx}
						width={3.6 * mmPerPx}
						height={3.6 * mmPerPx}
					/>
					<text class="as mono" x={18.5 * mmPerPx} y={3.5 * mmPerPx} style="font-size: {labelSize}px">X</text>
					<text class="as mono" x={2.5 * mmPerPx} y={21 * mmPerPx} style="font-size: {labelSize}px">Y</text>
				</g>

				<!-- The user's zero point (gap J12).
				     A cross with an open centre, in --text-1 and not in the accent: the accent
				     is the head and the mark at 0,0 (C5) is *also* a fixed sign, so this third
				     point has to be distinguishable from both. All measures converted back to
				     screen pixels — otherwise the cross grows with the zoom. -->
				{#if originPoint}
					<g class="origin-mark" aria-hidden="true">
						<line
							x1={originPoint.x_mm - 9 * mmPerPx}
							y1={originPoint.y_mm}
							x2={originPoint.x_mm - 3 * mmPerPx}
							y2={originPoint.y_mm}
						/>
						<line
							x1={originPoint.x_mm + 3 * mmPerPx}
							y1={originPoint.y_mm}
							x2={originPoint.x_mm + 9 * mmPerPx}
							y2={originPoint.y_mm}
						/>
						<line
							x1={originPoint.x_mm}
							y1={originPoint.y_mm - 9 * mmPerPx}
							x2={originPoint.x_mm}
							y2={originPoint.y_mm - 3 * mmPerPx}
						/>
						<line
							x1={originPoint.x_mm}
							y1={originPoint.y_mm + 3 * mmPerPx}
							x2={originPoint.x_mm}
							y2={originPoint.y_mm + 9 * mmPerPx}
						/>
						<text
							class="as mono"
							x={originPoint.x_mm + 11 * mmPerPx}
							y={originPoint.y_mm - 5 * mmPerPx}
							style="font-size: {labelSize}px">0</text
						>
					</g>
					{#if burnsHere}
						<!-- Where the work lands. Without this frame the zero point only says
						     that something shifts and not where to, and then you have to work it
						     out while what you wanted was to be able to look. -->
						<g class="burns-hier" aria-hidden="true">
							<!-- The sheet moves along. That is not decoration but the meaning of
							     the zero point: you put it on the corner of the material that is in
							     there, so the material is there. Without this frame the work sat
							     visibly beside the sheet while "off the sheet" was reported nowhere
							     — a drawing that contradicts itself. -->
							{#if sheet}
								<rect
									class="sheetsketch"
									x={originPoint.x_mm}
									y={originPoint.y_mm}
									width={sheet.width}
									height={sheet.height}
									vector-effect="non-scaling-stroke"
								/>
							{/if}
							<rect
								x={burnsHere.x}
								y={burnsHere.y}
								width={burnsHere.width}
								height={burnsHere.height}
								vector-effect="non-scaling-stroke"
							/>
							<text
								class="mono"
								x={burnsHere.x + 2 * mmPerPx}
								y={burnsHere.y - 3 * mmPerPx}
								style="font-size: {labelSize}px">{t('canvas.burnsHere')}</text
							>
						</g>
					{/if}
				{/if}

				<!-- The fresh piece, on top: where the head is *now*. Kept short (see
				     FRESH_POINTS) so that the difference stays between "it has been here"
				     en "hier is hij now". -->
				{#if spoorKop}
					<g class="trail" aria-hidden="true">
						<polyline class="fresh" points={spoorKop} vector-effect="non-scaling-stroke" />
					</g>
				{/if}

				{#if head}
					<!-- Live head position. There is no design to show yet: phase 1 only reads
					     status, the canvas itself comes in phase 3. -->
					<g class="head">
						<line x1={head[0]} y1="0" x2={head[0]} y2={bed.height} />
						<line x1="0" y1={head[1]} x2={bed.width} y2={head[1]} />
						<!-- The head is a screen marker too, not a 4 mm shape: zoomed in twenty
						     times it would otherwise be a circle 26 cm across. -->
						<circle cx={head[0]} cy={head[1]} r={7 * mmPerPx} />
						<!-- The job's progress, as a ring around the head (gap J3). This is the
						     only number the engine really gives, and it sits where you are
						     looking during a job anyway. Starting at the top and running
						     clockwise, because everybody reads that as "how far". -->
						{#if progressPart !== null}
							<circle
								class="ring-baan"
								cx={head[0]}
								cy={head[1]}
								r={ringR}
								vector-effect="non-scaling-stroke"
							/>
							<circle
								class="ring"
								cx={head[0]}
								cy={head[1]}
								r={ringR}
								vector-effect="non-scaling-stroke"
								stroke-dasharray="{ringCircumference * progressPart} {ringCircumference}"
								transform="rotate(-90 {head[0]} {head[1]})"
							/>
						{/if}
					</g>
				{/if}
			</svg>
		</div>
	</div>

	<div class="zoom">
		<!-- Layer numbers beside the shape on or off (gap C6). On by default, because the
		     number is the safety net the design system prescribes; off is possible,
		     because with fifty shapes on a sheet it is a cloud of figures. -->
		<button
			class="snap"
			class:on={numbersOn}
			aria-pressed={numbersOn}
			title={numbersOn ? t('canvas.layerNumbers.on') : t('canvas.layerNumbers.off')}
			aria-label={t('action.layerNumbers')}
			onclick={nummersSchakel}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M5 9h14M5 15h14M10 4 8 20M17 4l-2 16" />
			</svg>
		</button>
		<span class="scheiding" aria-hidden="true"></span>
		<!-- Snapping on or off. A magnet, because that is the image every drawing program
		     uses for it; the state is there in words in the title, because an icon alone
		     does not say whether it is on or off. -->
		<button
			class="snap"
			class:on={snapOn}
			aria-pressed={snapOn}
			title={snapOn ? t('canvas.snap.on') : t('canvas.snap.off')}
			aria-label={t('action.snap')}
			onclick={snapToggle}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M6 4v8a6 6 0 0 0 12 0V4" />
				<path d="M6 10h4M14 10h4" />
			</svg>
		</button>
		<span class="scheiding" aria-hidden="true"></span>
		<button title={t('canvas.zoomOut.title')} aria-label={t('canvas.zoomOut')} onclick={() => zoomAt(1 / 1.25)}>−</button>
		<!-- The percentage is now a *real* scale (100% = true size) and at the same time
		     the way into all the zoom states. Before this there was a button here saying
		     "100%" that did "fit the bed", and "to the selection" and a real 1:1 were only
		     reachable through an undocumented shortcut.
		     One dropdown instead of four separate buttons: the zoom bar sits over the
		     canvas and every button added to it covers work. -->
		<button
			class="val mono"
			aria-haspopup="menu"
			aria-expanded={zoomMenu}
			title={t('canvas.zoomLevels')}
			onclick={(e) => {
				const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
				zoomMenuAt = { x: box.left, y: box.top - 8 };
				zoomMenu = !zoomMenu;
			}}
		>
			{procent}%
			<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 15 6-6 6 6" /></svg>
		</button>
		<button class="fit" title={t('canvas.fit.title')} onclick={passend}>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>{t('canvas.fit')}		</button>
		<button title={t('canvas.zoomIn.title')} aria-label={t('canvas.zoomIn')} onclick={() => zoomAt(1.25)}>+</button>
	</div>

	{#if zoomMenu}
		<Menu
			menu={zoomStanden}
			x={zoomMenuAt.x}
			y={zoomMenuAt.y}
			upward
			onClose={() => (zoomMenu = false)}
		/>
	{/if}

	{#if !device}
		<p class="empty">{t('canvas.noMachine')}</p>
	{/if}
</div>

<!-- Gap C2 in words, as a strip of its own under the bed.
     The glow on the bed is the first warning, but colour must never carry it
     alone: whoever stands by a window in the workshop is the first to lose that
     glow, and with deuteranopia red on an amber line is no difference. Two
     separate sentences, because outside the bed (the head does not get there) and
     outside the sheet (there is no material there) are two problems.

     Deliberately not a floating card on the canvas: there it collided with the
     camera pill on the left and the zoom bar on the right — measured at 1024, the
     message ended up half behind it. A strip in the flow covers nothing and
     disappears again as soon as the work is inside the edges. -->
<!-- Everything hanging below the bed in one block, and that block measures
     itself. The camera pill floats above the canvas at a fixed distance from the
     bottom and reckons with `--palette-height`; with only the colour strip in that
     measurement the pill lay over this warning the moment it appeared (measured at
     1440: 34 px of overlap). One measurement for the whole bottom edge is the only
     one that holds, because there can be more than one strip. -->
<div class="onderrand" bind:clientHeight={bottomEdgeHeight}>
<!-- The node tool is pressed but does nothing: say why. Without this line the
     difference between "you still have to pick a shape" and "this shape cannot do
     it" was invisible, and both looked like a broken tool. -->
<!-- And the same for a tool that *is* working: the pen and the node tool both do more
     than a click, and a key nobody knows about is a key nobody uses. Measured on the pen
     before this: clicking gave corners and nothing on screen said that dragging gives a
     curve or that Enter is what finishes the line. -->
{#if tool === 'pen'}
	<p class="tool-hint" role="status">{t('canvas.pen.hint')}</p>
{:else if nodeReason}
	<p class="tool-hint" role="status">
		{#if nodeReason === 'none'}
			{t('canvas.nodes.pickOne')}
		{:else if nodeReason === 'many'}
			{t('canvas.nodes.tooMany', { n: design.selectedIds.length })}
		{:else if nodeReason === 'failed'}
			{t('canvas.nodes.failed')}
		{:else}
			{t('canvas.nodes.noPoints')}
		{/if}
	</p>
{:else if tool === 'nodes' && nodePoints.length}
	<p class="tool-hint" role="status">{t('canvas.nodes.hint')}</p>
{/if}
<!-- What the trace on the bed is, in words (gap J3).
     A line growing across the bed during a job reads as "this has been cut
     already" — and we cannot make that good: `driver;position` does not say
     whether the laser was on, so the jump between two shapes is just as much part
     of it. An image that promises more than it knows is worse than no image, so
     here is what you are looking at. Only during a job; outside one there is
     nothing to say. -->
{#if job && trail}
	<p class="trail-hint" role="status">
		<span class="trail-mark" aria-hidden="true"></span>
		<!-- All the text in one child: with loose text nodes beside it every piece
		     becomes a flex item of its own, and then "62%" sat in a column of its own
		     next to a broken-off sentence on a tablet (measured at 1024). -->
		<span
			>{t('canvas.trace')}{#if progressPart !== null}{' '}{t('canvas.traceProgress', {
					percent: Math.round(progressPart * 100)
				})}{/if}</span
		>
	</p>
{/if}
{#if plateTooBig || shapesOffBed || offSheet}
	<div class="outside-strip" role="status">
		{#if plateTooBig}
			<!-- Task 15: with a plate that is itself larger than the bed this is not a
			     mistake but a way of working — the message becomes the offer to burn in
			     tiles, instead of the ordinary "falls outside the bed" line (which
			     would go off on nearly every shape here anyway). -->
			<span class="row aanbod">
				<span class="sign" aria-hidden="true">!</span>
				<span>{t('canvas.tooBig')}</span>
				<button
					class="btn subtle"
					type="button"
					disabled={tiling?.busy || !sheetId}
					onclick={() => sheetId && tiling?.enableAndStart(sheetId)}
				>
					{t('canvas.burnInTiles')}
				</button>
			</span>
		{:else if shapesOffBed}
			<span class="row bededge">
				<span class="sign" aria-hidden="true">!</span>
				<span>{t('canvas.outsideBed', { n: shapesOffBed })}</span>
			</span>
		{/if}
		{#if offSheet}
			<span class="row sheetedge">
				<span class="sign" aria-hidden="true">!</span>
				<span
					>{t('canvas.outsideSheet', {
						n: offSheet,
						sheet: sheet ? sheet.name : t('canvas.theSheet')
					})}</span
				>
			</span>
		{/if}
	</div>
{/if}

<!-- Decision B2: the colour strip belongs *under* the canvas, not in the panel.
     There it belongs to the shape you are holding, and not to a tab you have to
     look up first. A row of its own, no floating bar across the bed: it must never
     cover something you are aligning. -->
<LayerPalette {design} {edits} {canEdit} onChanged={() => onEdited?.()} />
</div>

<style>
	/* As long as space is held the cursor says what a click does now. Without that
	   difference the canvas looks broken: you click and no frame appears. */
	.canvas-wrap.panning,
	.canvas-wrap.panning * {
		cursor: grab;
	}
	.canvas-wrap {
		flex: 1;
		position: relative;
		/* v2: the bed lies somewhere. A gradient in the surroundings and one shadow under
		   it — not three. */
		background: var(--stage);
		overflow: hidden;
	}
	.ruler-x,
	.ruler-y {
		position: absolute;
		/* Without this an inline SVG falls back on its default size of 300x150 and the
		   ruler stops halfway. */
		display: block;
		width: 100%;
		height: 100%;
		background: var(--surface-1);
		color: var(--text-2);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		z-index: 2;
		user-select: none;
	}
	.ruler-x {
		top: 0;
		left: 20px;
		width: calc(100% - 20px);
		height: 20px;
		border-bottom: 1px solid var(--line);
	}
	.ruler-y {
		top: 20px;
		left: 0;
		width: 20px;
		height: calc(100% - 20px);
		border-right: 1px solid var(--line);
	}
	.ruler-x line,
	.ruler-y line {
		stroke: var(--line-strong, var(--line));
		stroke-width: 1;
		shape-rendering: crispEdges;
	}
	.ruler-x .here,
	.ruler-y .here {
		stroke: var(--accent);
	}
	/* Off the bed the scale runs on, but more softly: the number is there when you need
	   it and does not impose itself when you are working inside the bed (C4). */
	.ruler-x line.outside,
	.ruler-y line.outside {
		stroke: color-mix(in srgb, var(--line-strong, var(--line)) 55%, transparent);
	}
	.ruler-x text.outside,
	.ruler-y text.outside {
		fill: color-mix(in srgb, var(--text-2) 60%, transparent);
	}
	/* The band that says how far the bed reaches. No border: that would be a fourth kind
	   of line on a 20 px ruler. */
	.werkgebied {
		fill: color-mix(in srgb, var(--text-2) 8%, transparent);
	}
	.ruler-x text,
	.ruler-y text {
		/* Numbers on a ruler are values: mono with tabular figures, otherwise the scale
		   jumps while panning. */
		font-variant-numeric: tabular-nums;
		fill: var(--text-2);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		dominant-baseline: hanging;
	}
	.corner {
		position: absolute;
		top: 0;
		left: 0;
		width: 20px;
		height: 20px;
		z-index: 3;
		display: grid;
		place-items: center;
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--text-2);
		background: var(--surface-1);
		border-right: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
		user-select: none;
	}
	.canvas {
		position: absolute;
		inset: 20px 0 0 20px;
	}
	.bed {
		background: var(--bed);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		/* Absolute at a computed place, not centred by the grid: as soon as the bed
		   became bigger than the area the browser clamped the left edge, and then every
		   conversion from pixels to millimetres was wrong — rulers, pointer position and
		   zooming to the cursor all three went wrong. */
		position: absolute;
		/* Two levels, as in every drawing program: the main lines are on the ruler's
		   step, the fine subdivision on a fifth of it. The colour comes from the token;
		   the fine line is the same colour, diluted. */
		background-image:
			linear-gradient(var(--line) 1px, transparent 1px),
			linear-gradient(90deg, var(--line) 1px, transparent 1px),
			linear-gradient(color-mix(in srgb, var(--line) 45%, transparent) 1px, transparent 1px),
			linear-gradient(90deg, color-mix(in srgb, var(--line) 45%, transparent) 1px, transparent 1px);
		box-shadow: var(--lift-1), 0 10px 24px rgb(16 20 26 / 0.10);
	}
	.camera {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: fill;
		pointer-events: none;
		user-select: none;
	}
	.sheet {
		position: absolute;
		left: 0;
		top: 0;
		border: 1px dashed var(--accent);
		background: color-mix(in srgb, var(--accent) 4%, transparent);
		pointer-events: none;
	}
	.sheet-label {
		font-variant-numeric: tabular-nums;
		position: absolute;
		left: 3px;
		bottom: 2px;
		font-size: var(--text-xs);
		color: var(--accent);
	}
	.bed-label {
		font-variant-numeric: tabular-nums;
		position: absolute;
		top: -22px;
		right: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.blank {
		position: absolute;
		inset: 0;
		display: grid;
		align-content: center;
		justify-items: center;
		gap: var(--space-2);
		padding: var(--space-4);
		text-align: center;
		pointer-events: none;
		user-select: none;
	}
	.blank h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--text-1);
	}
	.blank p {
		max-width: 34ch;
		font-size: var(--text-sm);
		line-height: 1.45;
		color: var(--text-2);
	}
	/* The origin (C5). Deliberately *not* in the accent and not in red: the accent is
	   the head marker — that was the very confusion — and in this system red means
	   danger. This is a fixed point on the machine, so the app's text colour, half
	   transparent so that it never shouts above the work. */
	.originMark {
		pointer-events: none;
	}
	.originMark line {
		stroke: var(--text-1);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
		opacity: 0.55;
	}
	.originMark .point {
		fill: var(--text-1);
		opacity: 0.55;
	}
	.originMark .knoop {
		fill: var(--text-1);
		opacity: 0.8;
	}
	.originMark text {
		fill: var(--text-1);
		opacity: 0.75;
		font-family: var(--font-mono);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	/* A shape in a grid layer: that burns its area away, so we show the area. Half
	   transparent, because you have to be able to see through it what lies underneath.

	   The opacity differs per theme, and that is not taste but measurement. The same 38%
	   gave a contrast of 2.96:1 on the light bed and only 1.68:1 on the dark one — the
	   same fill that convinces in light is a suspicion in dark. At 62% dark comes to
	   2.12:1. It cannot go much higher: on a dark bed even a fully opaque layer colour
	   only reaches ~2.65:1, and the area must not become opaque. The contour carries the
	   shape; the fill only says what happens to it. */
	.area {
		fill-opacity: 0.38;
	}

	/* A layer set to "does not burn": visible, never to be mistaken for work that is
	   going into the machine. The same rule as for the line beside it. */
	.area.gedempt {
		fill-opacity: 0.14;
	}

	:global([data-theme='dark']) .area {
		fill-opacity: 0.62;
	}

	:global([data-theme='dark']) .area.gedempt {
		fill-opacity: 0.24;
	}

	/* The layer number beside the shape (C6). The same colour as the line, with a border
	   in the bed colour around it — otherwise an 8 on a grid line reads as a 3. */
	.layer-number {
		pointer-events: none;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	/* Off the bed or off the sheet (C2): a glow *under* the shape, so that the layer
	   colour itself stays readable. Two colours, two meanings — red for "the head does
	   not go there", amber for "there is no material there". */
	.outside-glow {
		stroke: var(--danger-solid);
		stroke-width: 6;
		stroke-opacity: 0.32;
		stroke-linejoin: round;
		pointer-events: none;
	}
	/* Off the sheet: amber *and* dashed. Two encodings, because amber on a yellow layer
	   line (--layer-3) is a difference that disappears under deuteranopia and in bright
	   workshop light. Dashed also suits what it says: the material under this shape
	   stops. The shape itself stays solid — on this canvas dashed lines mean "is in no
	   layer". */
	.outside-glow.sheetedge {
		stroke: var(--warn-solid);
		stroke-dasharray: 3 3;
		stroke-opacity: 0.55;
	}
	.outside-strip {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-top: 1px solid var(--line);
		background: var(--surface-1);
	}
	.outside-strip .row {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		padding-left: var(--space-2);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-1);
		border-left: 4px solid var(--danger-solid);
	}
	.outside-strip .row.sheetedge {
		border-left-color: var(--warn-solid);
	}
	/* The sign is the second encoding *beside* the colour: printed in black and white it
	   is still an exclamation mark in a circle. */
	.outside-strip .sign {
		flex: none;
		width: 16px;
		height: 16px;
		margin-top: 1px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		font-weight: 700;
		font-size: var(--text-xs);
		color: var(--on-color);
		background: var(--danger-solid);
	}
	.outside-strip .row.sheetedge .sign {
		background: var(--warn-solid);
		color: var(--void);
	}
	/* Task 15: this is not an error but an offer, so the accent instead of the danger or
	   warning red, and a button with it instead of a sentence alone. */
	.outside-strip .row.aanbod {
		align-items: center;
		border-left-color: var(--accent);
	}
	.outside-strip .row.aanbod .sign {
		background: var(--accent);
		color: var(--on-color);
	}
	.head line {
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		opacity: 0.4;
	}
	.head circle {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
	}
	/* ── Progress during a job (gap J3) ───────────────────────────────────────
	   The trail is thin and faint: it is context under the work, not a second drawing on
	   top of it. Deliberately in --text-2 and not in the accent or a layer colour — the
	   accent is the head, and a layer colour would claim this piece was burned in *that*
	   layer, and we do not know that. */
	/* The path covered: wide and soft, running under the design. Wide enough to read on a
	   zoomed-out bed too, soft enough not to crowd out the layer colour above it. */
	.trail-baan {
		fill: none;
		stroke: var(--accent);
		stroke-width: 6;
		stroke-opacity: 0.38;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	/* The tile division (Task 15). The tile whose turn it is gets no wash — it is simply
	   there, in its own layer colours. The rest is muted with a wash in the bed colour:
	   still visible, not to be mistaken for where the head is now. A finished tile is a
	   little less dimmed than what is still to come, so that "already burned" and "still
	   coming" can be told apart without the step list too. */
	.tile-area {
		fill: color-mix(in oklab, var(--bed) 62%, transparent);
		pointer-events: none;
	}
	.tile-area.tile-ready {
		fill: color-mix(in oklab, var(--bed) 82%, transparent);
	}
	.tile-seam {
		stroke: var(--text-2);
		stroke-width: 1.4;
		stroke-dasharray: 6 4;
		stroke-opacity: 0.7;
		pointer-events: none;
	}
	.tile-mark {
		pointer-events: none;
		/* Not the marks of the seam whose turn it is now. Without that difference three
		   tiles give four marks called 1, 2, 1, 2, and a number is as confusing as a word
		   for a position. When no series is running there is no "now" either and they all
		   state equally strong — then this is a plan. */
		opacity: 0.35;
	}
	.tile-mark.active {
		opacity: 1;
	}
	.tile-mark circle {
		fill: none;
		stroke: var(--text-1);
		stroke-width: 1.4;
		stroke-opacity: 0.75;
		vector-effect: non-scaling-stroke;
	}
	.tile-mark line {
		stroke: var(--text-1);
		stroke-width: 1.4;
		stroke-opacity: 0.75;
		vector-effect: non-scaling-stroke;
	}
	.tile-mark text {
		fill: var(--text-1);
		fill-opacity: 0.8;
		font-weight: 600;
		stroke: none;
	}
	/* The fresh piece in the accent: that is where the machine is working now, and it is
	   the only piece you know for certain has just happened. */
	.trail polyline.fresh {
		stroke: var(--accent);
		stroke-width: 1.6;
		stroke-opacity: 0.9;
	}
	/* The ring around the head: the track as a faint circle so that you see where 100%
	   lies, and the progress inside it. */
	.head circle.ring-baan {
		stroke: var(--accent);
		stroke-width: 2.5;
		stroke-opacity: 0.16;
	}
	.head circle.ring {
		stroke: var(--accent);
		stroke-width: 2.5;
		stroke-linecap: round;
	}
	/* ── The user's zero point (gap J12) ─────────────────────────────────────── */
	.origin-mark line {
		stroke: var(--text-1);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
	}
	.origin-mark text {
		fill: var(--text-1);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3;
		stroke-linejoin: round;
	}
	/* Where the work lands: dotted and muted, because it is not a shape but an
	   announcement. Not in --danger or --warn — nothing is wrong; it is exactly what you
	   asked for. */
	.burns-hier rect {
		fill: none;
		stroke: var(--text-1);
		stroke-width: 1;
		stroke-dasharray: 5 4;
		stroke-opacity: 0.55;
	}
	/* The sheet in its new place is one step softer than the work in it: it is the
	   ground, not the subject. */
	.burns-hier rect.sheetsketch {
		stroke-opacity: 0.3;
		stroke-dasharray: 2 5;
	}
	.burns-hier text {
		fill: var(--text-2);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3;
		stroke-linejoin: round;
	}
	/* The same place and the same tone as the trail explanation: a line that says what
	   you are looking at, not a warning. */
	.tool-hint {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		border-top: 1px solid var(--line-1);
	}
	.trail-hint {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		border-top: 1px solid var(--line-1);
	}
	/* The little mark is the piece of line itself: that way you do not have to guess
	   which line on the bed belongs to this sentence. */
	.trail-mark {
		flex: none;
		width: 22px;
		height: 0;
		margin-top: 0.5em;
		border-top: 2px solid var(--accent);
		opacity: 0.9;
	}
	.hit {
		cursor: pointer;
	}
	/* Finely dotted and at full strength, so that a guide line cannot be confused with
	   the head marker (the same accent colour, but solid and half transparent) or with
	   the dashed selection contour. */
	.guide {
		pointer-events: none;
	}
	.guide line {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 2 2;
		vector-effect: non-scaling-stroke;
	}
	.guide text {
		fill: var(--accent);
		font-variant-numeric: tabular-nums;
		/* A little border in the bed colour under the letters: the word sits right beside
		   the workpiece and would otherwise fall across a contour or a handle. */
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
		/* No font-size here: it is computed per element, because this text is in
		   millimetres and would otherwise grow with the zoom. */
	}
	.hit.passive {
		pointer-events: none;
	}
	.pending {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.endpoint {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		pointer-events: none;
	}
	/* An invisible hit zone around a handle; the handle itself is too small to hit once
	   it has a fixed screen size. */
	.grip {
		fill: transparent;
		stroke: none;
		cursor: grab;
		touch-action: none;
	}
	.grip:active {
		cursor: grabbing;
	}
	/* Everything the pen draws while you are drawing catches no pointer. Measured: the
	   preview runs to where the cursor is, so its own stroke was the topmost thing under
	   the pointer and the next press landed on the line instead of on the bed — the second
	   point of every line was simply lost. */
	.pen-line,
	.pen-dot,
	.pen-arm,
	.pen-grip {
		pointer-events: none;
	}
	.pen-line {
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
	}
	.pen-dot { fill: var(--accent); }
	/* A handle's arm and its two grips. Thinner and lighter than the line itself: the arm
	   is scaffolding, the line is the work. */
	.pen-arm,
	.tether {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 2 2;
		stroke-opacity: 0.7;
		vector-effect: non-scaling-stroke;
	}
	.pen-grip {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.2;
		vector-effect: non-scaling-stroke;
	}
	/* Square, so a handle is never mistaken for a node; the two lie close together and
	   mean different things. */
	.handle-square {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		pointer-events: none;
	}
	.handle-square:has(+ .grip:hover) { fill: var(--accent); }
	.measure {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 3 2;
		vector-effect: non-scaling-stroke;
	}
	.measure-label {
		font-variant-numeric: tabular-nums;
		/* No font-size here: it is computed per element, because this text is in
		   millimetres and would otherwise grow with the zoom. */
		fill: var(--accent);
		font-family: var(--font-mono, monospace);
	}
	.knot {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		pointer-events: none;
	}
	/* The hit zone comes *after* the handle in the tree; :has looks ahead. */
	.knot:has(+ .grip:hover) { fill: var(--accent); }
	/* Tabbed to. The grip itself is transparent and has no size worth outlining, so the
	   ring goes round the knot it belongs to — otherwise a keyboard user tabs through four
	   invisible circles and sees nothing move. */
	.knot:has(+ .grip:focus-visible) {
		fill: var(--accent);
		stroke: var(--surface-1);
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.grip:focus-visible { outline: none; }
	/* The node in hand: the verbs work on this one, so it has to be the one that looks
	   chosen. Filled, not merely outlined — an outline difference disappears at the size a
	   node has on screen. */
	.knot.picked {
		fill: var(--accent);
		stroke: var(--surface-1);
	}
	.crop-catch {
		fill: rgb(0 0 0 / 0.18);
		cursor: crosshair;
	}
	.band {
		fill: color-mix(in srgb, var(--accent) 12%, transparent);
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.zoom {
		position: absolute;
		right: var(--space-3);
		bottom: var(--space-3);
		display: flex;
		gap: 2px;
		padding: 2px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		box-shadow: var(--shadow-float);
		z-index: 3;
	}
	.zoom .fit {
		display: flex;
		align-items: center;
		gap: 4px;
		width: auto;
		padding: 0 var(--space-3);
		font-size: var(--text-xs);
	}
	.zoom button {
		min-width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.zoom button:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.zoom .snap.on {
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
	}
	.zoom .scheiding {
		width: 1px;
		align-self: stretch;
		margin: 2px 2px;
		background: var(--line);
	}
	.zoom .val {
		font-size: 11px;
		padding: 0 8px;
		color: var(--text-1);
	}
	/* The global :focus-visible rule from tokens.css draws a 2 px outline with an offset.
	   On an SVG shape that renders as a rectangle around the bounding box, and while
	   dragging the focus is precisely on the drag surface or a corner handle — which gave
	   a thick border around the whole selection. So it is off here for all shapes in the
	   canvas; what is selected stays visible through the kerf-line contour, with keyboard
	   operation as well. */
	svg :focus,
	svg :focus-visible {
		outline: none;
	}
	/* Keyboard focus does stay visible: without a mouse you have to be able to see which
	   element you are about to select. */
	.hit:focus-visible {
		stroke: color-mix(in srgb, var(--accent) 30%, transparent);
		stroke-width: 4;
	}
	/* The kerf line as selection contour: statically dashed, animation only while
	   dragging — that comes in the next block. */
	.selection rect {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 6 4;
		vector-effect: non-scaling-stroke;
	}
	.selection .handle {
		fill: var(--surface-1);
		stroke-dasharray: none;
		pointer-events: none;
	}
	.selection rect.handle-hit {
		fill: transparent;
		stroke: none;
		touch-action: none;
	}
	.selection rect.handle-hit.grabbable {
		cursor: nwse-resize;
	}
	.selection .stalk {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: none;
		vector-effect: non-scaling-stroke;
	}
	.selection .rotator {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		cursor: grab;
	}
	.selection .rotator {
		pointer-events: none;
	}
	.selection .rotator-hit {
		fill: transparent;
		stroke: none;
		cursor: grab;
	}
	.selection .rotator-hit:active {
		cursor: grabbing;
	}
	/* `rect.grab` and not `.grab`: `.selection rect` above is more specific and otherwise
	   won, which gave the drag surface the same dashed accent line as the contour. Two
	   sets of dashes over each other, and while dragging only the contour animates — then
	   they run out of phase and the border closes up into a thick bar. */
	.selection rect.grab {
		fill: transparent;
		stroke: none;
		cursor: move;
		touch-action: none;
	}
	.selection text {
		fill: var(--text-2);
	}
	.empty {
		position: absolute;
		inset: auto 0 var(--space-6) 0;
		text-align: center;
		color: var(--text-2);
	}
</style>
