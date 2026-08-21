<script lang="ts">
	import {
		LAYER_COLORS,
		elementName,
		inkOn,
		type DesignOperation,
		type DesignStore
	} from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';
	import ArrangeIcon from './ArrangeIcon.svelte';
	import Menu from './Menu.svelte';
	import { en } from '$lib/i18n/en';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import { layerMenu, type Menu as MenuList } from '$lib/actions';
	import { untrack } from 'svelte';

	let {
		design,
		edits,
		canEdit = false,
		onRotate,
		onAssign,
		onLayerChange,
		onArrange,
		cornerNote = null,
		onPrune,
		tidyNote = null,
		onImage,
		onImageDpi,
		box = null,
		onSetPosition,
		onSetSize,
		image = null,
		onImageSet,
		onImageClear,
		show = 'selection',
		bed = null
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onRotate?: (angleDeg: number) => void;
		onAssign?: (operationId: string, assigned: boolean) => void;
		onLayerChange?: () => void;
		/** Only for "put everything on the bed" now: since v4 the rest of the arranging
		 *  lives in the action bar and the context menu. */
		onArrange?: (action: string) => void;
		/** What the last corner operation has to report (skipped corners). In a fixed
		 *  place in the panel, not in a browser popup. */
		cornerNote?: string | null;
		/** Empty layers removed. */
		onPrune?: () => void;
		/** What the last tidy-up action has to report. */
		tidyNote?: string | null;
		onImage?: (adjustment: string) => void;
		onImageDpi?: (dpi: number) => void;
		/** Live measures while dragging; falls back on the selection itself. */
		box?: { x: number; y: number; width: number; height: number } | null;
		onSetPosition?: (x: number, y: number) => void;
		onSetSize?: (width: number, height: number) => void;
		/** What is switched on for the chosen image; comes from the API. */
		image?: {
			dpi: number | null;
			dither_types: string[];
			adjustments: {
				name: string;
				label: string;
				enabled: boolean;
				ranges: Record<string, number[]>;
				values: Record<string, string | number | boolean>;
			}[];
		} | null;
		onImageSet?: (
			name: string,
			enabled: boolean,
			values: Record<string, unknown> | null
		) => void;
		onImageClear?: () => void;
		/** Which part is shown. Selection and layers side by side in one panel became
		 *  too busy to find anything in. */
		show?: 'selection' | 'layers';
		/** Bed size in mm, to see whether something falls outside. */
		bed?: { width: number; height: number } | null;
	} = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);
	let selected = $derived(design.selected);
	let size = $derived(design.selectedSize);

	// What lies off the bed does not burn and is hard to grab. Better to report it with
	// a way out than to let the user discover something is missing.
	let strays = $derived.by(() => {
		const perMm = design.design?.units_per_mm;
		if (!bed || !perMm) return [];
		return design.elements.filter((element) => {
			if (!element.bounds) return false;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			return x0 < -0.5 || y0 < -0.5 || x1 > bed.width + 0.5 || y1 > bed.height + 0.5;
		});
	});
	// While dragging the canvas layer shows a preview frame; those measures belong here
	// as well then, otherwise panel and canvas drift apart.
	let live = $derived(box ?? size);

	// Keeping the ratio. Without this a logo deforms as soon as you type one measure,
	// and you only notice once it is burned.
	let linked = $state(true);

	function commitPosition(axis: 'x' | 'y', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value)) return;
		onSetPosition?.(axis === 'x' ? value : live.x, axis === 'y' ? value : live.y);
	}

	function commitSize(axis: 'width' | 'height', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value) || value <= 0) return;
		if (linked && live.width > 0 && live.height > 0) {
			const factor = value / (axis === 'width' ? live.width : live.height);
			onSetSize?.(live.width * factor, live.height * factor);
			return;
		}
		onSetSize?.(
			axis === 'width' ? value : live.width,
			axis === 'height' ? value : live.height
		);
	}
	let chosen = $derived(design.selectedElements);

	/** The layers the selection is in, with their colour and burn number. */
	let inLagen = $derived.by(() => {
		const ids = new Set(chosen.flatMap((e) => e.operation_ids ?? []));
		const gewoon = design.operations.filter((op) => !op.grid);
		return gewoon
			.map((op, index) => ({ ...op, number: index + 1 }))
			.filter((op) => ids.has(op.id));
	});
	let selectedIds = $derived(design.selectedIds);

	// -------------------------------------------------------------- the state
	//
	// Rotating and mirroring were blind actions until now: you could click but not see
	// where you were, so every click stacked on the previous one and the only way back
	// was undo. The engine *knows* the pose — it keeps it in every node's matrix — so it
	// is now in the snapshot and the panel shows it. That makes every action a value
	// rather than a step: typing the same number gives the same picture, however many
	// times you have clicked.

	/** The selection's angle, or null when the shapes disagree. */
	let pose = $derived.by(() => {
		const poses = chosen.map((e) => e.pose).filter(Boolean) as {
			angle_deg: number;
			mirrored: boolean;
		}[];
		if (!poses.length) return { angle: null as number | null, mirrored: false, mixed: false };
		const first = poses[0];
		const mixed = poses.some((p) => Math.abs(p.angle_deg - first.angle_deg) > 0.05);
		return {
			angle: mixed ? null : first.angle_deg,
			// One mirrored shape in the selection is enough to report it; keeping quiet
			// would mean you only see it on the workpiece.
			mirrored: poses.some((p) => p.mirrored),
			mixed
		};
	});

	/**
	 * Where the selection was when you picked it up.
	 *
	 * This is the anchor for "Restore": as long as a selection is active you can get
	 * back in one tap to exactly the pose from before the arranging — not to the
	 * previous click, but to the original. Deliberately *not* a shadow copy of the
	 * document: every tap stays an ordinary, undoable edit in the engine, and nothing
	 * downstream (job, pre-flight, autosave) looks at geometry that is not really
	 * there.
	 */
	let anchor = $state<{
		key: string;
		angle: number | null;
		mirrored: boolean;
		box: { x: number; y: number; width: number; height: number };
	} | null>(null);

	$effect(() => {
		const key = selectedIds.join(',');
		const start = design.selectedSize;
		const state = pose;
		untrack(() => {
			if (!key || !start) {
				anchor = null;
				return;
			}
			// Only re-anchor on a *new* selection. If the anchor followed every edit it
			// would not be an anchor but a mirror of the last click.
			if (anchor?.key === key) return;
			anchor = { key, angle: state.angle, mirrored: state.mirrored, box: { ...start } };
		});
	});

	function near(a: number, b: number, slack = 0.05) {
		return Math.abs(a - b) < slack;
	}

	/** Is the selection somewhere other than where you grabbed it? */
	let moved = $derived.by(() => {
		if (!anchor || !size) return false;
		if (pose.mirrored !== anchor.mirrored) return true;
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			return true;
		return (
			!near(size.x, anchor.box.x) ||
			!near(size.y, anchor.box.y) ||
			!near(size.width, anchor.box.width) ||
			!near(size.height, anchor.box.height)
		);
	});

	/**
	 * In words, what has changed since it was clicked.
	 *
	 * Only what the button beside it undoes, and not what is there now: the sizes
	 * are already in the fields above, and saying that twice makes the line longer
	 * without making it clearer.
	 */
	let movedSummary = $derived.by(() => {
		if (!anchor || !size) return '';
		const parts: string[] = [];
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			parts.push(t('panel.moved.rotated', { angle: format(pose.angle) }));
		if (pose.mirrored !== anchor.mirrored) parts.push(t('panel.moved.mirrored'));
		// Rotating about the centre changes the bounding box, so size and place are
		// only reported when nothing else changed — otherwise it says "moved" on
		// every rotation and the word stops meaning anything.
		if (!parts.length) {
			const otherSize =
				!near(size.width, anchor.box.width) || !near(size.height, anchor.box.height);
			const otherPlace = !near(size.x, anchor.box.x) || !near(size.y, anchor.box.y);
			// With one shape a different box really is a different size. With more
			// shapes the box is the hull of the whole selection, and that changes as
			// well when the shapes only move relative to *each other* — aligning, for
			// instance. Saying "scaled" then is untrue: nothing got bigger or smaller.
			// Measured after one click on "Align top" with three shapes: the box got
			// shorter and the line said "scaled".
			if (otherSize) parts.push(t(chosen.length > 1 ? 'panel.moved.arranged' : 'panel.moved.scaled'));
			else if (otherPlace) parts.push(t('panel.moved.moved'));
		}
		return parts.join(' · ') || t('panel.moved.changed');
	});

	// One decimal, but not a bare ".0": an angle of 45 is 45°, not 45.0°. The
	// decimal separator comes from the reader's locale.
	function format(value: number) {
		return i18n.number(Math.round(value * 10) / 10);
	}

	async function setAngle(raw: string) {
		const value = Number(raw.replace(',', '.'));
		if (!Number.isFinite(value) || !selectedIds.length) return;
		if ((await edits.rotate(selectedIds, ((value % 360) + 360) % 360, true)).ok)
			await design.load();
	}

	/** Back to the pose from before the arranging, in one tap. */
	async function restore() {
		if (!anchor || !selectedIds.length) return;
		const ids = selectedIds;
		// Order counts: mirroring flips the sign of the angle, so the angle goes over it
		// afterwards, and the frame last — that also puts back the offset rotating about
		// the centre leaves behind.
		if (pose.mirrored !== anchor.mirrored) await edits.mirror(ids, 'horizontal');
		if (anchor.angle !== null) await edits.rotate(ids, anchor.angle, true);
		const { x, y, width, height } = anchor.box;
		await edits.resize(ids, x, y, width, height);
		await design.load();
	}

	// Which of the rarely used groups are open. Remembered per panel, not per
	// selection: whoever uses booleans uses them all afternoon.
	let openGroups = $state<Record<string, boolean>>({});

	// The corner operation lives in `CornersDialog.svelte`; the style, the size and the
	// sample drawing moved along with it.

	let editingLayer = $state<string | null>(null);
	/**
	 * The menu on a layer row, from one place.
	 *
	 * The right-click and the ⋯ button open the same menu in the same way. They were
	 * two calls in the markup, and then it is a matter of time before one has an entry
	 * the other is missing.
	 */
	function opendLaagMenu(op: DesignOperation, index: number, x: number, y: number) {
		rijMenu = {
			x,
			y,
			list: layerMenu(
				{
					label: op.label,
					shapeCount: op.element_ids.length,
					burns: op.output,
					visible: !design.isLayerHidden(op.id),
					first: index === 0,
					last: index === plainLayers.length - 1,
					selection: selectedIds.length,
					inside: selectedIds.length > 0 && membership(op.id) === 'all',
					may: canEdit,
					locked: op.grid ? t('reason.testGridLayer') : undefined
				},
				{
					selectShapes: () => design.selectMany(op.element_ids),
					putSelection: (inside) => onAssign?.(op.id, inside),
					toggleBurns: () => patchLayer(op.id, { output: !op.output }),
					toggleVisible: () => design.toggleLayer(op.id),
					up: () => moveLayer(op.id, 'up'),
					down: () => moveLayer(op.id, 'down'),
					openSettings: () => (editingLayer = op.id),
					remove: () => (confirmDrop = op.id)
				}
			)
		};
	}

	let rijMenu = $state<{
		list: MenuList;
		x: number;
		y: number;
		/** For a menu that hangs off a button at the bottom of the panel. */
		upward?: boolean;
	} | null>(null);
	let openGrid = $state<number | null>(null);

	// Grid layers are not ordinary layers: they belong to one test grid and their speed
	// and power *are* the test. So one row per grid.
	/**
	 * What splitting would produce. An imported path holds all its panels in one shape;
	 * the number here is the number of shapes the button promises.
	 */
	const teSplitsen = $derived.by(() => {
		const samengesteld = chosen.filter((e) => (e.subpaths ?? 1) > 1);
		return {
			shapes: samengesteld.length,
			stukken: samengesteld.reduce((n, e) => n + (e.subpaths ?? 1), 0)
		};
	});

	/**
	 * Can this selection carry a fill, and does it already?
	 *
	 * A line and a point have no inside; the button should not be there then. Without a
	 * fill a shape only grids its outline, and that is the whole reason this button
	 * exists.
	 */
	const VULBAAR = ['elem rect', 'elem ellipse', 'elem path', 'elem polyline'];
	const vulbaar = $derived(chosen.filter((e) => VULBAAR.includes(e.type)));
	const alGevuld = $derived(
		vulbaar.length > 0 && vulbaar.every((e) => Boolean(e.fill))
	);

	/** How many layers the selection is in now — the number 'only in' cancels. */
	const nuInLagen = $derived(
		new Set(chosen.flatMap((e) => e.operation_ids ?? [])).size
	);

	let plainLayers = $derived(operations.filter((o) => !o.grid));
	/** Layers without work: what 'tidy up the empty layers' removes. */
	const legeLagen = $derived(plainLayers.filter((op) => !op.element_ids.length));

	let gridGroups = $derived.by(() => {
		const byGrid = new Map<number, typeof operations>();
		for (const op of operations) {
			if (!op.grid) continue;
			const list = byGrid.get(op.grid.grid_id) ?? [];
			list.push(op);
			byGrid.set(op.grid.grid_id, list);
		}
		return [...byGrid.entries()].map(([id, ops]) => ({ id, ops }));
	});

	async function removeGrid(gridId: number) {
		const token =
			typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		await fetch(`/api/library/testgrids/${gridId}/remove-from-design`, {
			method: 'POST',
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		});
		onLayerChange?.();
	}
	let newLayerType = $state('cut');
	// Throwing a layer away takes its assignments with it. That must not happen on one
	// tap beside the speed fields, so a confirmation comes in between.
	let confirmDrop = $state<string | null>(null);
	// Throwing everything away at once is the same action times ten, so the same
	// confirmation — but one that says *how much* goes and what stays.
	let confirmDropAll = $state(false);

	const LAYER_TYPES = [
		{ value: 'cut', label: t('panel.kind.cut'), noun: t('panel.kind.cutNoun') },
		{ value: 'engrave', label: t('panel.kind.engrave'), noun: t('panel.kind.engraveNoun') },
		{ value: 'grid', label: t('panel.kind.raster'), noun: t('panel.kind.rasterNoun') },
		{ value: 'dots', label: t('panel.kind.dots'), noun: t('panel.kind.dotsNoun') }
	];
	let newLayerNoun = $derived(
		LAYER_TYPES.find((type) => type.value === newLayerType)?.noun ?? t('panel.kind.layerNoun')
	);

	async function addLayer() {
		if (await edits.addLayer(newLayerType)) onLayerChange?.();
	}

	async function patchLayer(id: string, fields: Record<string, unknown>) {
		if (await edits.updateLayer(id, fields)) onLayerChange?.();
	}

	async function moveLayer(id: string, direction: 'up' | 'down') {
		if (await edits.moveLayer(id, direction)) onLayerChange?.();
	}

	/** Engraving before cutting, in one click (gap L2). */
	async function sorteerLagen() {
		const off = await edits.sortLayers();
		if (off.ok) onLayerChange?.();
	}

	/**
	 * Changing the operation kind of an existing layer (gap L3).
	 *
	 * The layer gets a new id — the engine cannot switch a node's type — so the
	 * expander closes: it would otherwise point at a layer that no longer exists.
	 */
	async function retypeLayer(id: string, type: string) {
		const off = await edits.retypeLayer(id, type);
		if (!off.ok) return;
		editingLayer = null;
		onLayerChange?.();
	}

	// ── Dragging to reorder (gap L1) ──────────────────────────────────────────
	//
	// Not the HTML5 drag API: that does not work on a touch screen, and beside a laser a
	// tablet is the usual device. Pointer events work on all three devices with the same
	// code.
	//
	// The ↑/↓ buttons in the expander stay, and the grip itself does the same with the
	// arrow keys — dragging is an extra route, not a replacement.
	let dragging = $state<{ id: string; from: number; to: number } | null>(null);
	let rijElementen: (HTMLElement | null)[] = [];
	let rijGrenzen: { top: number; centre: number }[] = [];

	function startSleep(event: PointerEvent, id: string, index: number) {
		if (!canEdit || edits.busy) return;
		event.preventDefault();
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		// Measure the sizes once, at the start: the list itself does not move while
		// dragging, and measuring again per movement costs a layout per pointer move.
		rijGrenzen = rijElementen
			.filter((el): el is HTMLElement => !!el)
			.map((el) => {
				const box = el.getBoundingClientRect();
				return { top: box.top, centre: box.top + box.height / 2 };
			});
		dragging = { id, from: index, to: index };
	}

	function beweegSleep(event: PointerEvent) {
		if (!dragging) return;
		let to = 0;
		for (let i = 0; i < rijGrenzen.length; i++) {
			if (event.clientY > rijGrenzen[i].centre) to = i + 1;
		}
		// Landing above your own row means: in that place. Below your own row everything
		// in between shifts up one, so the destination is one lower.
		if (to > dragging.from) to -= 1;
		to = Math.min(Math.max(to, 0), rijGrenzen.length - 1);
		if (to !== dragging.to) dragging = { ...dragging, to };
	}

	async function eindSleep() {
		const movement = dragging;
		dragging = null;
		if (!movement || movement.to === movement.from) return;
		const off = await edits.dropLayerAt(movement.id, movement.to);
		if (off.ok) onLayerChange?.();
	}

	/**
	 * Compacte list (gat L5).
	 *
	 * Measured: our row is 76 px on the desktop and 111 px on a touch screen; LightBurn
	 * does 23–26 px. Above eight layers our list is therefore a scrolling exercise.
	 * Compact puts identity and values on one line instead of two — the fields stay,
	 * because adjusting beside a running machine must not cost a submenu. That is
	 * exactly why this panel exists.
	 *
	 * The state is remembered: whoever works with fifteen layers does so all
	 * afternoon.
	 */
	let compact = $state(
		typeof window !== 'undefined' && localStorage.getItem('openkerf.lagen-compact') === 'aan'
	);

	// The same order as the server (`Drawing.BURN_ORDER`): first what touches the
	// surface, cutting last. Here only to know whether the button still has something to
	// do — the sorting itself happens in the engine.
	const BRAND_ORDER: Record<string, number> = {
		'op image': 0,
		'op raster': 1,
		'op engrave': 2,
		'op dots': 3,
		'op cut': 4
	};

	let gesorteerd = $derived.by(() => {
		const rangen = plainLayers.map((o) => BRAND_ORDER[o.type] ?? 99);
		return {
			kanSorteren: rangen.some((rang, i) => i > 0 && rang < rangen[i - 1])
		};
	});

	function compactSchakel() {
		compact = !compact;
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.lagen-compact', compact ? 'aan' : 'uit');
		}
	}

	async function dropLayer(id: string) {
		confirmDrop = null;
		if (await edits.removeLayer(id)) onLayerChange?.();
	}

	async function dropAllLayers() {
		confirmDropAll = false;
		if (await edits.removeAllLayers()) onLayerChange?.();
	}

	/** The kind of operation in the reader's language; the engine calls it "op cut". */
	function typeName(type: string): string {
		const kind = type.replace(/^(op|effect) /, '');
		const key = `panel.type.${kind}` as MessageKey;
		return key in en ? t(key) : kind;
	}

	/**
	 * The layer type as the segmented control knows it.
	 *
	 * The engine calls them `op cut`; our four choices are called `cut`. An image
	 * layer (`op image`) has no choice of its own — the engine makes that itself
	 * when an image is placed — and falls under grid, because that is what it
	 * does.
	 */
	function kindOf(type: string): string {
		const kind = String(type).replace(/^op /, '');
		return kind === 'image' ? 'grid' : kind;
	}

	/** Power sits at 0–1000 in the engine; the user reckons in per cent. */
	function powerPercent(op: { power: number | null }): number | null {
		return op.power === null ? null : Math.round(op.power / 10);
	}

	/**
	 * A number from a field that sits right in the row.
	 *
	 * Empty or nonsense is left as it was rather than turned into zero: zero mm/s
	 * is a machine standing still with the laser on.
	 */
	function commitNumber(
		event: Event & { currentTarget: HTMLInputElement },
		id: string,
		field: string,
		was: number | null
	) {
		const value = Number(event.currentTarget.value);
		if (!Number.isFinite(value) || value <= 0) {
			event.currentTarget.value = was === null ? '' : String(was);
			return;
		}
		if (value === was) return;
		patchLayer(id, { [field]: value });
	}

	// An operation is "on" for the selection when *every* chosen element is in it.
	function membership(operationId: string): 'all' | 'some' | 'none' {
		if (chosen.length === 0) return 'none';
		const inside = chosen.filter((e) => e.operation_ids.includes(operationId)).length;
		if (inside === 0) return 'none';
		return inside === chosen.length ? 'all' : 'some';
	}

	/**
	 * The three values of a layer as one line, for the compact mode.
	 *
	 * With units, because "35 · 100 · 1" is a row of numbers without meaning.
	 * Passes only when there is more than one: that is the case for a couple of
	 * layers at most, and "1×" on all the others is noise.
	 */
	function short(op: { speed: number | null; power: number | null; passes: number | null }) {
		const parts: string[] = [];
		parts.push(op.speed === null ? '—' : `${op.speed}`);
		const percent = powerPercent(op);
		parts.push(percent === null ? '—' : `${percent}%`);
		if ((op.passes ?? 1) > 1) parts.push(`${op.passes}×`);
		return parts.join(' · ');
	}

	function describe(op: { speed: number | null; power: number | null }) {
		const parts: string[] = [];
		if (op.speed !== null) parts.push(`${op.speed} mm/s`);
		if (op.power !== null) parts.push(`${Math.round((op.power / 1000) * 100)}%`);
		return parts;
	}
</script>

{#if show === 'selection' && strays.length}
	<div class="section stray">
		<!-- The same words as the strip under the canvas (gap C2): there says what is
		     going on, here says the way out. Two places naming the same problem
		     differently makes the reader think there are two problems. -->
		<p>{t('canvas.outsideBed', { n: strays.length })}</p>
		{#if canEdit}
			<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('rescue')}>
				{t('action.rescue')}
			</button>
		{/if}
	</div>
{/if}

<div class="section">
	<!-- Heading, count and history on one line. They used to be on three, and
	     three lines above the selection are three lines pushing the selection
	     down. -->
	<div class="section-head">
		<h2 class="section-title">{t('panel.design')}</h2>
		{#if elements.length}
			<span class="muted mono tally">{t('panel.elements', { n: elements.length })}</span>
		{/if}
		<!-- Undo and redo used to be here. They moved to the action bar above the
		     canvas: they were the only two buttons in the app that disappeared the
		     moment you were on the Job tab, while that is precisely where you
		     sometimes want to take something back. Since the move they have ⌘Z and
		     ⌘⇧Z as well. -->
	</div>
	{#if edits.error}
		<p class="edit-error" role="alert">{edits.error}</p>
	{/if}
	{#if elements.length === 0}
		<!-- This used to say "Use 'Load design…' in the Job tab". That button does
		     not exist and never has (repo-wide grep: this line was the only place
		     that name appeared). An empty state pointing at an invented button is
		     worse than one that keeps quiet: you go looking. -->
		<p class="empty">{t('panel.empty')}</p>
	{/if}
</div>

{#if show === 'selection' && selected && size}
	<div class="section">
		<h2 class="section-title">{t('panel.selection')}</h2>
		<div class="selected">
			<div class="head">
				<span class="name" title={chosen.length > 1 ? undefined : selected.label}>
					{chosen.length > 1 ? t('panel.shapes', { n: chosen.length }) : elementName(selected)}
				</span>
				<!-- How many layers the selection is in used to be a paragraph of its own
				     at the bottom of the panel, out of sight. It belongs to the identity
				     of what you are holding, so it sits next to the name. -->
				<!-- *Which* layer, not how many. "in 1 layer" was true and useless: that
				     the shape is in something is not the question, the question is what.
				     And this is exactly what you check before starting — with the layer
				     colour, so it matches what you see on the canvas. -->
				<span class="in-layers">
					{#if inLagen.length === 0}
						<span class="geenlaag" title={t('panel.noLayer.title')}>{t('panel.noLayer')}</span>
					{:else}
						{#each inLagen as layer (layer.id)}
							<span class="laagchip" title={t('panel.layerChip', { n: layer.number, label: layer.label })}>
								<span class="stip" style="background: {layer.color}"></span>
								{layer.label}
							</span>
						{/each}
					{/if}
				</span>
				<button class="clear" onclick={() => design.select(null)}>{t('panel.clear')}</button>
			</div>
			<!-- Sizes, position and angle as one grid of three lines: two columns of
			     numbers with the unit once on the right. They used to be freely
			     wrapping pills beside each other, so X ended up on the first line and Y
			     on its own on the second — and then two pairs no longer read as two
			     pairs. -->
			<div class="figures mono">
				<!-- The one-letter labels are translated too: "B" is Breedte in Dutch and
				     means nothing in English, where the same column reads "W". -->
				{#each [
					[t('panel.widthShort'), 'width', t('panel.width')],
					[t('panel.heightShort'), 'height', t('panel.height')]
				] as [label, key, name] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							min="0.1"
							aria-label={t('panel.inMillimetres', { what: name })}
							disabled={!canEdit}
							value={(live ?? size)[key as 'width' | 'height'].toFixed(1)}
							onchange={(e) => commitSize(key as 'width' | 'height', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<button
					class="link"
					aria-pressed={linked}
					disabled={!canEdit}
					title={linked ? t('panel.ratio.locked') : t('panel.ratio.free')}
					aria-label={linked ? t('panel.ratio.lockedShort') : t('panel.ratio.freeShort')}
					onclick={() => (linked = !linked)}
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if linked}
							<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
							<path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
						{:else}
							<path d="M9 12H5a3 3 0 0 1 0-6h4M15 12h4a3 3 0 0 1 0 6h-4" />
						{/if}
					</svg>
				</button>
				{#each [['X', 'x', t('panel.positionX')], ['Y', 'y', t('panel.positionY')]] as [label, key, name] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							aria-label={t('panel.inMillimetres', { what: name })}
							disabled={!canEdit}
							value={(live ?? size)[key as 'x' | 'y'].toFixed(1)}
							onchange={(e) => commitPosition(key as 'x' | 'y', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<span class="unit">mm</span>
			</div>

			{#if canEdit}
				<!-- The angle was nowhere. You could rotate by 1° and by 90° but not see
				     where you were, so every click was a guess on top of the previous
				     one. Now the angle is a value from the engine: typeable, and the
				     steps move it instead of stacking something up. -->
				<div class="figures mono rotrow">
					<label class="f angle" class:mixed={pose.mixed}>
						<span aria-hidden="true">∠</span>
						<input
							type="number"
							step="1"
							inputmode="decimal"
							aria-label={t('panel.angle')}
							title={pose.mixed ? t('panel.angle.mixed') : t('panel.angle.title')}
							disabled={edits.busy || pose.mixed || pose.angle === null}
							value={pose.angle === null
								? ''
								: Number.isInteger(pose.angle)
									? pose.angle
									: pose.angle.toFixed(1)}
							placeholder={pose.mixed ? '—' : ''}
							onchange={(e) => setAngle(e.currentTarget.value)}
						/>
						<!-- The degree sign belongs *in* the field. As a column of its own it
						     sat three columns away on a tablet, apart from the number it
						     belongs to. -->
						<span class="suffix" aria-hidden="true">°</span>
					</label>
					<!-- Only the one-degree steps are left: that is the spinner belonging to
					     this field. Rotating by 90° is an operation and lives in the
					     right-click menu under "Rotate" (with , and . as shortcuts). -->
					{#each [[-1, ''], [1, '']] as [angle, icon] (angle)}
						<button
							class="icon step"
							disabled={edits.busy}
							title={t('panel.rotate.step', {
								angle: `${Number(angle) > 0 ? '+' : ''}${angle}`
							})}
							aria-label={t('panel.rotate.stepAria', {
								angle: `${Number(angle) > 0 ? '+' : ''}${angle}`
							})}
							onclick={() => onRotate?.(Number(angle))}
						>
							{#if icon}
								<ArrangeIcon name={String(icon)} size={18} />
							{:else}
								<span class="stepnum">{Number(angle) > 0 ? '+' : '−'}1</span>
							{/if}
						</button>
					{/each}
				</div>
				{#if pose.mixed}
					<p class="tip">{t('panel.angle.mixedNote')}</p>
				{/if}
			{/if}

			{#if selected.text}
				<!-- The content of the text is a value and belongs here; editing it is an
				     operation and lives in the right-click menu. This used to be one
				     button doing both, and then the text is only readable once you have
				     already clicked it. -->
				<p class="tekstwaarde" title={selected.text.text}>“{selected.text.text}”</p>
			{/if}

			<!-- Twelve icons — align, distribute, mirror, group — used to be here. They
			     moved to the action bar above the canvas: there they are visible on
			     every tab and do not scroll away. See DESIGN-SYSTEM v4, "Where an
			     operation belongs". -->

			{#if canEdit && (moved || pose.mirrored)}
				<!-- The anchor. As long as this selection is active, every rotation and
				     every mirroring can be taken back to how it was before the arranging
				     — not to the previous click. Clicking away makes it final; there is
				     nothing to commit, because every tap was already in the document and
				     can simply be undone. -->
				<div class="anchor" class:idle={!moved}>
					<span class="anchor-what">
						{#if moved}
							{t('panel.anchor.since', { what: movedSummary })}
						{:else}
							{t('panel.anchor.mirrored')}
						{/if}
					</span>
					{#if moved}
						<button
							class="anchor-back"
							disabled={edits.busy}
							title={t('panel.anchor.backTitle')}
							onclick={restore}
						><ArrangeIcon name="restore" size={16} /> {t('panel.anchor.back')}</button>
					{/if}
				</div>
			{/if}

			{#if selected.effect}
				<p class="hint">{t('panel.inEffect', { label: selected.effect.label })}</p>
			{/if}

			{#if teSplitsen.shapes}
				<!-- This is a diagnosis, not an operation: it says what you are holding.
				     The button that went with it ("Split into n shapes") moved to the
				     right-click menu, under "Edit path", with the same number. Without
				     this line the menu would promise a count you could not check
				     anywhere. -->
				<p class="tip">
					{t('panel.splittable', { n: teSplitsen.shapes, pieces: teSplitsen.stukken })}
				</p>
			{/if}
			{#if tidyNote}
				<p class="tip" role="status">{tidyNote}</p>
			{/if}
			{#if cornerNote}
				<p class="tip" role="status">{cornerNote}</p>
			{/if}

			<!-- Three collapsed folds used to be here: Combine (unite, difference,
			     intersect, exclude), Edit path (nest, offset, simplify, hatch, wobble)
			     and Corners. Fifteen operations behind three clicks, in a column you had
			     to scroll anyway. All fifteen are in the right-click menu on the shape
			     now, in submenus with the same names; Corners opens a window of its own
			     with the preview in it. -->

			{#if canEdit && selected.image}
				<!-- The edits are not destructive: the recipe runs over the original again
				     every time. Hence switches with their values, and not a row of
				     buttons where you have to remember what you pressed.

				     Collapsed, though: eight switches with sliders are on their own
				     longer than the rest of the panel put together, and you set them once
				     rather than over and over. -->
				<details
					class="fold"
					open={openGroups.image}
					ontoggle={(e) => (openGroups.image = e.currentTarget.open)}
				>
					<summary>
						{t('panel.image')}
						{#if image?.adjustments.some((a) => a.enabled)}
							<span class="fold-note on">
								{t('panel.image.on', { n: image.adjustments.filter((a) => a.enabled).length })}
							</span>
						{/if}
					</summary>
				<div class="imagefx">
					<div class="fx-head">
						<button
							class="rot"
							disabled={edits.busy || !image?.adjustments.some((a) => a.enabled)}
							onclick={() => onImageClear?.()}
						>{t('panel.image.clearAll')}</button>
					</div>

					{#each image?.adjustments ?? [] as item (item.name)}
						<div class="fx" class:on={item.enabled}>
							<label class="fx-toggle">
								<input
									type="checkbox"
									checked={item.enabled}
									disabled={edits.busy}
									onchange={(e) => onImageSet?.(item.name, e.currentTarget.checked, null)}
								/>
								<span>{item.label}</span>
							</label>
							{#if item.enabled}
								{#each Object.entries(item.values) as [key, value] (key)}
									{#if item.ranges[key]}
										<label class="fx-value">
											<span>{key}</span>
											<input
												type="range"
												min={item.ranges[key][0]}
												max={item.ranges[key][1]}
												step={key === 'radius' || key === 'factor' ? 0.1 : 1}
												{value}
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, {
														[key]: Number(e.currentTarget.value)
													})}
											/>
											<span class="mono fx-num">{value}</span>
										</label>
									{:else if key === 'type' && item.name === 'dither'}
										<label class="fx-value">
											<span>{t('panel.image.kind')}</span>
											<select
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, { type: e.currentTarget.value })}
											>
												{#each image?.dither_types ?? [] as option (option)}
													<option value={option} selected={option === value}>{option}</option>
												{/each}
											</select>
										</label>
									{/if}
								{/each}
							{/if}
						</div>
					{/each}

					<div class="fx-actions">
						<!-- Vectorise, crop and undo the crop used to be here. They are
						     actions, so they live in the image's context menu. What stays is
						     DPI: that is a property of this image and belongs with the rest of
						     the recipe. -->
						<label class="dpi mono">
							DPI
							<input
								type="number"
								min="10"
								max="2000"
								step="10"
								value={selected.image.dpi ?? 96}
								onchange={(e) => onImageDpi?.(Number(e.currentTarget.value))}
							/>
						</label>
					</div>
				</div>
				</details>
			{/if}

			<!-- "To another sheet" was here as a collapsed fold with a button per sheet.
			     It is an action and now lives in the context menu under "To another
			     sheet" — with the same sheet names, without unfolding first. -->

			<p class="hint">
				{#if canEdit}
					{t('panel.dragHint')}
				{:else}
					{t('panel.needsToken')}
				{/if}
			</p>
		</div>
	</div>
{/if}

{#if show === 'selection' && !selected}
	<div class="section">
		<p class="muted">{t('panel.nothingSelected')}</p>
	</div>
{/if}

{#if show === 'layers'}
	<div class="section">
		<div class="section-head">
			<h2 class="section-title">{t('panel.layers')}</h2>
			{#if plainLayers.length}
				<!-- What the number on the chip means is said once. Without it the list
				     reads as an arbitrary stack instead of as the order the machine works
				     in. -->
				<span class="order-note mono">{t('panel.burnOrder', { n: plainLayers.length })}</span>
			{/if}
		</div>

		{#if plainLayers.length > 1}
			<!--
				The bar above the list: one menu and one switch.

				There used to be four buttons on three lines here — sort, remove all,
				clear out empty layers, and the density. Three of those are verbs about
				the whole list, and by the placement rule those belong in a menu
				(DESIGN-SYSTEM v4). What stays is the density, because that is a way of
				looking, and the tidy-up line — which reports a *state* ("there are empty
				layers") and offers the way out in the same line.
			-->
			<div class="list-bar">
				{#if canEdit}
					<button
						class="listmore"
						aria-haspopup="menu"
						title={t('panel.list.title')}
						onclick={(e) => {
							const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
							rijMenu = {
								x: box.left,
								y: box.bottom + 4,
								list: [
									{
										items: [
											{
												id: 'sorteer',
												label: t('panel.list.sort'),
												explain: t('panel.list.sort.explain'),
												off: gesorteerd.kanSorteren ? undefined : t('panel.list.sort.already'),
												run: sorteerLagen
											},
											{
												id: 'ruim',
												label: legeLagen.length
													? t('panel.list.pruneCount', { n: legeLagen.length })
													: t('panel.list.prune'),
												explain: t('panel.list.prune.explain'),
												off: legeLagen.length ? undefined : t('panel.list.prune.none'),
												run: () => onPrune?.()
											}
										]
									},
									{
										items: [
											{
												id: 'alles-gone',
												label: t('panel.list.dropAll'),
												explain: t('explain.layerRemove'),
												danger: true,
												run: () => (confirmDropAll = true)
											}
										]
									}
								]
							};
						}}
					>
						{t('panel.list')}
						<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
					</button>
				{/if}
				<span class="list-stretch"></span>
				<button
					class="dichtheid"
					aria-pressed={compact}
					title={compact ? t('panel.density.compact') : t('panel.density.roomy')}
					onclick={compactSchakel}
				>
					<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if compact}
							<path d="M4 7h16M4 12h16M4 17h16" />
						{:else}
							<path d="M4 8h16M4 16h16" />
						{/if}
					</svg>
					{compact ? t('panel.density.compactLabel') : t('panel.density.roomyLabel')}
				</button>
			</div>
			{#if canEdit && legeLagen.length}
				<!-- A state with its way out in the same line. As a button in the bar it
				     was there even when there was nothing to clear out; as a line it is
				     only there when it means something, and then it says how many. -->
				<p class="tidyrow">
					{t('panel.empties', { n: legeLagen.length })}
					<button class="alsLink" disabled={edits.busy} onclick={() => onPrune?.()}
						>{t('panel.tidyUp')}</button
					>
				</p>
			{/if}
		{/if}
		{#if confirmDropAll}
			<!-- Say what goes and what stays. Throwing away a layer must not throw away
			     work, and that has to be readable here before you click — the same rule
			     as when removing a sheet. -->
			<div class="confirm">
				<span>
					{t('panel.dropAll.ask', { n: plainLayers.length })}
					{#if design.elements.length === 1}
						{t('panel.dropAll.oneShape')}
					{:else if design.elements.length}
						{t('panel.dropAll.shapes', { n: design.elements.length })}
					{:else}
						{t('panel.dropAll.noShapes')}
					{/if}
					{#if gridGroups.length}
						{t('panel.dropAll.gridsStay')}
					{/if}
				</span>
				<button class="rot" onclick={() => (confirmDropAll = false)}>{t('common.cancel')}</button>
				<button class="rot drop" disabled={edits.busy} onclick={dropAllLayers}>
					{t('panel.dropAll.confirm')}
				</button>
			</div>
		{/if}
		{#if !operations.length}
			<p class="muted">{t('panel.noLayers')}</p>
		{/if}
		{#each plainLayers as op, index (op.id)}
			{@const open = editingLayer === op.id}
			{@const percent = powerPercent(op)}
			<div
				class="layer"
				class:compact
				class:off={!op.output}
				class:onzichtbaar={design.isLayerHidden(op.id)}
				class:open
				class:sleept={dragging?.id === op.id}
				class:sleep-modus={dragging != null}
				class:target-boven={dragging != null && dragging.id !== op.id && dragging.to === index && index < dragging.from}
				class:target-onder={dragging != null && dragging.id !== op.id && dragging.to === index && index > dragging.from}
				bind:this={rijElementen[index]}
				role="presentation"
				oncontextmenu={(e) => {
					e.preventDefault();
					opendLaagMenu(op, index, e.clientX, e.clientY);
				}}
			>
				<div class="ident">
					{#if canEdit && plainLayers.length > 1}
					<!--
						One grip for the order, not three.

						There used to be a column of three here: an up arrow, the drag grip, a
						down arrow. Those arrows came in for gap L9 — dragging and the arrow
						keys were invisible grips, and there had to be something that explains
						itself. That argument has lapsed: since the previous round every layer
						row has a context menu with the words "Burn earlier" and "Burn later" in
						it, and *that* explains itself better than an 11 px arrow. What is left
						is the grip, with the same arrow keys on it.

						Gain: two buttons fewer per row (ten in a list of five), and the row no
						longer has to be three buttons tall.
					-->
					<button
						class="grip"
						aria-label={t('panel.layer.dragAria', { label: op.label })}
						title={t('panel.layer.dragTitle')}
						disabled={edits.busy}
						onpointerdown={(e) => startSleep(e, op.id, index)}
						onpointermove={beweegSleep}
						onpointerup={eindSleep}
						onpointercancel={() => (dragging = null)}
						onkeydown={(e) => {
							if (e.key === 'ArrowUp' && index > 0) {
								e.preventDefault();
								moveLayer(op.id, 'up');
							} else if (e.key === 'ArrowDown' && index < plainLayers.length - 1) {
								e.preventDefault();
								moveLayer(op.id, 'down');
							}
						}}
					>
						<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
							<circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" />
							<circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" />
							<circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" />
						</svg>
					</button>
					{/if}
					<!-- The number on the chip *is* the burn order. Clicking opens the
					     layer, so the colour is also the way to its settings. -->
					<button
						class="chip mono"
						style="background: {design.colorFor(op.id)}; color: {inkOn(
							design.colorFor(op.id)
						)}"
						disabled={!canEdit}
						title={t('panel.layer.chipTitle', { n: index + 1, total: plainLayers.length })}
						aria-expanded={open}
						aria-label={t('panel.layer.openAria', { label: op.label })}
						onclick={() => (editingLayer = open ? null : op.id)}
					>{index + 1}</button>
					<!-- One line for the identity. The element count went to the value line:
					     with name and count stacked, a row is 186 px tall on a tablet and
					     three layers fit on a screen. -->
					<div class="layer-name">{op.label}</div>
					<!-- Only the number, next to the name. Put on the value line the row
					     became 96 px: that line is genuinely full with three fields (215 of
					     218 px, as the note there already said). What the number means is in
					     the tooltip; zero stands out because the column aligns. -->
					<span class="count" title={t('panel.layer.count', { n: op.element_ids.length })}
						>{op.element_ids.length}</span
					>
					{#if canEdit}
						<!-- Burn-along belongs in the row: it is the switch you touch most
						     often while working, and hidden in a submenu you cannot see which
						     layers are off. -->
						<button
							class="out"
							class:on={op.output}
							role="switch"
							aria-checked={op.output}
							title={op.output ? t('panel.layer.burnsOn') : t('panel.layer.burnsOff')}
							aria-label={t('panel.layer.burnsAria', { label: op.label })}
							disabled={edits.busy}
							onclick={() => patchLayer(op.id, { output: !op.output })}
						>
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
								<path d="M12 3v9" />
								<path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
							</svg>
						</button>
						<!-- Decision B4: visible and burn-along are two things. Keeping an
						     alignment box on the canvas without burning it is a standard
						     trick, and with one switch that is impossible. Visibility is a way
						     of looking: it does not go to the engine and so changes nothing
						     about what gets burned.

						     In compact mode this one moves into the fold. Measured on a
						     tablet: with both 44 px switches side by side the layer name has
						     30 px left and reads "Cu…" — and a list in which you cannot tell
						     the layers apart is not a compact list but an unreadable one.
						     Burn-along stays in the row, because that is the switch you touch
						     while working; hiding you do once. *That* a layer is hidden stays
						     in the row as a word.

						     The eye used to be here, next to the on/off switch and the ⋯.
						     Three 28 px touch targets plus the chip, the grip and the count
						     left the layer name 37 of 215 px — measured, and that is why it
						     read "Out-si-…". Hiding you do once per layer and it is in the row
						     menu.

						     The ⋯ did the same as the chip beside it: open the fold. Two
						     buttons for one operation, while the row menu could only be found
						     with the right mouse button. Now the chip opens the settings and
						     the ⋯ the menu — two different things, and the way to the menu has
						     become visible. -->
						<button
							class="more"
							aria-haspopup="menu"
							title={t('panel.layer.moreTitle', { label: op.label })}
							aria-label={t('panel.layer.moreAria', { label: op.label })}
							onclick={(e) => {
								const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
								opendLaagMenu(op, index, box.right - 200, box.bottom + 4);
							}}
						>⋯</button>
					{/if}
				</div>

				<!-- Speed, power and passes are fields in the row itself. That is the whole
				     reason this panel exists: adjusting next to a running machine must not
				     cost a submenu.

				     Compact (gap L5) is the exception: there the values are one readable
				     line and the fields move into the fold. Three fields beside a name and
				     three switches do not fit in a 280 px panel without wrapping, and then
				     the row is two lines tall again and nothing has been gained. -->
				<div class="vals">
					{#if canEdit && compact}
						<button
							class="short mono"
							title={t('panel.layer.valuesTitle')}
							aria-expanded={open}
							aria-label={t('panel.layer.valuesAria', { label: op.label, values: short(op) })}
							onclick={() => (editingLayer = open ? null : op.id)}
						>{short(op)}</button>
					{:else if canEdit}
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="0.1"
								inputmode="decimal"
								aria-label={t('panel.layer.speedAria', { label: op.label })}
								value={op.speed ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'speed', op.speed)}
							/><span>mm/s</span>
						</label>
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								max="100"
								inputmode="numeric"
								aria-label={t('panel.layer.powerAria', { label: op.label })}
								value={percent ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'power_percent', percent)}
							/><span>%</span>
						</label>
						<label class="val narrow">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								inputmode="numeric"
								aria-label={t('panel.layer.passesAria', { label: op.label })}
								value={op.passes ?? 1}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'passes', op.passes ?? 1)}
							/><span>×</span>
						</label>
					{:else}
						{#each describe(op) as value (value)}
							<span class="pill mono">{value}</span>
						{/each}
					{/if}
					{#if !op.output}
						<!-- Colour alone is not enough: this is here in words too, because it
						     is the difference between "it has been cut" and "I forgot
						     it". -->
						<span class="tag">{t('panel.tag.doesNotBurn')}</span>
					{/if}
					{#if design.isLayerHidden(op.id)}
						<!-- And this is the other half of B4: hidden says nothing about
						     burning. Two separate words, because two separate states. -->
						<span class="tag zicht">{t('panel.tag.hidden')}</span>
					{/if}
					{#if design.layerCapabilities.air_assist && (compact || op.air_assist)}
						<!-- Air assist in the row (decision B11, gap L10).
						     It used to sit here as a dead word once it was on; now it is a
						     switch, because whether the blower joins in is the difference
						     between a clean cut and a scorched edge, and you flip that per
						     material. Switching it off cost a tap into the fold and a tap
						     back until now.

						     Why it only appears in roomy mode when it is *on*, and always in
						     compact: measured with four layers at 1440 and 1024. In compact
						     mode the pill fits beside the value line and the row stays 36 px
						     (desktop) and 54 px (tablet) — exactly the sizes from L5. In roomy
						     mode the value line is already full (215 of 218 px on desktop) and
						     the pill drops to a third line: 76 → 101 px, and on a tablet
						     111 → 159 px. That is half the list gone for a switch you rarely
						     touch. LightBurn does fit it on one line, but their panel is
						     480–512 px; ours has 280.

						     So in roomy mode switching on happens in the fold, switching off
						     can be done from the row — that is the side with the hurry in it.

						     The pill only appears when the driver has a command that really
						     switches the blower; on a Ruida there is none (L8). -->
						<button
							class="tag air"
							class:off={!op.air_assist}
							role="switch"
							aria-checked={op.air_assist}
							aria-label={t('panel.air.aria', { label: op.label })}
							title={op.air_assist ? t('panel.air.on') : t('panel.air.off')}
							disabled={edits.busy}
							onclick={() => patchLayer(op.id, { air_assist: !op.air_assist })}
						>{t('panel.tag.air')}</button>
					{/if}
					{#if canEdit && selectedIds.length}
						<!-- Assigning is at the end and not before the name: otherwise the
						     whole row shifts the moment you select something. -->
						<button
							class="assign"
							class:in={membership(op.id) === 'all'}
							class:partly={membership(op.id) === 'some'}
							aria-pressed={membership(op.id) === 'all'}
							title={t('panel.assign.title', { label: op.label })}
							disabled={edits.busy}
							onclick={() => onAssign?.(op.id, membership(op.id) !== 'all')}
						>{membership(op.id) === 'all' ? '✓' : membership(op.id) === 'some' ? '–' : '+'}
							{t('panel.assign.label')}</button>
					{/if}
				</div>
			</div>

			{#if canEdit && open}
				{@const onthouden = design.memoryFor(design.colorFor(op.id))}
				<div class="layer-edit">
					{#if compact}
						<!-- In compact mode the fields are here, because there is no room in
						     the row. Same fields, same behaviour — just one line lower. -->
						<div class="vals wide">
							<label class="val">
								<input
									class="mono"
									type="number"
									step="1"
									min="0.1"
									inputmode="decimal"
									aria-label={t('panel.layer.speedAria', { label: op.label })}
									value={op.speed ?? ''}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'speed', op.speed)}
								/><span>mm/s</span>
							</label>
							<label class="val">
								<input
									class="mono"
									type="number"
									step="1"
									min="1"
									max="100"
									inputmode="numeric"
									aria-label={t('panel.layer.powerAria', { label: op.label })}
									value={percent ?? ''}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'power_percent', percent)}
								/><span>%</span>
							</label>
							<label class="val narrow">
								<input
									class="mono"
									type="number"
									step="1"
									min="1"
									inputmode="numeric"
									aria-label={t('panel.layer.passesAria', { label: op.label })}
									value={op.passes ?? 1}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'passes', op.passes ?? 1)}
								/><span>×</span>
							</label>
						</div>
					{/if}
					<div class="swatches" role="group" aria-label={t('panel.colourAria', { label: op.label })}>
						{#each LAYER_COLORS as swatch (swatch)}
							<button
								class="swatch"
								class:picked={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								style="background: {swatch}"
								title={t('panel.swatch', { colour: swatch })}
								aria-label={t('panel.swatch', { colour: swatch })}
								aria-pressed={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								disabled={edits.busy}
								onclick={() => patchLayer(op.id, { color: swatch })}
							></button>
						{/each}
					</div>

					<!-- What this colour has remembered on this machine (decision B2). It
					     says in so many words that it is not a preset: a preset belongs to a
					     material and a thickness and says something has been burned. This
					     only says what you last did here, and that must never pass for
					     evidence. -->
					<p class="memory wide">
						{#if onthouden?.speed_mm_s}
							{t('panel.memory.remembered', {
								values: `${onthouden.speed_mm_s} mm/s${
									onthouden.power_percent == null
										? ''
										: ` · ${Math.round(onthouden.power_percent)}%`
								}`,
								machine: onthouden.machine_name ?? t('panel.memory.thisMachine')
							})}
						{:else}
							{t('panel.memory.none')}
						{/if}
					</p>

					<label class="wide">
						<span>{t('panel.name')}</span>
						<input
							type="text"
							value={op.label}
							onchange={(e) => patchLayer(op.id, { label: e.currentTarget.value })}
						/>
					</label>

					<!-- What this layer does, changeable after creating it (gap L3). Making a
					     cut layer into an engrave layer could only be done by throwing it away
					     and redoing every assignment; LightBurn has a dropdown for it in the
					     row. The shapes and the settings come along. -->
					<div class="kind wide">
						<span class="rot-label">{t('panel.kind')}</span>
						<Segmented
							label={t('panel.kindOf', { label: op.label })}
							options={LAYER_TYPES.map(({ value, label }) => ({ value, label }))}
							disabled={edits.busy}
							bind:value={() => kindOf(op.type), (value) => retypeLayer(op.id, value)}
						/>
						<p class="hint">{t('panel.kind.hint')}</p>
					</div>

					{#if compact}
						<!-- The way-of-looking switch from the row, here as a checkbox (see the
						     note about the eye in the row). Same behaviour, same explanation:
						     this changes nothing about what gets burned. -->
						<label class="check wide">
							<input
								type="checkbox"
								checked={!design.isLayerHidden(op.id)}
								onchange={() => design.toggleLayer(op.id)}
							/>
							<span>{t('panel.visibleOnCanvas')}</span>
						</label>
					{/if}

					{#if design.layerCapabilities.air_assist}
						<!-- Decision B11: only visible when the driver has a command for it. The
						     same rule as with the Z axis — what the machine *can* do decides
						     what you see. If the switch is not there, this machine has no
						     method set up to drive the blower. -->
						<label class="check wide">
							<input
								type="checkbox"
								checked={op.air_assist}
								disabled={edits.busy}
								onchange={(e) => patchLayer(op.id, { air_assist: e.currentTarget.checked })}
							/>
							<span>{t('panel.airDuring')}</span>
						</label>
					{/if}

					{#if design.layerCapabilities.z_step}
						<!-- Dropping per pass, the same rule as with air assist (B11): only
						     visible when the driver has a Z axis that it really moves. So on a
						     Ruida this field is not there, because it would do nothing. The
						     engine does not know this by itself — to it a pass is a counter on
						     one cutcode object — so we build it up in the plan, with a
						     `z_move` between the passes and a move back to the starting height
						     after the last one. -->
						<div class="zstep wide">
							<NumberField
								label={t('panel.zStep')}
								unit="mm"
								value={String(op.z_step_mm ?? 0)}
								step={0.1}
								min={-20}
								max={20}
								disabled={edits.busy}
								onchange={(v) => patchLayer(op.id, { z_step_mm: Number(v) })}
							/>
							<p class="hint">
								{#if !op.z_step_mm}
									{t('panel.zStep.off')}
								{:else if (op.passes ?? 1) < 2}
									{t('panel.zStep.onePass')}
								{:else}
									{t('panel.zStep.explain', {
										passes: op.passes,
										step: i18n.number(Math.abs(op.z_step_mm)),
										direction: t(op.z_step_mm > 0 ? 'panel.zStep.lower' : 'panel.zStep.higher')
									})}
								{/if}
							</p>
						</div>
					{/if}

					{#if op.type === 'op raster' || op.type === 'op image'}
						<!-- Only rastering uses these; on a cut they are meaningless. -->
						<!-- Each over the full width: a stepper is two 38 px buttons plus a
						     field, and in a half column of 112 px there is nothing left for
						     "2000". -->
						<div class="steppers wide">
						<NumberField
							label="DPI"
							value={String(op.dpi ?? 500)}
							step={10}
							min={10}
							max={2000}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { dpi: Number(v) })}
						/>
						<NumberField
							label={t('panel.overscan')}
							unit="mm"
							value={String(parseFloat(op.overscan ?? '0.5') || 0)}
							step={0.5}
							min={0}
							max={50}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { overscan_mm: Number(v) })}
						/>
						</div>
						<label class="check wide">
							<input
								type="checkbox"
								checked={op.bidirectional}
								onchange={(e) =>
									patchLayer(op.id, { bidirectional: e.currentTarget.checked })}
							/>
							<span>{t('panel.bidirectional')}</span>
						</label>
					{/if}

					<!-- Order is burn order: engrave first, only then cut, otherwise the
					     workpiece falls out of the sheet before the lettering is on it. -->
					<div class="order wide">
						<span class="rot-label">{t('panel.order', { kind: typeName(op.type) })}</span>
						<button
							class="rot"
							disabled={edits.busy || index === 0}
							title={index === 0 ? t('reason.alreadyFirst') : t('panel.order.burnEarlier')}
							onclick={() => moveLayer(op.id, 'up')}
						>↑ {t('panel.order.earlier')}</button>
						<button
							class="rot"
							disabled={edits.busy || index === plainLayers.length - 1}
							title={index === plainLayers.length - 1
								? t('reason.alreadyLast')
								: t('panel.order.burnLater')}
							onclick={() => moveLayer(op.id, 'down')}
						>↓ {t('panel.order.later')}</button>
					</div>

					{#if confirmDrop === op.id}
						<div class="confirm wide">
							<span>{t('panel.drop.ask', { label: op.label })}</span>
							<button class="rot" onclick={() => (confirmDrop = null)}>{t('common.cancel')}</button>
							<button class="rot drop" onclick={() => dropLayer(op.id)}
								>{t('panel.drop.confirm')}</button
							>
						</div>
					{:else}
						<button class="gone wide" onclick={() => (confirmDrop = op.id)}>
							{t('panel.drop.layer')}
						</button>
					{/if}
				</div>
			{/if}
		{/each}

		{#each gridGroups as group (group.id)}
			<div class="layer grid-row">
				<div class="ident">
					<span class="chip mono grid-chip">R</span>
					<div class="layer-name">
						<div class="op">{t('panel.grid.title', { id: group.id })}</div>
						<div class="obj">{t('panel.grid.cells', { n: group.ops.length })}</div>
					</div>
					<button
						class="more"
						aria-expanded={openGrid === group.id}
						aria-label={t('panel.grid.showCells', { id: group.id })}
						onclick={() => (openGrid = openGrid === group.id ? null : group.id)}
					>{openGrid === group.id ? '−' : '+'}</button>
				</div>
			</div>

			{#if openGrid === group.id}
				<div class="cells">
					{#each group.ops as op (op.id)}
						<label class="cell" title={t('panel.grid.cell', { row: op.grid?.row, column: op.grid?.column })}>
							<input
								type="checkbox"
								checked={op.output}
								disabled={!canEdit || edits.busy}
								onchange={(e) => patchLayer(op.id, { output: e.currentTarget.checked })}
							/>
							<span class="mono">{op.grid?.speed_mm_s}·{op.grid?.power_percent}%</span>
						</label>
					{/each}
					{#if canEdit}
						<button class="gone cells-remove" onclick={() => removeGrid(group.id)}>
							{t('panel.grid.remove')}
						</button>
					{/if}
				</div>
			{/if}
		{/each}
		{#if canEdit}
			<!-- Four fixed kinds: as one bar, so that at a glance you see what there is
			     to choose and what is set now. The button names what is coming —
			     otherwise the bar reads as a filter over the list above it. Below the
			     list, because you look at the layers that are already there more often
			     than you make one. -->
			<!--
				One button with a menu, instead of a label, four radio buttons and a
				button.

				It took five controls and three rows to do something you do a couple of
				times per project: choose a kind, press add. Now it is one button that
				unfolds the four kinds — the same number of taps, a fifth of the room, and
				the kind is in the menu under its name instead of as an abbreviated pill.
			-->
			<button
				class="add"
				aria-haspopup="menu"
				disabled={edits.busy}
				onclick={(e) => {
					const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
					rijMenu = {
						x: box.left,
						y: box.top - 8,
						upward: true,
						list: [
							{
								title: t('panel.addLayer'),
								items: LAYER_TYPES.map(({ value, label }) => ({
									id: `fresh-${value}`,
									label,
									run: () => {
										newLayerType = value;
										addLayer();
									}
								}))
							}
						]
					};
				}}
			>
				+ {t('panel.addLayer')}
			</button>
		{/if}
		<p class="hint">
			{#if selected}
				{t('panel.assign.hint', { into: t('panel.assign.label') })}
			{:else}
				{t('panel.assign.hintNone')}
			{/if}
		</p>
	</div>
{/if}

{#if rijMenu}
	<Menu
		menu={rijMenu.list}
		x={rijMenu.x}
		y={rijMenu.y}
		upward={rijMenu.upward ?? false}
		onClose={() => (rijMenu = null)}
	/>
{/if}

<style>
	.section + .section {
		margin-top: var(--space-6);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.empty,
	.muted {
		color: var(--text-2);
		margin: 0;
	}
	/* Two lines per layer: who it is, and what it does. More lines and the list becomes
	   a stack of cards you can no longer find anything in; fewer and the values can no
	   longer be tapped. */
	.layer {
		/* Anchor for the drag grip, which hangs in the left margin. */
		position: relative;
		display: grid;
		/* minmax(0, 1fr) and not the implicit auto column: that grows with the longest
		   layer name and then pushes the whole list out of the panel. */
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-1);
		/* A little more air on the left: the drag grip hangs in it. Putting it in the row
		   cost the layer name 20 px and then "Engrave" broke as "Eng-rave" — exactly the
		   readability the previous round had won. In the margin it costs ten pixels and
		   nothing of the name. */
		padding: var(--space-2) var(--space-2) var(--space-2) calc(var(--space-2) + 14px);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.layer .ident {
		display: flex;
		align-items: center;
		/* 6 px and not 8: with the drag grip added (L1) the layer name kept 53 px and
		   "Engrave" broke as "Eng-rave". Six times two pixels back gives the name
		   eighteen more, and that is exactly what it needed. */
		gap: var(--space-1h);
	}
	.layer + .layer {
		margin-top: var(--space-1);
	}
	/* We do not dim a switched-off layer away: you still have to be able to read it and
	   switch it on. Only the values fade, because they are doing nothing for now. */
	.layer.off .vals .val,
	.layer.off .vals .pill {
		opacity: 0.5;
	}
	.layer.off {
		border-style: dashed;
	}
	.layer.open {
		border-color: var(--accent);
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
	}
	/* ── Compact list (L5) ────────────────────────────────────────────────────
	   Identity and values on one line. The fields stay: this panel exists because
	   adjusting beside a running machine must not cost a submenu. What gives way is the
	   name — it may be truncated, because it is there in full in the roomy state and
	   always in the tooltip. */
	.layer.compact {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2) var(--space-1) calc(var(--space-2) + 10px);
	}
	/* The two switches may be tight in the compact state: they sit beside each other and
	   you aim at a 16 px icon, not at the edge of the surface. On a touch screen they
	   stay 44 px — that is handled by the media query at the bottom, which outweighs this
	   rule. */
	.layer.compact .out,
	.layer.compact .ident {
		flex: 1 1 12ch;
		min-width: 0;
		/* Four touch targets and a name in 247 px: every pixel goes to the name, because
		   that is the only thing in the row that is nowhere else. Measured: with the roomy
		   spacing the name kept 10 px and read "E". */
		gap: var(--space-1);
	}
	.layer.compact .vals {
		flex: 0 1 auto;
	}
	.layer.compact .layer-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.layer.compact .count {
		display: none;
	}
	/* The three values as one line. A button and not text: it opens the same expander as
	   the chip, so that you get to the field from the number you want to change. */
	.short {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		/* Bare, without a frame: a pill costs 14 px here that the layer name needs. That
		   it can be opened shows from the underline on hover and from `aria-expanded` —
		   and the chip beside it does the same. */
		padding: 0;
		white-space: nowrap;
	}
	.short:hover {
		color: var(--text-1);
		text-decoration: underline;
	}
	/* While dragging no text may be selected anywhere: the press starts on the grip, but
	   from there the browser looks for the next piece of selectable text and drew a blue
	   band all the way into the status bar. */
	.layer.sleep-modus,
	.layer.sleep-modus * {
		user-select: none;
	}
	/* ── The order column in the margin: ▲ / grip / ▼ (L1 and L9) ───────────
	   Three routes to the same action, and that is not a luxury: dragging is fastest with
	   a mouse, the arrow keys on the grip work without a mouse, and the buttons are the
	   only one of the three that explain themselves. LightBurn has that third one always
	   visible; we had it in the expander. */
	/* Off *and* dismissible: a layer that is already at the top cannot go higher. Making
	   it invisible would make the column jump, so it stays and merely goes quiet. */
	/* Below 1200 px they disappear. That is not arbitrary: the same bound where tokens.css
	   makes every button 44×44 because you work with a finger there. Three 44 px touch
	   targets stacked in a 111 px row is impossible, and 14 px wide arrows beside a 26 px
	   grip is a touch target you only hit by accident — measured: the global rule blew
	   them up to 44×44 in a 14 px column, straight across the card edge.
	   That leaves the grip: on a touch screen dragging is the gesture you expect, the
	   arrow keys on it do the same, and the ↑ Earlier / ↓ Later buttons are still in the
	   expander. */
	@media (max-width: 1199px), (pointer: coarse) {
	}
	/* ── Dragging to reorder (L1) ─────────────────────────────────────────── */
	.grip {
		flex: none;
		width: 14px;
		height: 22px;
		/* Dragging must not select text: the first version drew a blue selection across
		   half the screen on every drag movement. */
		user-select: none;
		display: grid;
		place-items: center;
		border-radius: var(--radius-field);
		color: var(--text-2);
		cursor: grab;
		touch-action: none;
	}
	.grip:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* What you are holding sits apart from the list: lifted and slightly transparent, so
	   that you see the row underneath where it will land. */
	.layer.sleept {
		opacity: 0.65;
		border-color: var(--accent);
		box-shadow: var(--shadow-float);
		cursor: grabbing;
	}
	/* The destination, as a line against the row. A line and not an opened gap: the list
	   must not slide under your finger, or you will bad-aim. */
	.layer.target-boven {
		box-shadow: inset 0 3px 0 0 var(--accent);
	}
	.layer.target-onder {
		box-shadow: inset 0 -3px 0 0 var(--accent);
	}
	.list-bar {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.list-stretch { flex: 1; }
	/* The list menu: the same shape as the density switch beside it, because they are in
	   the same bar and should not fight for attention. */
	.listmore {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		padding: var(--space-1) var(--space-2);
		font: inherit;
		font-size: var(--text-xs);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.listmore:hover { background: var(--surface-2); color: var(--text-1); }
	/* A state with its way out on the same line. */
	.tidyrow {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.alsLink {
		padding: 0;
		border: none;
		background: none;
		font: inherit;
		font-weight: 500;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.alsLink:disabled { opacity: 0.5; text-decoration: none; }
	.dichtheid {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		margin-left: auto;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		color: var(--text-2);
		background: var(--surface-1);
	}
	.dichtheid:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.kind {
		display: grid;
		gap: var(--space-1);
	}
	.kind :global(.segmented) {
		width: 100%;
	}
	/* The field with its explanation as one block: the sentence below it says what
	   happens at this number of passes, and that belongs beside the number. */
	.zstep {
		display: grid;
		gap: var(--space-1);
	}
	/* Four words in 222 px: with the standard 12 px spacing per side "Engrave" ran over
	   its own segment and read "Engrav". The letters stay on the type scale; only the air
	   around them shrinks. */
	.kind :global(.segmented button) {
		padding-left: var(--space-1);
		padding-right: var(--space-1);
	}
	.chip {
		width: 26px;
		height: 26px;
		flex: none;
		border-radius: var(--radius-field);
		display: grid;
		place-items: center;
		font-size: var(--text-xs);
		font-weight: 600;
		/* The ink comes from inkOn() as an inline style; this is only the fallback for a
		   colour that cannot be parsed. */
		color: var(--on-color);
		border: 0;
		padding: 0;
	}
	.chip:not(:disabled):hover {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px currentColor;
	}
	/* Burning along: a button with an on state, not a tick you have to hit. */
	.out {
		flex: none;
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.out.on {
		border-color: color-mix(in srgb, var(--ok) 55%, var(--line));
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		color: var(--ok);
	}
	.out:hover:not(:disabled) {
		background: var(--surface-2);
	}
	/* Visibility sits beside burning-along and deliberately looks *different*: this is a
	   viewing state, not a machine state. Hence neutral grey where burning-along goes
	   green — colour is reserved here for what the laser is going to do. */
	/* A hidden layer may still be read — it is not switched off, it is just not on the
	   bed for the moment. The name fades, the buttons do not. */
	.layer.onzichtbaar .layer-name,
	.layer.onzichtbaar .count {
		opacity: 0.55;
	}
	.tag.zicht {
		color: var(--text-2);
		font-weight: 400;
	}
	/* Air assist on: not a warning, so not in amber. A state you have to be able to see,
	   in the ordinary text colour with a border around it. */
	.tag.air {
		color: var(--text-1);
		font-weight: 400;
		border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line));
		border-radius: var(--radius-dot);
		padding: 0 var(--space-2);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
	}
	/* Off is not an empty spot but a struck-through word: doubly encoded, so that it can
	   be read without a difference in colour too — and so that "this machine cannot do
	   it" (no pill) stays something other than "it is switched off". */
	.tag.air.off {
		color: var(--text-2);
		border-color: var(--line);
		background: transparent;
		text-decoration: line-through;
	}
	.tag.air:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--text-1);
	}
	.memory {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: var(--space-2);
	}
	.more {
		flex: none;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		line-height: 1;
	}
	.more:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.vals {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}
	/*
	   A value with its unit as one thing: the field belongs with "mm/s", so they share a
	   border and the unit cannot be clicked.

	   Bare until you point at it. Three framed pills per row turned a list of five layers
	   into fifteen boxes — 44 buttons in the panel, and the numbers you want to compare
	   with each other disappeared between the borders. They can still be changed on the
	   spot (that is the reason this panel exists), but the border only comes when you are
	   going to do something with it. On hover *and* on focus, so with the keyboard it is
	   there too.
	*/
	.val {
		display: inline-flex;
		align-items: center;
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		background: transparent;
		overflow: hidden;
		transition: background var(--transition), border-color var(--transition);
	}
	.val:hover {
		border-color: var(--line);
		background: var(--surface-2);
	}
	.val:focus-within {
		border-color: var(--accent);
		background: var(--surface-2);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	.val input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		width: 4.2em;
		min-width: 0;
		text-align: right;
		padding: var(--space-1) 2px var(--space-1) var(--space-2);
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.val.narrow input {
		width: 2.4em;
	}
	/* The browser's own spinner is two pixels tall; with gloves on you cannot hit it and
	   it eats the width the number needs. */
	.val input::-webkit-outer-spin-button,
	.val input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.val input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.val span {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 0 var(--space-2) 0 2px;
		white-space: nowrap;
	}
	.tag {
		color: var(--warn);
		font-weight: 500;
	}

	/* The name may run over two lines: "Outer cut 3…" and "Contour engra…" cannot be
	   told apart, and the tail is precisely what the user typed themselves. A row that
	   grows for a name is honest; a row that clips a name to stay the same height is
	   not. */
	.layer-name {
		flex: 1;
		min-width: 0;
		font-weight: 500;
		line-height: 1.25;
		overflow: hidden;
		/* break-word and not anywhere: anywhere chops "Inner cuts" into "Inner cut / s",
		   even when it does just fit. */
		overflow-wrap: break-word;
		/* Breaks a word that is too long on a syllable rather than in the middle. */
		hyphens: auto;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
	}
	.layer-name .op {
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.layer-name .obj {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.count {
		flex: none;
		min-width: 1.6em;
		text-align: center;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.pill {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.hint {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.section-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.section-head .section-title { margin-bottom: 0; }
	.tally {
		flex: 1;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* No nowrap: on a tablet this line is wider than the panel, and then it pushes the
	   whole list sideways off screen instead of breaking. */
	.order-note {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Beside the machine you operate this with a finger, sometimes with a glove. The
	   global rule makes buttons 44 px tall but not wide enough, and the input fields fall
	   outside it entirely. */
	@media (max-width: 1199px), (pointer: coarse) {
		.chip,
		.out,
		.more {
			width: 44px;
			height: 44px;
			min-height: 44px;
		}
		/* The grip is narrower than the rest but just as tall: it has to be grabbable
		   with a finger without pushing the name out of the row. */
		.grip {
			width: 26px;
			height: 44px;
			min-height: 44px;
		}
		/* With a finger the grip is wider, so the margin it hangs in is too. */
		.layer {
			padding-left: calc(var(--space-2) + 20px);
		}
		.layer.compact {
			padding-left: calc(var(--space-2) + 20px);
		}
		.dichtheid {
			min-height: 44px;
		}
		.val input {
			/* 44 px tall, even though this is not a <button> and the global rule does not
			   catch it. With a glove on you would otherwise bad-aim here. */
			padding: var(--space-3) 2px var(--space-3) var(--space-2);
			width: 3.6em;
		}
		.val.narrow input {
			width: 2.2em;
		}
		.assign {
			min-height: 44px;
		}
		/* Three 44 px touch targets beside a name do not fit in 290 px. The number of
		   shapes goes first: that is also in the chip's tooltip and in the panel below
		   it, the name is nowhere else. */
		.count {
			display: none;
		}
		.layer .ident {
			gap: var(--space-1);
		}
		/* For a finger every swatch has to make the 44 px the rest has too. */
		.swatch {
			height: 44px;
			min-height: 44px;
		}
		/* Order and delete must not touch each other: one bad-aimed tap further along
		   costs you a layer with all its assignments. */
		.layer-edit .gone,
		.confirm .drop {
			margin-left: var(--space-6);
		}
		.layer-edit .gone {
			margin-top: var(--space-6);
		}
	}
	.edit-error {
		margin: 0 0 var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
	.imagefx { display: grid; gap: 4px; }
	.fx-head { display: flex; align-items: center; gap: var(--space-2); }
	.fx {
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: 4px 8px;
	}
	.fx.on { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
	.fx-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.fx-value {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.fx-value input[type='range'] { flex: 1; }
	.fx-value select {
		flex: 1;
		font: inherit;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.fx-num { min-width: 3em; text-align: right; }
	.fx-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 4px; }
	.dpi { display: flex; align-items: center; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.dpi input {
		width: 4.5em;
		font: inherit;
		padding: 2px 4px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stray {
		border: 1px solid color-mix(in srgb, var(--warn) 50%, var(--line));
		border-radius: var(--radius-card);
		background: color-mix(in srgb, var(--warn) 8%, transparent);
		display: grid;
		gap: 8px;
	}
	.stray p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	.tip {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	/* No margin of its own any more: the selection card is a grid with one gap, and a
	   group that added its own spacing on top of it made the rhythm erratic *and* the
	   panel longer. */

	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
		margin-right: var(--space-1);
	}
	.rot {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.rot:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.rot:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.grid-row .grid-chip { background: var(--text-2); }
	.cells {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-top: none;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
		margin-bottom: 8px;
	}
	.cell {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 2px 4px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.cell input { width: 12px; height: 12px; accent-color: var(--accent); }
	.cells-remove {
		flex-basis: 100%;
		text-align: left;
		font-size: var(--text-xs);
		color: var(--danger);
		margin-top: var(--space-1);
	}
	/* The button names the outcome, not the action — see DESIGN-SYSTEM, "the primary
	   button says *what* is coming". */
	.add {
		width: 100%;
		padding: 8px;
		font: inherit;
		font-size: var(--text-xs);
		font-weight: 500;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--accent);
	}
	.add:hover:not(:disabled) { background: var(--surface-2); }
	.add:disabled { opacity: 0.45; cursor: not-allowed; }
	.layer-edit {
		display: grid;
		/* minmax(0, 1fr): a 1fr column does not shrink below the min-content of what is
		   in it, and a stepper with two 38 px buttons then pushes the column wider than
		   the panel. */
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
		padding: var(--space-3);
		margin: -1px 0 var(--space-1);
		border: 1px solid var(--accent);
		border-top: 0;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
	}
	.layer-edit label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.layer-edit .wide { grid-column: 1 / -1; }
	.steppers { display: grid; gap: var(--space-2); }
	.layer-edit label.check {
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
	}
	.layer-edit input[type='text'] {
		font: inherit;
		width: 100%;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Ten fixed colours, because a free colour picker produces tints that can no longer
	   be told apart on the canvas. */
	/* Five per row, on the desktop as well: ten in a row does not quite fit in a 280 px
	   panel and the last one then falls outside it. */
	.swatches {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 4px;
	}
	.swatch {
		width: auto;
		height: 24px;
		padding: 0;
		border: 1px solid var(--edge-on-color);
		border-radius: var(--radius-field);
	}
	.swatch.picked {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px var(--accent);
	}
	/* Label on its own line, the two buttons beside each other: let them wrap and on a
	   tablet there is one button per line. */
	.order {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		align-items: center;
		gap: var(--space-1);
	}
	.order .rot-label {
		grid-column: 1 / -1;
		margin: 0;
	}
	.order .rot {
		text-align: center;
	}
	/* Deleting stands apart from the rest and asks again: it takes the layer's
	   assignments with it and that cannot be typed back. */
	.confirm {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-2);
		border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--line));
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.confirm span { flex-basis: 100%; }
	.rot.drop { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
	/* A red text link, not a filled button: which is why the class is not called
	   `danger` — the safety net in tokens.css fills every `button.danger` solid red on
	   hover, and that belongs to a button that erases straight away. This one opens a
	   confirmation. */
	.layer-edit .gone {
		font-size: var(--text-xs);
		color: var(--danger);
		text-align: left;
		margin-top: var(--space-2);
	}
	/* Assign sits on the values line, not before the name: otherwise the whole row
	   shifts as soon as you select something. */
	.assign {
		font: inherit;
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.assign:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.assign.in {
		border-style: solid;
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}
	.assign.partly {
		border-style: solid;
		border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
		color: var(--text-1);
	}
	.selected {
		border: 1px solid var(--accent);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		display: grid;
		/* One rhythm for the whole block. Every group used to set its own margin-top,
		   which made the distances differ per row and the panel longer than the content
		   justifies. */
		gap: var(--space-3);
	}
	/* By default a grid item does not shrink below its content. Without this rule a long
	   element name — the engine sticks the id and the stroke colour after "Path", which is
	   thirty characters in no time — pushes the whole header row out of the card, and then
	   "Delete" falls off the panel. That is how it was on the screenshot and it cannot be
	   seen coming with the naked eye. */
	.selected > * {
		min-width: 0;
	}
	.selected .head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	/* The name may give way before the rest: it is the longest and the least critical —
	   what you are holding you also see on the canvas, "Delete" nowhere else. */
	/* The name keeps its width and the layer chips give way. "3 shapes" is short
	   and is what you are holding; "3 sha…" beside two full layer names is the
	   wrong half to lose. Measured in English, where the same header truncated and
	   the Dutch one did not — a language should not decide which half survives. */
	.selected .head .name { flex: 0 0 auto; }
	.selected .head .in-layers { flex: 1 1 auto; min-width: 0; overflow: hidden; }
	.selected .name {
		font-weight: 600;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.laagchip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 11ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.laagchip + .laagchip::before {
		content: ',';
		margin-right: 2px;
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		border: 1px solid color-mix(in srgb, currentColor 25%, transparent);
	}
	/* No layer means: this shape does not go into the machine. That is not an error, but
	   it is the only case here where you have to do something. */
	.geenlaag { color: var(--warn); }
	.in-layers {
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.clear {
		font-size: var(--text-xs);
		color: var(--accent);
		flex: none;
		margin-left: auto;
	}

	/* Two columns of numbers with the unit once on the right. A fixed grid rather than
	   wrapping pills: only that way is W above X and H above Y, and that is what makes the
	   four fields read as two pairs. */
	.figures {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
		align-items: end;
		gap: var(--space-1) var(--space-2);
	}
	.figures .f {
		display: flex;
		align-items: stretch;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		overflow: hidden;
		min-width: 0;
	}
	.figures .f:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	/* The label sits *in* the field and not above it: a separate label row above four
	   fields costs two lines of height for two characters of information. */
	.figures .f > span {
		display: grid;
		place-items: center;
		padding: 0 var(--space-1) 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		flex: none;
	}
	.figures input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		/* min-width: 0 and flex: 1 — without that a number input keeps its own minimum
		   width and "145.0" was truncated to "145.". That
		   stond zo op de tablet in beeld. */
		flex: 1;
		width: 100%;
		min-width: 0;
		text-align: right;
		padding: var(--space-1h) var(--space-2) var(--space-1h) 0;
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.figures input::-webkit-outer-spin-button,
	.figures input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.figures input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.figures input:disabled { opacity: 0.6; }
	.figures .unit {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding-bottom: var(--space-1h);
		text-align: center;
		min-width: 1.6em;
	}
	.figures .link {
		display: grid;
		place-items: center;
		width: 100%;
		min-width: 1.6em;
		height: 30px;
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.figures .link[aria-pressed='true'] {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.figures .link:hover:not(:disabled) { background: var(--surface-2); }

	/* Angle plus four steps on one row. The angle field deliberately gets more room than
	   a button: "337.5" has to fit in it, and a truncated number is worse than no number —
	   then you believe what is there. */
	.rotrow {
		grid-template-columns: minmax(4.6em, 1.6fr) repeat(4, minmax(0, 1fr));
		align-items: center;
	}
	.rotrow .f.angle > span:first-child {
		padding-right: 0;
		font-size: var(--text-sm);
	}
	.rotrow .f.angle input { padding-right: 0; }
	.figures .suffix {
		display: grid;
		place-items: center;
		flex: none;
		padding: 0 var(--space-2) 0 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.figures .f.mixed input { color: var(--text-2); }
	.icon.step {
		width: 100%;
		height: 30px;
	}
	.stepnum {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}

	/* The icon rows. Four per row, because four of 44 px fit with spacing in a 279 px
	   panel and six do not — and four also makes the layout coincide with the meaning: row
	   one horizontal, row two vertical. */
	/* Buttons without a border for the history and the rotation steps: those belong with
	   the field beside them, not with the grid below them. */
	.icon {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.icon:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.icon:disabled { opacity: 0.4; cursor: not-allowed; }

	/* The anchor: where you came from, and the way back. Neutral in colour — this is not
	   a warning but a note. */
	.anchor {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* The whole line carries the emphasis now: the change used to be bold inside
	   the sentence, and a message is one string — splitting it to keep the tag
	   would make the halves untranslatable. */
	.anchor-what { min-width: 0; color: var(--text-1); }
	.anchor-back {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		flex: none;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-size: var(--text-xs);
		color: var(--accent-text);
	}
	.anchor-back:hover:not(:disabled) { border-color: var(--accent); }

	/* Collapsed groups. The summary stays an ordinary readable line with a triangle —
	   you can find it without knowing it is there. */
	.fold {
		border-top: 1px solid var(--line);
		padding-top: var(--space-2);
		margin-top: calc(var(--space-1) * -1);
	}
	.fold summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-1);
		min-height: 24px;
	}
	/* Our own triangle. `display: flex` on a summary drops the browser's default marker,
	   and then a collapsed group cannot be told apart from a heading — precisely the reason
	   you must not hide such a group. */
	.fold summary::-webkit-details-marker { display: none; }
	.fold summary::marker { content: ''; }
	.fold summary::before {
		content: '';
		flex: none;
		width: 0;
		height: 0;
		border-left: 5px solid currentColor;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
		transition: transform 120ms ease;
	}
	.fold[open] summary::before { transform: rotate(90deg); }
	.fold summary:hover { color: var(--accent); }
	.fold-note {
		font-weight: 400;
		color: var(--text-2);
	}
	.fold-note.on {
		color: var(--accent-text);
		font-variant-numeric: tabular-nums;
	}
	.fold > :not(summary) { margin-top: var(--space-2); }

	/* Beside the machine with a finger. This block is deliberately right at the bottom:
	   the rules above have the same specificity, so whoever comes first loses — and when
	   this block was halfway up, the rotation row kept its six desktop columns and the card
	   ran out of the panel on the right. */
	@media (max-width: 1199px), (pointer: coarse) {
		/* Thick fingers: every target in the selection card makes 44 px, with at least
		   12 px between them. Since the icon grids moved to the action bar and the context
		   menu, this is only about the fields and their steps. */
		.icon,
		.icon.step,
		.figures .link {
			height: 44px;
			min-height: 44px;
		}
		.icon { width: 44px; }
		.figures { gap: var(--space-2) var(--space-3); }
		.figures input {
			/* 44 and not 43: the field just missed it because the wrapper's border eats two
			   pixels. */
			min-height: 44px;
			padding-top: var(--space-3);
			padding-bottom: var(--space-3);
		}
		.rotrow {
			/* The angle field and four 44 px buttons do not fit beside each other on a
			   tablet. So the field gets the full width; the steps keep their full touch area
			   on the row below. */
			grid-template-columns: repeat(4, minmax(0, 1fr));
		}
		.rotrow .f.angle { grid-column: 1 / -1; }
		.fold summary { min-height: 44px; }
		.anchor-back { min-height: 44px; }
	}
</style>
