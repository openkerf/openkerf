<script lang="ts">
	import { axisLabel, AXIS_UNIT, type GridAxis } from '$lib/api';
	import { i18n, t } from '$lib/i18n/index.svelte';
	// Numbers in the reader's own notation, and a refusal in the reader's own language
	// when the engine sent a code for it.
	import { apiError, mm, number } from '$lib/i18n/core.ts';
	import { operations, type LibraryStore } from '$lib/library.svelte';
	import NumberField from './NumberField.svelte';

	let {
		materialId = null,
		thicknessMm = null,
		library,
		canEdit = false,
		onGenerated
	}: {
		/** Pre-chosen material: from the sheet you are working on, or from the card
		 *  you came from. */
		materialId?: number | null;
		/** The thickness of that sheet. A grid is about one board, and that is already
		 *  in the machine — then this number is no longer a question. */
		thicknessMm?: number | null;
		library: LibraryStore;
		canEdit?: boolean;
		onGenerated?: (gridId: number) => void;
	} = $props();

	// Coming in from a material, that material is already filled in.
	$effect(() => {
		if (materialId === null) return;
		form.material_id = materialId;
	});
	// A sheet can carry a material id that no longer exists, for instance because the
	// material has been removed from the library. Without this fallback there is an
	// empty select — not "none" — and the warning below stayed away, because there
	// *was* something in the field. Only check once the list is in: empty means "not
	// loaded yet".
	$effect(() => {
		if (form.material_id === null || library.materials.length === 0) return;
		if (!library.materials.some((m) => m.id === form.material_id)) form.material_id = null;
	});
	// And the sheet's thickness with it: the grid is about the board that is in the
	// machine, so those two fields do not have to be filled in again.
	$effect(() => {
		if (thicknessMm === null) return;
		form.thickness_mm = String(thicknessMm);
	});

	type Cell = {
		row: number;
		column: number;
		speed_mm_s: number;
		power_percent: number;
		interval_mm: number | null;
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
	};

	/**
	 * The three quantities you can sweep (decision B12).
	 *
	 * Two of them sit on the axes, the third stays fixed. Passes is deliberately not
	 * among them: that multiplies the burn time of the whole board.
	 *
	 * Name and unit come from `$lib/api`, because the photo list on the phone
	 * summarises the same grids; two copies of "mm/s" are two chances to drift apart.
	 * What stays here is the wizard's input behaviour: the step size of the plus and
	 * minus and the field's upper bound.
	 */
	type As = GridAxis;
	const AS_ORDE: As[] = ['speed', 'power', 'interval'];
	const INVOER: Record<As, { step: number; max?: number }> = {
		speed: { step: 1 },
		power: { step: 5, max: 100 },
		interval: { step: 0.01, max: 5 }
	};
	/** Where the line spacing means something; when cutting the head lays one line. */
	const INTERVAL_OPERATIONS = ['graveren-raster'];

	let busy = $state(false);
	// The preview refreshes every 250 ms; that must not disable the main button.
	let busyPreview = $state(false);
	let error = $state<string | null>(null);
	/**
	 * Why the current input does not yet produce a board.
	 *
	 * Separate from `error`, because this is not a failure but an intermediate state.
	 * While typing from "5" to "30", "from" is briefly higher than "to", and that
	 * lasts exactly as long as it takes to adjust the second field too. Before this
	 * separation the whole preview block fell away then: the form jumped from 506 to
	 * 810 pixels wide and the reason sat below the fold. Now the last valid image
	 * stays up with this notice above it.
	 */
	let previewError = $state<string | null>(null);
	/**
	 * Which refusal the preview came back with, when the engine named one.
	 *
	 * The code is what lets a refusal be shown where its cause is. "There is no cut
	 * setting for this material at 3 mm" belongs under the cut-out switch that has just
	 * been turned on, not in the notice above the picture with everything else that can
	 * go wrong — a user who has to look for the reason reads it after the board is drawn.
	 */
	let previewErrorCode = $state<string | null>(null);
	let done = $state<{ id: number; cellen: number } | null>(null);
	/** One thing the engine says about the board that is nobody's refusal. */
	type Warning = { code: string; text: string };
	// The measures in the plan are numbers, row_axis/column_axis are words.
	type Plan = Record<string, number> & {
		row_axis?: As;
		column_axis?: As;
		/** Whether the row labels left of the grid still land on the bed. */
		label_room?: boolean;
		label_margin_mm?: number;
		/** Whether the whole board — caption and border included — still starts on the bed. */
		board_room?: boolean;
		anchor?: 'corner' | 'center';
		/** The board's own eight-character name, and the same in a form a person reads. */
		uid?: string;
		code_human?: string;
		warnings?: Warning[];
		/** On a board without a code or a cut-out these come back as null, not as 0. */
		code_enabled?: boolean;
		code_size_mm?: number | null;
		code_x_mm?: number | null;
		code_y_mm?: number | null;
		cutout_enabled?: boolean;
		cut_speed_mm_s?: number | null;
		cut_power_percent?: number | null;
		cut_passes?: number | null;
	};
	let preview = $state<{
		plan: Plan;
		cells: Cell[];
		engine?: { grid?: boolean };
	} | null>(null);

	let form = $state({
		material_id: null as number | null,
		caption: '',
		thickness_mm: '3',
		operation: 'snijden',
		row_axis: 'speed' as As,
		column_axis: 'power' as As,
		speed_min: '5',
		speed_max: '25',
		speed_steps: '4',
		power_min: '40',
		power_max: '80',
		power_steps: '4',
		interval_min: '0.05',
		interval_max: '0.3',
		interval_steps: '4',
		// The values of the quantity that is not on an axis.
		speed_mm_s: '15',
		power_percent: '60',
		interval_mm: '0.1',
		cell_mm: '8',
		gap_mm: '2',
		// The same for the whole board. The case: a material that almost cuts through
		// at 5 mm/s and that you want to try at 8 mm/s in two passes.
		passes: '1',
		// 20 and not 10: the row labels are engraved to the left of the grid and at
		// three-digit speeds are a good 17 mm wide. From 10 on, the board therefore
		// started off the bed, and then the wizard opens with a warning about its own
		// default values.
		origin_x_mm: '20',
		origin_y_mm: '20',
		// Gap T9: from the corner or from the centre. You put a test board on an
		// offcut, and then you know where the *centre* of that piece is.
		anchor: 'corner' as 'corner' | 'center',
		// Gap T10: LightBurn has Enable Text and Enable Border. Text is on — the board
		// is a piece of evidence — and the border is there for anybody who wants to
		// align the photo more easily.
		text: true,
		border: false,
		// The board's own name burned on the plank, and the tile cut loose from the sheet.
		// Both off, the same way the library's columns default (`code_enabled INTEGER NOT
		// NULL DEFAULT 0`, library.py:183) — a board that has always been a rectangle of
		// squares must not start costing burn time because the form learned two new tricks.
		code: false,
		code_size_mm: '18',
		cutout: false,
		label_speed_mm_s: '80',
		label_power_percent: '30'
	});

	/**
	 * The name of the board being previewed, sent back with every next preview.
	 *
	 * The planner mints a name when it is given none (`testgrid.py:437`), so a form that
	 * previews on every keystroke gets a new one every 250 ms — and the name is printed in
	 * the caption and burned in the code, so it would change under the reader's eyes
	 * between looking at it and pressing the button. Measured: three previews in a row gave
	 * `BF11HGMK`, `FB66KTY7` and `PBQ98RSY`. Holding it here makes the name a property of
	 * the board on screen. It is dropped when a board has been drawn, so the next one is a
	 * different plank with a different name.
	 */
	let boardUid = $state<string | null>(null);

	/** Under which key the fixed value of a quantity goes to the API. */
	const VAST_VELD: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	let intervalKan = $derived(INTERVAL_OPERATIONS.includes(form.operation));
	/**
	 * What the label layer is about: caption, border, or both (T10).
	 *
	 * The code is on this list because it burns in that same layer's speed — see
	 * `code_seconds` in `plan_grid`, which divides by `label_speed`. So a board that has
	 * only a code still needs these two fields, and the label above them has to name the
	 * thing they act on.
	 */
	let labelLayerName = $derived(
		t(
			form.text
				? 'grid.labelLayer.caption'
				: form.border
					? 'grid.labelLayer.border'
					: 'grid.labelLayer.code'
		)
	);
	/** Raster chosen on an engine that cannot convert it into laser lines. */
	let rasterImpossible = $derived(
		form.operation === 'graveren-raster' && preview?.engine?.grid === false
	);
	let assen = $derived([form.row_axis, form.column_axis] as As[]);
	let vasteAs = $derived(
		AS_ORDE.filter(
			(a) => !assen.includes(a) && (a !== 'interval' || intervalKan)
		)
	);

	/**
	 * Two axes cannot be the same quantity: pick for the rows what is already in
	 * the columns and that one moves to the vacated place. That is what a user
	 * means by "swap", and it saves an error message.
	 */
	function kiesAs(welke: 'row_axis' | 'column_axis', fresh: As) {
		const andere = welke === 'row_axis' ? 'column_axis' : 'row_axis';
		if (form[andere] === fresh) form[andere] = form[welke];
		form[welke] = fresh;
	}

	// If the operation jumps back to cutting while interval is on an axis, that axis
	// no longer exists. Without this the form stays invalid.
	$effect(() => {
		if (intervalKan) return;
		if (form.row_axis === 'interval') kiesAs('row_axis', 'speed');
		if (form.column_axis === 'interval') kiesAs('column_axis', 'power');
	});

	function body(metOpschrift = false) {
		const off: Record<string, unknown> = {
			material_id: form.material_id,
			thickness_mm: form.thickness_mm === '' ? null : Number(form.thickness_mm),
			operation: form.operation,
			row_axis: form.row_axis,
			column_axis: form.column_axis,
			cell_mm: Number(form.cell_mm),
			gap_mm: Number(form.gap_mm),
			passes: Number(form.passes),
			origin_x_mm: Number(form.origin_x_mm),
			origin_y_mm: Number(form.origin_y_mm),
			anchor: form.anchor,
			text: form.text,
			border: form.border,
			code_enabled: form.code,
			code_size_mm: form.code_size_mm === '' ? null : Number(form.code_size_mm),
			// Even with the code switched off: the name is printed in the caption of a board
			// that carries one, and this is what keeps it still. See `boardUid`.
			uid: boardUid,
			cutout_enabled: form.cutout,
			label_speed_mm_s: Number(form.label_speed_mm_s),
			label_power_percent: Number(form.label_power_percent)
		};
		for (const as of AS_ORDE) {
			if (assen.includes(as)) {
				off[`${as}_min`] = Number(form[`${as}_min`]);
				off[`${as}_max`] = Number(form[`${as}_max`]);
				off[`${as}_steps`] = Number(form[`${as}_steps`]);
			} else {
				off[VAST_VELD[as]] = Number(form[VAST_VELD[as]]);
			}
		}
		// The planning route does not know "caption"; only the board carries it.
		if (metOpschrift) off.caption = form.caption.trim();
		return off;
	}

	async function send(path: string, metOpschrift = false, quiet = false) {
		if (quiet) busyPreview = true;
		else busy = true;
		// A quiet preview round does not touch `error`: that block sits at the bottom
		// of the form and belongs to a failed action, not to a half-typed number.
		if (quiet) {
			previewError = null;
			previewErrorCode = null;
		} else error = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(path, {
				method: 'POST',
				headers,
				body: JSON.stringify(body(metOpschrift))
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				// Through `apiError`, so a refusal that carries a code is said in the reader's
				// language; one that carries numbers keeps its English sentence, because the
				// numbers do not travel in the header. The status line stays the last resort
				// for a failure that says nothing at all.
				const notice = apiError(
					response,
					typeof data?.detail === 'string'
						? data.detail
						: t('grid.error.refused', { status: response.status })
				);
				if (quiet) {
					previewError = notice;
					previewErrorCode = response.headers.get('X-OpenKerf-Error');
				} else error = notice;
				return null;
			}
			return data;
		} catch (e) {
			const notice = t('error.network', { message: e instanceof Error ? e.message : e });
			if (quiet) previewError = notice;
			else error = notice;
			return null;
		} finally {
			if (quiet) busyPreview = false;
			else busy = false;
		}
	}

	/**
	 * Proposing a range around what the library already knows.
	 *
	 * ARCHITECTUUR.md: the app proposes the range around the expected working point.
	 * Without presets a wide but reasonable starting point comes out.
	 */
	async function suggest() {
		const thickness = form.thickness_mm === '' ? null : Number(form.thickness_mm);
		const range = await library.suggest(form.material_id, form.operation, thickness);
		if (!range) return;
		form = {
			...form,
			speed_min: String(range.speed_min),
			speed_max: String(range.speed_max),
			power_min: String(range.power_min),
			power_max: String(range.power_max)
		};
		suggestedFrom = range.based_on;
	}

	let suggestedFrom = $state<number | null>(null);

	// Watching along live. A preview behind a button is not a preview: you only see
	// what you are setting after you have decided you want to see it.
	let timer: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		void [
			// The material and the thickness were missing from this list, and they decide
			// more than the caption: the cut-out's setting is looked up per material *and*
			// thickness, and a refusal is the answer when there is none. Measured before
			// adding them: switching from birch to glass — which has no cut setting at all —
			// left "The rim is cut at 12 mm/s and 65%" from the previous material on screen,
			// because nothing else on the form had changed and so no preview was asked for.
			form.material_id, form.thickness_mm,
			form.operation, form.row_axis, form.column_axis,
			form.speed_min, form.speed_max, form.speed_steps, form.speed_mm_s,
			form.power_min, form.power_max, form.power_steps, form.power_percent,
			form.interval_min, form.interval_max, form.interval_steps, form.interval_mm,
			form.cell_mm, form.gap_mm, form.passes, form.origin_x_mm, form.origin_y_mm,
			form.anchor, form.text, form.border,
			// The code and the cut-out belong in this list for the same reason as the two
			// switches above them: they change the size of the board, where the bed check
			// lands and what the burn costs. A field missing here is a preview that lies.
			form.code, form.code_size_mm, form.cutout,
			form.label_speed_mm_s, form.label_power_percent
		];
		if (timer) clearTimeout(timer);
		timer = setTimeout(async () => {
			const verse = await send('/api/library/testgrids/preview', false, true);
			// Only replace it when a valid board came out. Leaving the last valid image
			// up is calmer than dropping a hole — and it is more honest too: *that* is
			// still what you would burn if you stopped typing now.
			if (verse) {
				preview = verse;
				// The name the board keeps for as long as this form is about this board.
				if (typeof verse.plan?.uid === 'string') boardUid = verse.plan.uid;
			}
		}, 250);
		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	const CEL_SLEUTEL: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	/** The values that really get burned — after rounding, in grid order. */
	function langsAs(richting: 'row' | 'column'): number[] {
		if (!preview) return [];
		const as: As =
			richting === 'row'
				? (preview.plan.row_axis ?? 'speed')
				: (preview.plan.column_axis ?? 'power');
		const found = new Map<number, number>();
		for (const cell of preview.cells) {
			found.set(cell[richting], cell[CEL_SLEUTEL[as]] as number);
		}
		return [...found.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
	}
	let rowValues = $derived(preview ? langsAs('row') : []);
	let columnValues = $derived(preview ? langsAs('column') : []);

	/**
	 * How heavily a square burns: much power, low speed and a small interval give the
	 * deepest burn. That is not physics but a readable gradient — the preview has to
	 * teach you how to read the board later on, with the heaviest corner at the top
	 * right.
	 *
	 * Logarithmic and then stretched over the whole range: across a grid the ratio
	 * quickly spans a factor of ten, and linearly only the top row then stays visibly
	 * dark.
	 */
	function score(cell: Cell) {
		// An empty interval counts as 1: then the factor drops out instead of pulling
		// the whole scale to zero.
		const interval = cell.interval_mm ?? 1;
		return Math.log(
			cell.power_percent / Math.max(0.001, cell.speed_mm_s * Math.max(0.001, interval))
		);
	}

	let brandschaal = $derived.by(() => {
		if (!preview) return { layer: 0, high: 1 };
		const scores = preview.cells.map(score);
		const layer = Math.min(...scores);
		const high = Math.max(...scores);
		return { layer, high: high > layer ? high : layer + 1 };
	});

	function brand(cell: Cell) {
		const t = (score(cell) - brandschaal.layer) / (brandschaal.high - brandschaal.layer);
		// Not all the way to zero: even the lightest square is a cut in wood.
		return Math.max(0, Math.min(1, 0.12 + 0.88 * t));
	}

	/**
	 * Which corner goes deepest, worked out rather than assumed.
	 *
	 * As long as speed went down and power to the right, that was always the top
	 * right. With freely chosen axes it can be any corner — and a legend naming the
	 * wrong corner is worse than no legend.
	 */
	let deepestCorner = $derived.by(() => {
		if (!preview || preview.cells.length === 0) return null;
		const heaviest = preview.cells.reduce((a, b) => (score(b) > score(a) ? b : a));
		const atBottomEdge = heaviest.row === rowValues.length - 1;
		const atRightEdge = heaviest.column === columnValues.length - 1;
		// Word order differs per language: Dutch says "rechtsboven" as one word,
		// English "top right" the other way round — so the catalogue joins them.
		return t('grid.corner', {
			horizontal: t(atRightEdge ? 'grid.corner.right' : 'grid.corner.left'),
			vertical: t(atBottomEdge ? 'grid.corner.bottom' : 'grid.corner.top')
		});
	});

	/**
	 * A length with its unit, and without a trailing zero on a whole number.
	 *
	 * `mm()` writes one decimal always, which is right for a measured position and wrong
	 * for a setting somebody typed: "a strip of 20.0 mm" for a code of 18 reads as a
	 * measurement of something. Still through `number`, so it is a comma in Dutch.
	 */
	function lengte(value: number | null | undefined) {
		if (value === null || value === undefined || !Number.isFinite(value)) return '—';
		return `${number(value)} mm`;
	}

	/** "3 min 20 s" — a time you can weigh against your coffee. */
	function duur(s: number | null | undefined) {
		if (!s) return '—';
		if (s < 60) return t('grid.time.seconds', { n: Math.round(s) });
		const minuten = Math.floor(s / 60);
		if (minuten < 60)
			return t('grid.time.minutes', { minutes: minuten, seconds: Math.round(s % 60) });
		return t('grid.time.hours', { hours: Math.floor(minuten / 60), minutes: minuten % 60 });
	}
	let brandtijd = $derived(duur(preview?.plan.seconds));

	/** "0.05 mm", "60%", "12 mm/s" — the axis value as it ends up on the wood. */
	function show(as: As, value: number | null | undefined) {
		if (value === null || value === undefined) return '';
		const eenheid = AXIS_UNIT[as];
		return eenheid === '%' ? `${value}%` : `${value} ${eenheid}`;
	}

	// The preview is drawn in real pixels rather than in millimetres: an SVG with a
	// mm viewBox turns every 11px label into a giant of 11mm.
	const VOORBEELD_PX = 208;
	let scale = $derived(preview ? VOORBEELD_PX / Math.max(1, preview.plan.width_mm) : 1);
	let celPx = $derived(preview ? preview.plan.cell_mm * scale : 0);
	let gatPx = $derived(preview ? preview.plan.gap_mm * scale : 0);
	// With more than eight steps every label becomes unreadable; then only the
	// edges. An eleven-pixel label does not fit in a twenty-pixel square; then only
	// the two edge values, because those carry the range.
	let toonAlleLabels = $derived(
		rowValues.length <= 8 && columnValues.length <= 8 && celPx >= 30
	);

	function labelbaar(series: number[], i: number) {
		return toonAlleLabels || i === 0 || i === series.length - 1;
	}

	// "No material" is not the same as "the field is empty": an id that is not in the
	// library produces no preset later on just the same. So the warning belongs there
	// in that case too, and not one frame later.
	let noMaterial = $derived(
		form.material_id === null ||
			(library.materials.length > 0 &&
				!library.materials.some((m) => m.id === form.material_id))
	);
	let step = $derived(done ? 2 : 1);

	// ------------------------------------------ the code and the cut-out
	//
	// Both are values you set and read back, so they live on this form and not in a menu
	// (CLAUDE.md, the placement rule). What follows is everything the two need to be
	// honest about themselves: where their refusals belong, what they cost, and how big
	// they draw in the preview.

	/**
	 * A refusal shown where the switch that caused it is.
	 *
	 * These four all arrive from the *preview*, which runs 250 ms after the switch goes
	 * on — so they are on screen while the numbers that caused them are still in the
	 * fields, and long before a plank is in the machine. Measured on the live library:
	 * a cut-out on glass answers `library.grid.cutoutNeedsPreset` ("There is no cut
	 * setting for this material at 3 mm; burn a cutting board first, or add the setting
	 * by hand."), on no material `library.grid.cutoutNeedsMaterial`, an 11 mm code
	 * `library.grid.codeTooSmall`, and an 18 mm code beside 11 mm of board
	 * `library.grid.codeNoRoom`.
	 */
	const CODE_REFUSALS = ['library.grid.codeTooSmall', 'library.grid.codeNoRoom'];
	const CUTOUT_REFUSALS = [
		'library.grid.cutoutNeedsMaterial',
		'library.grid.cutoutNeedsPreset',
		'library.grid.cutoutNoSetting'
	];
	let codeRefusal = $derived(
		previewErrorCode && CODE_REFUSALS.includes(previewErrorCode) ? previewError : null
	);
	let cutoutRefusal = $derived(
		previewErrorCode && CUTOUT_REFUSALS.includes(previewErrorCode) ? previewError : null
	);
	/** What is left for the notice above the picture: everything that is nobody's switch. */
	let looseRefusal = $derived(codeRefusal || cutoutRefusal ? null : previewError);

	/** What the engine says about this board that is nobody's refusal — a code only just
	 *  big enough to read, for instance. Its own sentence, because it names the numbers. */
	let boardWarnings = $derived(preview?.plan.warnings ?? []);

	/**
	 * The strip of board the code stands in: its own size plus the gap above it.
	 *
	 * Read out of the plan rather than copied from `CODE_GAP_MM`, so a change on that side
	 * cannot leave this sentence quietly wrong.
	 */
	let codeStripMm = $derived.by(() => {
		const plan = preview?.plan;
		if (!plan?.code_enabled) return null;
		const size = Number(plan.code_size_mm);
		const top = Number(plan.code_y_mm);
		if (!Number.isFinite(size) || !Number.isFinite(top)) return null;
		return size + (top - plan.origin_y_mm - plan.height_mm);
	});
	/** How far outside everything else the cut runs, from the plan's own two rectangles. */
	let cutMarginMm = $derived.by(() => {
		const plan = preview?.plan;
		if (!plan?.cutout_enabled) return null;
		return Math.round((plan.outer_x_mm - plan.cut_x_mm) * 1000) / 1000;
	});
	/** The cut setting the server looked up, so it is shown rather than asked for. */
	let cutSetting = $derived.by(() => {
		const plan = preview?.plan;
		if (!plan?.cutout_enabled || !plan.cut_speed_mm_s) return null;
		return {
			speed: Number(plan.cut_speed_mm_s),
			power: Number(plan.cut_power_percent),
			passes: Number(plan.cut_passes ?? 1)
		};
	});

	/**
	 * Where the previous board came to lie.
	 *
	 * Needed because by default a second grid lands in exactly the same place: Start X
	 * and Start Y are still what they were. Measured: two boards, both at 20, 20 mm,
	 * exactly on top of each other — invisible on the canvas and a double burn in the
	 * machine.
	 */
	let vorigBord = $state<{
		id: number;
		x: number;
		y: number;
		width: number;
		height: number;
	} | null>(null);

	async function generate() {
		done = null;
		const grid = await send('/api/library/testgrids', true);
		if (grid) {
			done = { id: grid.id, cellen: grid.cells?.length ?? 0 };
			const plan = preview?.plan;
			vorigBord = plan
				? {
						id: grid.id,
						x: plan.outer_x_mm ?? plan.origin_x_mm,
						y: plan.outer_y_mm ?? plan.origin_y_mm,
						width: plan.outer_width_mm ?? plan.width_mm,
						height: plan.outer_height_mm ?? plan.height_mm
					}
				: null;
			onGenerated?.(grid.id);
		}
	}

	/**
	 * Back to step 1 for a next board.
	 *
	 * This was one button with `generate()`: "Draw another grid" *drew* straight
	 * away, without giving you the chance to change anything — and left the previous
	 * board's message up ("The job is in the queue") under the new one's number. Now
	 * the button does what it says: it puts you back at the settings, with the place
	 * of the previous board on screen so you lay the new one beside it instead of on
	 * top of it.
	 */
	function again() {
		done = null;
		// A next board is a next plank, so it gets a name of its own; holding on to this one
		// would burn the same code twice and send two photographs to one row.
		boardUid = null;
		naarMachine = null;
		machineError = null;
		machineLet = null;
		error = null;
	}

	/** Would the new board land on top of the previous one? */
	let botsing = $derived.by(() => {
		if (!vorigBord || done || !preview) return false;
		const plan = preview.plan;
		const x = plan.outer_x_mm ?? plan.origin_x_mm;
		const y = plan.outer_y_mm ?? plan.origin_y_mm;
		const b = plan.outer_width_mm ?? plan.width_mm;
		const h = plan.outer_height_mm ?? plan.height_mm;
		return (
			x < vorigBord.x + vorigBord.width &&
			vorigBord.x < x + b &&
			y < vorigBord.y + vorigBord.height &&
			vorigBord.y < y + h
		);
	});

	// ------------------------------------------------- vorige keer (gat T3)
	//
	// Anybody testing 3 mm birch every week sets the same thing up every week. The
	// previous grid for this material *is* that setting; no separate preferences table
	// is needed for it.

	let overgenomen = $state<{ dateOf: string; grid: number } | null>(null);
	let loadedFor = $state<number | null | undefined>(undefined);

	const TO_CARRY_OVER = [
		'operation', 'row_axis', 'column_axis',
		'speed_min', 'speed_max', 'speed_steps',
		'power_min', 'power_max', 'power_steps',
		'interval_min', 'interval_max', 'interval_steps',
		'cell_mm', 'gap_mm', 'passes',
		'label_speed_mm_s', 'label_power_percent'
	] as const;

	/**
	 * Putting one saved setting into the form.
	 *
	 * Works for a previous grid (T3) and for a named recipe (T7): the server supplies
	 * them in the same shape, and that was the reason to build T7 *on* T3 rather than
	 * beside it.
	 */
	function neemOver(vorige: Record<string, unknown>) {
		for (const key of TO_CARRY_OVER) {
			const value = vorige[key];
			if (value === null || value === undefined) continue;
			(form as Record<string, unknown>)[key] =
				typeof value === 'number' ? String(value) : value;
		}
		// A fixed quantity sits in the previous row as min == max.
		for (const as of AS_ORDE) {
			if (vorige[`${as}_steps`] === 1 && vorige[`${as}_min`] != null) {
				form[VAST_VELD[as]] = String(vorige[`${as}_min`]);
			}
		}
		// Where the board lay and what else was on it (T9, T10). The point you tapped
		// comes back, not the corner computed from it.
		if (vorige.anchor === 'center' || vorige.anchor === 'corner') form.anchor = vorige.anchor;
		if (typeof vorige.text_enabled === 'boolean') form.text = vorige.text_enabled;
		if (typeof vorige.border_enabled === 'boolean') form.border = vorige.border_enabled;
		// Whether the board names itself and whether the tile comes loose are choices about
		// how you work rather than about this material, which is why they are in
		// `Library.GRID_DEFAULTS` (library.py:1629) with the two above them. The name itself
		// is not: adopting the previous board's name would burn it on two planks.
		if (typeof vorige.code_enabled === 'boolean') form.code = vorige.code_enabled;
		if (typeof vorige.cutout_enabled === 'boolean') form.cutout = vorige.cutout_enabled;
		if (vorige.code_size_mm != null) form.code_size_mm = String(vorige.code_size_mm);
		const x = vorige.anchor_x_mm ?? vorige.origin_x_mm;
		const y = vorige.anchor_y_mm ?? vorige.origin_y_mm;
		if (x != null) form.origin_x_mm = String(x);
		if (y != null) form.origin_y_mm = String(y);
		if (vorige.thickness_mm != null) form.thickness_mm = String(vorige.thickness_mm);
	}

	$effect(() => {
		const id = form.material_id;
		if (id === loadedFor) return;
		loadedFor = id;
		overgenomen = null;
		if (id === null) return;
		(async () => {
			const response = await fetch(`/api/library/testgrids/defaults?material_id=${id}`);
			if (!response.ok) return;
			const vorige = await response.json();
			// Only adopt it as long as you have generated nothing yet: otherwise you
			// overwrite the form you were just working in.
			if (!vorige || done || form.material_id !== id) return;
			neemOver(vorige);
			overgenomen = { dateOf: vorige.from_date, grid: vorige.from_grid };
		})();
	});

	// ------------------------------------------ benoemde recepten (gat T7)
	//
	// T3 remembers one setting per material: the previous grid. That covers the weekly
	// trial, not two recipes you alternate between — "cut birch" beside "engrave
	// birch". LightBurn has a Presets list for that with saving and deleting; this is
	// the same list, filled with the same keys as the previous grid, so there is one
	// fill-in routine.

	type Recipe = {
		id: number;
		name: string;
		material_id: number | null;
		material_name: string | null;
		settings: Record<string, unknown>;
	};

	let recepten = $state<Recipe[]>([]);
	let pickedRecipe = $state<number | null>(null);
	let recipeName = $state('');
	let recipeError = $state<string | null>(null);
	let recipeBusy = $state(false);
	/** The save field is closed until you open it: it is not the main route. */
	let saving = $state(false);

	async function fetchRecipes() {
		const ask =
			form.material_id === null
				? '/api/library/testgrids/recipes'
				: `/api/library/testgrids/recipes?material_id=${form.material_id}`;
		const response = await fetch(ask);
		if (!response.ok) return;
		recepten = await response.json();
		if (pickedRecipe !== null && !recepten.some((r) => r.id === pickedRecipe)) {
			pickedRecipe = null;
		}
	}

	$effect(() => {
		void form.material_id;
		fetchRecipes();
	});

	function pickRecipe(id: number | null) {
		pickedRecipe = id;
		const recipe = recepten.find((r) => r.id === id);
		if (!recipe) return;
		// A recipe overwrites the form; that is what you chose it for. The provenance
		// line from T3 no longer holds after that, so it goes.
		overgenomen = null;
		neemOver(recipe.settings);
		recipeName = recipe.name;
	}

	async function saveRecipe() {
		const name = recipeName.trim();
		if (!name) return;
		recipeBusy = true;
		recipeError = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			// Exactly what gets burned later on, minus the caption: that belongs to one
			// board and not to the recipe.
			const settings = { ...body(false) };
			delete (settings as Record<string, unknown>).material_id;
			const response = await fetch('/api/library/testgrids/recipes', {
				method: 'POST',
				headers,
				body: JSON.stringify({
					name: name,
					material_id: form.material_id,
					settings: settings
				})
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				recipeError =
					typeof data?.detail === 'string'
						? data.detail
						: t('grid.recipe.saveFailed', { status: response.status });
				return;
			}
			await fetchRecipes();
			pickedRecipe = data?.id ?? null;
			saving = false;
		} finally {
			recipeBusy = false;
		}
	}

	async function wipeRecipe() {
		if (pickedRecipe === null) return;
		recipeBusy = true;
		recipeError = null;
		try {
			const headers: Record<string, string> = {};
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(`/api/library/testgrids/recipes/${pickedRecipe}`, {
				method: 'DELETE',
				headers
			});
			if (!response.ok) {
				recipeError = t('grid.recipe.deleteFailed', { status: response.status });
				return;
			}
			pickedRecipe = null;
			recipeName = '';
			await fetchRecipes();
		} finally {
			recipeBusy = false;
		}
	}

	/** "11 Aug" — the date of the grid the setting comes from. */
	function kortedatum(ruw: string) {
		const d = new Date(String(ruw).replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return ruw;
		return new Intl.DateTimeFormat(i18n.locale, { day: 'numeric', month: 'short' }).format(d);
	}

	// ------------------------------------------------ to the machine (gap T1)
	//
	// The wizard used to end on the canvas: the grid was there, and nothing pointed
	// you at Show frame or Start job. Those two are in the success message itself
	// now. They call the same APIs as the control panel.

	let naarMachine = $state<string | null>(null);
	let machineError = $state<string | null>(null);
	let machineLet = $state<string | null>(null);

	/**
	 * The hard check the control panel does before starting.
	 *
	 * That panel opens a preflight and only starts after a confirmation; this button
	 * starts directly, and then the most important check must not fall away. Outside
	 * the bed is a block — the head cannot get there, so the machine skips the
	 * movement or runs into its end stop. Outside the sheet is a warning: the head
	 * can get there, there is simply no material. Exactly the distinction
	 * `bounds_report` makes.
	 */
	async function tegenhouder(): Promise<string | null> {
		machineLet = null;
		try {
			const response = await fetch('/api/job/estimate');
			if (!response.ok) return null; // No verdict is not a block.
			const bounds = (await response.json())?.bounds;
			if (!bounds) return null;
			if (bounds.outside_bed > 0) {
				return t('grid.block.outsideBed', { n: bounds.outside_bed });
			}
			if (bounds.outside_sheet > 0) {
				machineLet = t('grid.watch.outsideSheet', { n: bounds.outside_sheet });
			}
			return null;
		} catch {
			return null;
		}
	}

	async function machineActie(pad: string, busy: string, ready: string) {
		naarMachine = busy;
		machineError = null;
		try {
			// Only before burning. Running a frame is precisely the way to see that
			// something falls off the bed; blocking that would block the very check you
			// wanted to make.
			if (pad.includes('/job/start')) {
				const bezwaar = await tegenhouder();
				if (bezwaar) {
					machineError = bezwaar;
					return;
				}
			}
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(pad, { method: 'POST', headers, body: '{}' });
			if (!response.ok) {
				const data = await response.json().catch(() => null);
				const notice = data?.detail;
				machineError =
					typeof notice === 'string'
						? notice
						: Array.isArray(notice?.output)
							? notice.output.join(' ')
							: `De machine weigerde dit (${response.status}).`;
				return;
			}
			naarMachine = ready;
		} catch (e) {
			machineError = t('error.network', { message: e instanceof Error ? e.message : String(e) });
		} finally {
			if (naarMachine === busy) naarMachine = null;
		}
	}

	// ---------------------------------------------------- material erbij (E4)

	let newMaterial = $state('');
	let materialError = $state<string | null>(null);

	async function makeMaterial() {
		const name = newMaterial.trim();
		if (!name) return;
		materialError = null;
		const made = await library.addMaterial(name);
		if (!made) {
			materialError = library.error ?? t('error.materialFailed');
			return;
		}
		newMaterial = '';
		form.material_id = made.id;
	}
</script>

<div class="wizard">
	<!-- The wizard is the didactic core of the app: it says where you are and what
	     is still to come, even though step 3 only happens beside the machine. -->
	<ol class="steps" aria-label={t('grid.steps')}>
		<li class:now={step === 1}><span class="nr">1</span>{t('grid.step.setUp')}</li>
		<li class:now={step === 2}><span class="nr">2</span>{t('grid.step.burn')}</li>
		<li><span class="nr">3</span>{t('grid.step.photograph')}</li>
		<li><span class="nr">4</span>{t('grid.step.bestCell')}</li>
	</ol>

	{#if !canEdit}
		<p class="muted">{t('grid.needsToken')}</p>
	{:else}
		<p class="lead">
			{t('grid.lead', {
				columns: t('grid.lead.right', { axis: axisLabel(form.column_axis).toLowerCase() }),
				rows: t('grid.lead.down', { axis: axisLabel(form.row_axis).toLowerCase() })
			})}
		</p>

		<!-- Gap T7: named settings. Whoever tests 3 mm birch weekly is served by "last
		     time" (T3), but two recipes for the same material — cut beside engrave —
		     cannot sit side by side in that. At the top, as in LightBurn: you pick your
		     recipe before you start tinkering, not after. -->
		<div class="recepten">
			<label class="field">
				<span class="name">{t('grid.recipe')}</span>
				<select
					value={pickedRecipe}
					disabled={recepten.length === 0}
					title={recepten.length === 0 ? t('grid.recipe.none') : undefined}
					onchange={(e) =>
						pickRecipe(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
				>
					<option value={null}
						>{recepten.length === 0 ? t('grid.recipe.none') : t('grid.recipe.pick')}</option
					>
					{#each recepten as recipe (recipe.id)}
						<option value={recipe.id}
							>{recipe.name}{recipe.material_name
								? ''
								: ` · ${t('grid.recipe.allMaterials')}`}</option
						>
					{/each}
				</select>
			</label>
			<div class="receptknoppen">
				<button class="btn" onclick={() => (saving = !saving)} aria-expanded={saving}>
					{saving ? t('grid.recipe.dontSave') : t('grid.recipe.save')}
				</button>
				{#if pickedRecipe !== null}
					<button class="btn quiet" disabled={recipeBusy} title={recipeBusy ? t('reason.busy') : undefined} onclick={wipeRecipe}
						>{t('common.remove')}</button
					>
				{/if}
			</div>
			{#if saving}
				<div class="erbij">
					<input
						type="text"
						bind:value={recipeName}
						maxlength="60"
						placeholder={t('grid.recipe.namePlaceholder')}
						aria-label={t('grid.recipe.nameAria')}
						onkeydown={(e) => {
							if (e.key === 'Enter') {
								e.preventDefault();
								saveRecipe();
							}
						}}
					/>
					<button
						class="btn"
						disabled={recipeBusy || recipeName.trim() === ''}
						title={recipeBusy ? t('reason.busy') : t('reason.needsName')}
						onclick={saveRecipe}>{t('common.save')}</button
					>
				</div>
				<p class="hint">
					{t('grid.recipe.hint')}
					{form.material_id === null
						? t('grid.recipe.hint.noMaterial')
						: t('grid.recipe.hint.material')}
				</p>
			{/if}
			{#if recipeError}<p class="failure" role="alert">{recipeError}</p>{/if}
		</div>

		<div class="werkbank">
			<div class="grid">
				<div class="paar">
				<label class="field">
					<span class="name">{t('library.material')}</span>
					<select bind:value={form.material_id}>
						<option value={null}>{t('grid.none')}</option>
						{#each library.materials as material (material.id)}
							<option value={material.id}>{material.name}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span class="name">{t('library.operation')}</span>
					<select bind:value={form.operation}>
						{#each operations() as op (op.value)}
							<option value={op.value}>{op.label}</option>
						{/each}
					</select>
				</label>
				</div>

				{#if noMaterial}
					<!-- Before the wood goes, not after: without a material no preset can come
					     out of this board later, and that is the whole reason you burn it. The
					     warning does not only point at the gap but closes it — otherwise there
					     is an objection with no way out beside a button that simply goes
					     ahead. -->
					<div class="waarschuwing" role="status">
						<p>
							<strong>{t('grid.noMaterial.title')}</strong>
							{t('grid.noMaterial.body')}
						</p>
						<div class="erbij">
							<input
								type="text"
								bind:value={newMaterial}
								maxlength="60"
								placeholder={t('grid.newMaterial.placeholder')}
								aria-label={t('grid.newMaterial.aria')}
								onkeydown={(e) => {
									if (e.key === 'Enter') {
										e.preventDefault();
										makeMaterial();
									}
								}}
							/>
							<button
								class="btn"
								disabled={library.busy || newMaterial.trim() === ''} title={library.busy ? t('reason.busy') : t('reason.needsName')}
								onclick={makeMaterial}>{t('grid.newMaterial.create')}</button
							>
						</div>
						{#if materialError}<p class="failure">{materialError}</p>{/if}
					</div>
				{/if}

				{#if rasterImpossible}
					<!-- The engine turns a grid layer into a bitmap while planning, and that
					     converter lives in the wxPython GUI. When the server runs headless — as
					     here — the layer throws its own shapes away and the board comes out of
					     the machine blank. That is a gap in the engine, not a choice of ours;
					     the least we can do is say it before the wood goes. -->
					<p class="waarschuwing ernstig" role="alert">
						<strong>{t('job.noRaster.title')}</strong>
						{t('grid.noRaster.body')}
					</p>
				{/if}

				{#if overgenomen}
					<p class="overgenomen" role="status">
						{t('grid.carriedOver', {
							date: kortedatum(overgenomen.dateOf),
							grid: overgenomen.grid
						})}
					</p>
				{/if}

				<div class="paar">
					<NumberField
						label={t('library.thickness')}
						unit="mm"
						step={0.5}
						min={0}
						bind:value={form.thickness_mm}
					/>
					<NumberField label={t('grid.cell')} unit="mm" step={1} min={1} bind:value={form.cell_mm} />
				</div>
				<!-- For the whole board, not per square: passes as an axis would yield a
				     board nobody reads back, and the number goes on the caption so you can
				     still place the board in two weeks.

				     In a `.paar` with one child: that keeps the field the same width as the
				     fields above. Over the full width a number field is 500px for one
				     digit, and then the column no longer lines up. -->
				<div class="paar">
					<NumberField
						label={t('library.passes')}
						unit={t('grid.passes.unit')}
						step={1}
						min={1}
						bind:value={form.passes}
					/>
				</div>

				<!-- Decision B12: you pick which two quantities you sweep. The third stays
				     fixed and ends up on the caption of the board. -->
				<div class="paar">
				<label class="field">
					<span class="name">{t('grid.rowsDown')}</span>
					<select
						value={form.row_axis}
						onchange={(e) => kiesAs('row_axis', e.currentTarget.value as As)}
					>
						{#each AS_ORDE as value (value)}
							{#if value !== 'interval' || intervalKan}
								<option value={value}>{axisLabel(value)}</option>
							{/if}
						{/each}
					</select>
				</label>
				<label class="field">
					<span class="name">{t('grid.columnsRight')}</span>
					<select
						value={form.column_axis}
						onchange={(e) => kiesAs('column_axis', e.currentTarget.value as As)}
					>
						{#each AS_ORDE as value (value)}
							{#if value !== 'interval' || intervalKan}
								<option value={value}>{axisLabel(value)}</option>
							{/if}
						{/each}
					</select>
				</label>
				</div>

				<!-- The fixed quantity sits with the axes and not at the bottom: it belongs
				     to the question "what varies", and on an 80vh window it otherwise fell
				     behind the button bar. -->
				{#each vasteAs as as (as)}
					<NumberField
						label={t('grid.fixedAxis', { axis: axisLabel(as) })}
						unit={AXIS_UNIT[as]}
						step={INVOER[as].step}
						min={0}
						max={INVOER[as].max ?? null}
						bind:value={form[VAST_VELD[as]]}
					/>
				{/each}

				<!-- From, to and the number of steps are one statement about one axis
				     together. They used to be spread over three places in the grid; now
				     every axis is in a block of its own, with from and to side by side. -->
				{#each assen as as (as)}
					<fieldset class="asblok">
						<!-- The unit once, in the block's heading. It used to be in both field
						     labels ("from (mm/s)", "to (mm/s)") and then you read it twice to
						     understand one range. -->
						<legend class="name">{t('grid.axisRange', { axis: axisLabel(as), unit: AXIS_UNIT[as] })}</legend>
						<div class="paar">
							<NumberField
								label={t('grid.from')}
								step={INVOER[as].step}
								min={0}
								max={INVOER[as].max ?? null}
								bind:value={form[`${as}_min`]}
							/>
							<NumberField
								label={t('grid.to')}
								step={INVOER[as].step}
								min={0}
								max={INVOER[as].max ?? null}
								bind:value={form[`${as}_max`]}
							/>
						</div>
						<div class="paar">
							<NumberField
								label={t('grid.stepsLabel')}
								unit={as === assen[0] ? t('grid.stepsUnit.rows') : t('grid.stepsUnit.columns')}
								step={1}
								min={2}
								bind:value={form[`${as}_steps`]}
							/>
						</div>
					</fieldset>
				{/each}

				<div class="paar">
					<NumberField label={t('grid.gap')} unit="mm" step={1} min={0} bind:value={form.gap_mm} />
				</div>

				<!-- Gap T9: LightBurn asks for X Center/Y Center. On an offcut you know
				     where the middle of your piece of wood is, not where the corner of a
				     grid you have not seen yet should go. The centre applies to the whole
				     board, captions included — otherwise it sits askew the moment the row
				     labels stick out on the left. -->
				<label class="field">
					<span class="name">{t('grid.measureFrom')}</span>
					<select bind:value={form.anchor}>
						<option value="corner">{t('grid.anchor.corner')}</option>
						<option value="center">{t('grid.anchor.center')}</option>
					</select>
				</label>
				<div class="paar">
					<NumberField
						label={form.anchor === 'center' ? t('grid.centerX') : t('grid.startX')}
						unit="mm"
						step={5}
						min={0}
						bind:value={form.origin_x_mm}
					/>
					<NumberField
						label={form.anchor === 'center' ? t('grid.centerY') : t('grid.startY')}
						unit="mm"
						step={5}
						min={0}
						bind:value={form.origin_y_mm}
					/>
				</div>

				<!-- Gap T10: LightBurn has Enable Text and Enable Border. For a quick test
				     on an offcut the caption is waste; for a board that goes in the cupboard
				     it is half the evidence. On by default, so whoever does nothing keeps
				     what was there. -->
				<fieldset class="schakelaars">
					<legend class="name">{t('grid.extras')}</legend>
					<label class="vink">
						<input type="checkbox" bind:checked={form.text} />
						<span>{t('grid.extras.text')}</span>
					</label>
					<label class="vink">
						<input type="checkbox" bind:checked={form.border} />
						<span>{t('grid.extras.border')}</span>
					</label>
					<p class="hint">
						{#if !form.text}
							{t('grid.extras.noText')}
						{:else if form.border}
							{t('grid.extras.bothOn')}
						{:else}
							{t('grid.extras.borderOnly')}
						{/if}
					</p>

					<!-- The board's own name on the plank, and the tile cut loose from the
					     sheet. Both were built end to end and then had no control at all: the
					     only way to ask for either was hand-written HTTP, and `docs/test-grid.md`
					     said so out loud. They are values you set and read back, so this form is
					     where they belong.

					     Why the code is worth burn time is not what it *is* but what it is
					     for: eleven of the author's thirty-two boards are physically
					     indistinguishable from another one, so a photograph taken after the wood
					     is off the machine is filed by guesswork. -->
					<label class="vink">
						<input type="checkbox" bind:checked={form.code} />
						<span>{t('grid.extras.code')}</span>
					</label>
					{#if form.code}
						<div class="uitleg">
							<p class="hint">{t('grid.code.why')}</p>
							{#if preview?.plan.code_human}
								<!-- The name is in the sentence and not glued to the end of it: a
								     language that puts it elsewhere has nowhere to put it otherwise. -->
								<p class="hint">{t('grid.code.name', { name: preview.plan.code_human })}</p>
							{/if}
							<!-- Not clamped to the engine's own 12 and 14 mm: those two numbers
							     live in `boardcode.MIN_SIZE_MM` and `SMALL_SIZE_MM`, and a copy of
							     them here would be a second place to forget. The refusal and the
							     warning below say them, in the sentence that measured them. -->
							<NumberField
								label={t('grid.code.size')}
								unit="mm"
								step={1}
								min={1}
								bind:value={form.code_size_mm}
							/>
							{#if codeRefusal}
								<p class="krap" role="status">{codeRefusal}</p>
							{:else}
								{#if codeStripMm !== null}
									<p class="hint">
										{t('grid.code.cost', {
											strip: lengte(codeStripMm),
											time: duur(preview?.plan.code_seconds),
											module: mm(preview?.plan.code_module_mm, 2)
										})}
									</p>
								{/if}
								{#each boardWarnings as warning (warning.code)}
									<!-- The engine's own sentence: it carries the numbers this side
									     cannot know, and it reaches curl and the logs in the same
									     words. -->
									<p class="krap" role="status">{warning.text}</p>
								{/each}
							{/if}
						</div>
					{/if}

					<label class="vink">
						<input type="checkbox" bind:checked={form.cutout} />
						<span>{t('grid.extras.cutout')}</span>
					</label>
					{#if form.cutout}
						<div class="uitleg">
							{#if cutoutRefusal}
								<!-- The refusal arrives from the preview, so it is on screen a
								     quarter of a second after the switch goes on — with the
								     numbers that caused it still in the fields, and before
								     anybody has laid a plank in the machine. -->
								<p class="krap" role="status">{cutoutRefusal}</p>
							{:else}
								{#if cutSetting}
									<!-- Shown and not asked: the cut setting is looked up from the
									     library by the server (`cutout_setting`, testgrid.py:1064),
									     and it refuses rather than guesses, because the speed that
									     cuts this material is the very thing a test board exists to
									     find out. -->
									<p class="hint">
										{t('grid.cutout.setting', {
											speed: number(cutSetting.speed),
											power: number(cutSetting.power),
											passes: number(cutSetting.passes)
										})}
									</p>
								{/if}
								{#if cutMarginMm !== null}
									<p class="hint">
										{t('grid.cutout.how', {
											margin: lengte(cutMarginMm),
											n: preview?.plan.cut_tabs ?? 0,
											tab: lengte(preview?.plan.cut_tab_mm)
										})}
									</p>
								{/if}
								{#if preview?.plan.cut_seconds}
									<p class="hint">
										{t('grid.cutout.cost', { time: duur(preview.plan.cut_seconds) })}
									</p>
								{/if}
							{/if}
						</div>
					{/if}

					{#if form.code || form.cutout}
						<!-- Said once, quietly, and not per switch: nobody has burned a board
						     with either of these, on any material. Every millimetre and every
						     second above is arithmetic on pixels and on the engine's own cut
						     plan. -->
						<p class="hint">{t('grid.extras.untried')}</p>
					{/if}
				</fieldset>

				{#if form.text || form.border || form.code}
					<!-- The label layer was hard-coded at 80 mm/s @30%. That works on birch and
					     not on acrylic, and then the caption burns straight through your
					     board. -->
					<NumberField
						label={t('grid.label.speed', { layer: labelLayerName })}
						unit="mm/s"
						step={5}
						min={1}
						bind:value={form.label_speed_mm_s}
					/>
					<NumberField
						label={t('grid.label.power', { layer: labelLayerName })}
						unit="%"
						step={5}
						min={1}
						max={100}
						bind:value={form.label_power_percent}
					/>
				{/if}

				<label class="field wide">
					<span class="name">{t('grid.caption')}</span>
					<input
						type="text"
						bind:value={form.caption}
						maxlength="48"
						placeholder={t('grid.caption.placeholder')}
					/>
					<span class="hint">{t('grid.caption.hint')}</span>
				</label>
			</div>

			{#if preview}
				<aside class="preview" aria-label={t('grid.preview')}>
					{#if looseRefusal}
						<!-- While typing, an intermediate state is nearly always briefly
						     invalid: you adjust "from" and it is then higher than "to" until you
						     adjust that too. The preview stays, with the reason above it —
						     dropping a hole teaches you nothing and makes half the wizard
						     jump. -->
						<p class="unfinished" role="status">
							{looseRefusal}<br />
							<span class="quiet">{t('grid.preview.lastValid')}</span>
						</p>
					{:else if previewError}
						<!-- The reason itself is up beside the switch that caused it, which is
						     where it can be acted on. What still belongs here is that the picture
						     below is one board behind. -->
						<p class="unfinished" role="status">{t('grid.preview.lastValid')}</p>
					{:else if botsing}
						<!-- The previous board is still there, and Start X/Y is still in the same
						     place. Two boards over each other you do not see on the canvas and do
						     see in the machine. -->
						<p class="unfinished" role="status">
							{t('grid.preview.overlap', {
								id: vorigBord?.id,
								anchor: t(form.anchor === 'center' ? 'grid.anchor.centreWord' : 'grid.anchor.startWord')
							})}
						</p>
					{/if}
					<div class="figures">
						<span class="mono">{t('grid.cells', { n: preview.cells.length })}</span>
						<!-- Only when there is more than one: with one pass this is the ordinary
						     course of things and says nothing. -->
						{#if (preview.plan.passes ?? 1) > 1}
							<span class="mono">{t('grid.passesPerCell', { n: preview.plan.passes })}</span>
						{/if}
						<!-- The size of the whole board, not of the squares alone: the caption and
						     the border are burned just as much, and it was precisely those that
						     stuck out on the left and top (T11). LightBurn reports the same as
						     Output Size. -->
						<!-- Through `number`, like every other measure in this panel. Beside the
						     line about the tile it wrote 132.9 where that one wrote 120,2 — two
						     notations for the same quantity, in one panel, for a Dutch reader. -->
						<span class="mono"
							>{number(preview.plan.outer_width_mm ?? preview.plan.width_mm)} × {number(
								preview.plan.outer_height_mm ?? preview.plan.height_mm
							)} mm</span
						>
					</div>
					<!-- Either dimension, not only the width. A code grows the board downwards and
					     not sideways, so a board whose only extra is a code was 20 mm taller than
					     its squares with nothing on screen saying where those millimetres went. -->
					{#if (preview.plan.outer_width_mm ?? 0) > preview.plan.width_mm || (preview.plan.outer_height_mm ?? 0) > preview.plan.height_mm}
						<p class="kosten">
							{t('grid.ofWhich', {
								size: `${number(preview.plan.width_mm)} × ${number(preview.plan.height_mm)} mm`,
								extras:
									// One whole phrase per combination rather than a list glued together
									// in the markup: "caption, border and code" is not the same three
									// words in the same order in every language. Seven combinations,
									// and the eighth cannot happen — with none of the three on there
									// is no extra board to explain.
									form.text && form.border && form.code
										? t('grid.extras.allThree')
										: form.text && form.border
											? t('grid.extras.both')
											: form.text && form.code
												? t('grid.extras.captionAndCode')
												: form.border && form.code
													? t('grid.extras.borderAndCode')
													: form.text
														? t('grid.extras.captionOnly')
														: form.border
															? t('grid.extras.borderOnly2')
															: t('grid.extras.codeOnly')
							})}
						</p>
					{/if}
					{#if cutMarginMm !== null}
						<!-- With a cut-out the piece you carry away is not the board: it is the
						     board plus the margin the cut runs in. That is the measure that has to
						     fit the offcut in your hand. -->
						<p class="kosten">
							{t('grid.cutout.tile', {
								size: `${number(preview.plan.cut_width_mm)} × ${number(
									preview.plan.cut_height_mm
								)} mm`
							})}
						</p>
					{/if}
					<!-- What it is going to cost, before you press generate. With interval as
					     an axis the burn time can quietly go up tenfold: a row at 0.05 mm lays
					     six times as many lines as one at 0.3 mm, and that is in no other
					     number on this form. -->
					<p class="kosten">{t('grid.burnTime', { time: brandtijd })}</p>

					<!-- The board as it comes out: darker = more burning, and the values are
					     alongside where they end up on the wood. -->
					<!-- The switches from T10 have to be visible here and not only in a
					     number: switch the caption off and the axis values disappear from the
					     preview too, because they do not go on the wood. The border is a line
					     around the whole thing, exactly where it burns. -->
					<!-- The cut runs outside everything else the board draws, so it is a ring
					     around the board and not part of its grid. Dashed, because it is not one
					     continuous cut: four bridges hold the tile in the sheet. -->
					<div
						class="tile"
						class:cutting={cutMarginMm !== null}
						style="--rim: {(cutMarginMm ?? 0) * scale}px;"
					>
					<div
						class="board"
						class:kaal={!form.text}
						class:frame={form.border}
						style="--cel: {celPx}px; --gat: {gatPx}px;"
					>
						{#if form.text}
						<div class="corner"></div>
						<div class="koplabels">
							{#each columnValues as v, i (i)}
								<span class="as mono"
									>{labelbaar(columnValues, i)
										? form.column_axis === 'power'
											? `${v}%`
											: v
										: ''}</span
								>
							{/each}
						</div>
						<div class="zijlabels">
							{#each rowValues as v, i (i)}
								<span class="as mono"
									>{labelbaar(rowValues, i)
										? form.row_axis === 'power'
											? `${v}%`
											: v
										: ''}</span
								>
							{/each}
						</div>
						{/if}
						<div
							class="cells"
							style="grid-template-columns: repeat({columnValues.length}, var(--cel));"
						>
							{#each preview.cells as cell (`${cell.row}-${cell.column}`)}
								<span
									class="cell"
									style="--burn: {brand(cell)}"
									title={t('grid.cellTitle', {
										row: show(form.row_axis, cell[CEL_SLEUTEL[form.row_axis]]),
										column: show(form.column_axis, cell[CEL_SLEUTEL[form.column_axis]])
									})}
								></span>
							{/each}
						</div>
						{#if form.code && codeStripMm !== null}
							<!-- Bottom right, in a strip the board grows for it: the only corner
							     with nothing burning near the quiet zone, and outside the block of
							     squares the four alignment handles get dragged onto. Drawn at the
							     size it really is, so a code that eats a third of the board looks
							     like it. -->
							<div class="codestrip" class:naast={form.text}>
								<div
									class="qr"
									style="--zij: {Number(preview.plan.code_size_mm) * scale}px;"
									title={t('grid.code.name', { name: preview.plan.code_human ?? '' })}
								></div>
							</div>
						{/if}
					</div>
					</div>

					{#if preview.plan.board_room === false}
						<!-- The board starts outside the bed on the left or the top. That is
						     nearly always down to the row labels: they are engraved left of the
						     grid and are as wide as their longest value. With the centre as the
						     anchor you cannot work that out yourself, so the number is here. -->
						<p class="krap">
							<!-- The position the engine measured this on, and with a cut-out that is
							     the *cut* rectangle and not the board (`board_room = cut_x >= 0 and
							     cut_y >= 0`, testgrid.py:748). Measured on the default form with a
							     cut-out: the board starts at 2.4 mm and fits, while the cut runs to
							     −1.6 mm and does not — so naming the board's own corner here would
							     be a warning pointing at a number that looks fine. -->
							<!-- Both numbers carry their unit: in Dutch the decimal mark *is* a comma,
							     and "−1,6, 3,5 mm" is two numbers that read as four. -->
							{t('grid.tooFar', {
								position: `${mm(preview.plan.cut_x_mm)}, ${mm(preview.plan.cut_y_mm)}`
							})}
							{#if cutMarginMm !== null}
								{t('grid.tooFar.cut', { margin: lengte(cutMarginMm) })}
							{/if}
							{#if preview.plan.label_room === false}
								{t('grid.tooFar.labels', { mm: Math.ceil(preview.plan.label_margin_mm ?? 0) })}
							{/if}
							{t('grid.tooFar.move', {
								anchor: t(
									form.anchor === 'center' ? 'grid.anchor.centreWord' : 'grid.anchor.startWord'
								),
								orText: form.text ? t('grid.tooFar.orText') : ''
							})}
						</p>
					{/if}

					<p class="legenda">
						{t('grid.legend.rows', {
							axis: axisLabel(form.row_axis).toLowerCase(),
							unit: AXIS_UNIT[form.row_axis]
						})}
						{t('grid.legend.columns', { axis: axisLabel(form.column_axis).toLowerCase() })}
						{#each vasteAs as as (as)}
							{t('grid.legend.fixed', {
								axis: axisLabel(as),
								value: show(as, Number(form[VAST_VELD[as]]))
							})}
						{/each}
						{deepestCorner
							? t('grid.legend.deepest', { corner: deepestCorner })
							: t('grid.legend.darker')}
					</p>
				</aside>
			{/if}
		</div>

		{#if suggestedFrom !== null}
			<p class="muted">
				{suggestedFrom
					? t('grid.suggested', { n: suggestedFrom })
					: t('grid.suggested.none')}
			</p>
		{/if}

		{#if error}<p class="error" role="alert">{error}</p>{/if}

		{#if done}
			<!-- Gap T1: this is where the wizard used to stop, leaving you with a drawn
			     grid on the canvas and no hint how to burn it. Frame first, then start —
			     the same order as in the control panel, and the same APIs. -->
			<div class="done" role="status">
				<p>
					<strong>{t('grid.done.title', { id: done.id })}</strong>
					{t('grid.done.body', { cells: done.cellen })}
				</p>
				<div class="branden">
					<button
						class="btn"
						disabled={naarMachine === 'frame'}
						title={naarMachine === 'frame' ? t('reason.busy') : undefined}
						onclick={() => machineActie('/api/machine/frame', 'frame', 'frame-ready')}
					>
						{naarMachine === 'frame' ? t('grid.frameRunning') : t('job.frame')}
					</button>
					<button
						class="btn primary"
						disabled={naarMachine === 'start'}
						title={naarMachine === 'start' ? t('reason.busy') : undefined}
						onclick={() => machineActie('/api/job/start', 'start', 'start-ready')}
					>
						{naarMachine === 'start' ? t('grid.starting') : t('job.startJob')}
					</button>
				</div>
				{#if naarMachine === 'frame-ready'}
					<p class="nagekomen">{t('grid.frameDone')}</p>
				{:else if naarMachine === 'start-ready'}
					<p class="nagekomen">{t('grid.startDone')}</p>
				{/if}
				{#if machineLet}<p class="nagekomen">{t('grid.watchOut', { what: machineLet })}</p>{/if}
				{#if machineError}<p class="failure" role="alert">{machineError}</p>{/if}
			</div>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} title={busy ? t('reason.busy') : undefined} onclick={suggest}>{t('grid.suggestRange')}</button>
			<!-- Form rule v4: the primary button is on the right, the helper on the left.
			     They used to sit next to each other on the left, and then the button that
			     goes into the wood is as prominent as the one that suggests a number. -->
			<span class="stretch"></span>
			<!-- E4: without a material this stays an ordinary button. It works — sometimes
			     you *do* want to burn a board without getting a preset out of it — but it
			     does not promise that this is the intended route. -->
			<!-- Once a grid is there, starting is the next step and not yet another grid.
			     Two equally bright buttons side by side make you choose between two things
			     of which only one is at issue. The button on a burned board does not draw,
			     it puts you back at the settings: a second board would otherwise fall on
			     the first. -->
			{#if done}
				<button class="btn" onclick={again}>{t('grid.another')}</button>
			{:else}
				<button
					class="btn"
					class:primary={!noMaterial}
					disabled={busy || !preview || previewError !== null}
				title={busy ? t('reason.busy') : (previewError ?? t('reason.noneYet'))}
					onclick={generate}
				>
					{#if busy}
						{t('common.busy')}
					{:else if previewError}
						{t('grid.draw')}
					{:else if noMaterial}
						{t('grid.drawAnyway')}
					{:else if preview}
						{t('grid.drawWith', {
							cells: preview.cells.length,
							size: `${number(preview.plan.outer_width_mm ?? preview.plan.width_mm)} × ${number(
								preview.plan.outer_height_mm ?? preview.plan.height_mm
							)} mm`
						})}
					{:else}
						{t('grid.draw')}
					{/if}
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.wizard { display: grid; gap: var(--space-3); }

	.steps {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.steps li {
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.steps li + li::before {
		content: '';
		width: 12px;
		height: 1px;
		background: var(--line);
		margin-right: var(--space-1h);
	}
	.steps .nr {
		display: grid;
		place-items: center;
		width: 18px;
		height: 18px;
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.steps li.now { color: var(--text-1); font-weight: 600; }
	.steps li.now .nr {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}

	.lead { margin: 0; font-size: var(--text-sm); color: var(--text-1); max-width: 62ch; }
	.muted { color: var(--text-2); margin: 0; font-size: var(--text-xs); }

	/* Form rule v4: the form is a stack of rows, not a continuous two-column grid. In
	   that grid every field fell into the next free slot, and so "Speed from" sat
	   beside "Columns, to the right" with "to" on the row below — two fields that are
	   one value, pulled apart diagonally. Now the markup decides what belongs
	   together: `.pair` puts exactly two fields side by side, everything else is on a
	   row of its own. See DESIGN-SYSTEM v4, "Forms". */
	.grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		align-content: start;
	}
	.paar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: end;
	}
	.field { display: grid; gap: 4px; }
	.name { font-size: var(--text-xs); color: var(--text-2); }
	/* An axis is one statement: from, to and the number of steps belong in one framed
	   block, because loose in the flow they read as three separate numbers. */
	.asblok {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.asblok legend { padding: 0 4px; }
	.hint { font-size: var(--text-xs); color: var(--text-2); }
	select, input[type='text'] {
		font: inherit;
		font-size: var(--text-sm);
		width: 100%;
		box-sizing: border-box;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}

	.waarschuwing {
		grid-column: 1 / -1;
		display: grid;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.waarschuwing p { margin: 0; }
	/* A board that comes out of the machine blank is not a point of attention but a
	   wasted plate: that message gets the danger colour. */
	.waarschuwing.ernstig {
		/* Back to one text block: the shared frame is a grid, and then every word
		   between two <strong>s becomes a row of its own. */
		display: block;
		border-left-color: var(--danger-solid, var(--danger));
		background: color-mix(in srgb, var(--danger-solid, var(--danger)) 12%, transparent);
	}
	/* The way out is in the warning itself: type one line and you are out, without
	   opening the library and losing this dialog. */
	.erbij { display: flex; gap: var(--space-2); flex-wrap: wrap; }
	.erbij input { flex: 1; min-width: 12rem; }
	.failure { color: var(--danger-solid, var(--danger)); }

	/* What worked last time comes back — but visibly, because otherwise the form
	   changes under your hands without you knowing why. */
	.overgenomen {
		grid-column: 1 / -1;
		margin: 0;
		padding: var(--space-1h) var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}

	/* The recipe bar: one row at the top, as in LightBurn. Choosing is the main
	   action, saving sits beside it and only opens when you ask for it — otherwise the
	   first thing you see is an empty name field. */
	.recepten {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-2) var(--space-3);
		align-items: end;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.recepten .erbij,
	.recepten .hint,
	.recepten .failure { grid-column: 1 / -1; }
	.receptknoppen { display: flex; gap: var(--space-2); }
	/* Deleting is quiet: it is there in case you need it, not as a suggestion beside
	   the button you actually have to use. */
	.btn.quiet { border-color: transparent; background: transparent; color: var(--text-2); }
	.btn.quiet:hover:not(:disabled) { background: var(--surface-1); color: var(--text-1); }

	/* Two switches that belong together: a fieldset, because they share one question
	   ("what else goes on the board"). */
	.schakelaars {
		grid-column: 1 / -1;
		display: grid;
		gap: var(--space-1h);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.schakelaars legend { padding: 0 var(--space-1); }
	.vink {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--text-1);
	}
	.schakelaars .hint { margin: 0; max-width: 52ch; }
	/* What a switch needs once it is on, indented under it so it reads as belonging to
	   that switch and not to the fieldset. */
	.uitleg {
		display: grid;
		gap: var(--space-1h);
		margin-left: calc(var(--space-2) + 1em);
		max-width: 52ch;
	}
	.schakelaars .krap { margin: 0; max-width: 52ch; }

	/* Setting up and seeing what you set, side by side. Below 720px it stacks. The
	   preview column has a fixed width instead of `auto`: with `auto` it followed the
	   width of the board, so it changed along with the labels ("5" against "12.5
	   mm/s") and the form beside it slid back and forth while typing. Measured:
	   274 → 304 px for one extra digit. */
	.werkbank {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 292px;
		gap: var(--space-4);
		align-items: start;
	}
	@media (max-width: 720px) {
		.werkbank { grid-template-columns: 1fr; }
		.grid { grid-template-columns: 1fr; }
		.preview { position: static; }
	}

	.preview {
		/* Watching along while you fiddle. With the position choice and the switches
		   the form has become longer than the dialog: anybody choosing "from the
		   centre" at the bottom no longer saw the preview in which that difference is
		   visible. Above 720px, because below that the preview sits *below* the form
		   and sticking would mean it covers the fields. */
		position: sticky;
		top: 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	/* The reason the preview is briefly not keeping up. A calm notice and not an
	   alarm: this is an intermediate state while typing, not a failure. */
	.unfinished {
		margin: 0 0 var(--space-2);
		padding: var(--space-1h) var(--space-2);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.unfinished .quiet { color: var(--text-2); }

	.figures {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
		margin-bottom: var(--space-2);
	}

	/* The preview is in pixels, not in millimetres: labels inside a mm viewBox come
	   out a factor of ten too large. See DESIGN-SYSTEM v3. */
	.board {
		display: grid;
		grid-template-columns: auto auto;
		grid-template-rows: auto auto;
		gap: 4px;
	}
	/* Without a caption there is no label column either: then the board is exactly the
	   squares, and that is what the preview should show. */
	.board.kaal { grid-template-columns: auto; grid-template-rows: auto; }
	/* The border as it burns: around everything, with the same gap in between that the
	   generator keeps. */
	.board.frame {
		padding: var(--space-2);
		border: 1px solid var(--text-2);
		border-radius: var(--radius-sharp);
	}
	/* The cut, drawn where it runs: `--rim` millimetres outside everything the board
	   burns, in the preview's own scale. Dashed rather than solid, because the engraved
	   frame is the solid line here and this one is interrupted for real — four bridges
	   hold the tile in the sheet until you break it out. */
	.tile { display: inline-block; }
	.tile.cutting {
		padding: var(--rim);
		border: 1px dashed var(--text-2);
		border-radius: var(--radius-sharp);
	}
	/* The strip the board grows below the squares for its code. Right-aligned with the
	   squares, which is where the generator puts it. */
	.codestrip { display: flex; justify-content: flex-end; }
	.codestrip.naast { grid-column: 2; }
	.qr {
		width: var(--zij);
		height: var(--zij);
		/* Not an attempt at the pattern: at this scale a 29-module code is a grey smudge,
		   and a fake pattern would suggest the preview knows what will be burned. What it
		   does know is the footprint, and that is what is drawn. */
		background:
			repeating-conic-gradient(
				from 0deg at 50% 50%,
				var(--void) 0deg 90deg,
				transparent 90deg 180deg
			);
		background-size: 25% 25%;
		background-color: var(--mat-wood);
		outline: 1px solid var(--line);
	}
	.koplabels, .zijlabels { display: grid; gap: var(--gat); }
	.koplabels { grid-auto-flow: column; grid-auto-columns: var(--cel); }
	.zijlabels { grid-auto-rows: var(--cel); }
	.as {
		font-size: var(--text-xs);
		color: var(--text-2);
		display: grid;
		place-items: center;
		overflow: hidden;
	}
	.zijlabels .as { justify-items: end; padding-right: 2px; }
	.cells { display: grid; gap: var(--gat); }
	/* The board is wood and the cut is soot: the same tones the material card uses, so
	   that the preview *reads* as the board that will be on the table rather than as a
	   bar chart. */
	.cell {
		width: var(--cel);
		height: var(--cel);
		background: color-mix(in srgb, var(--void) calc(var(--burn) * 88%), var(--mat-wood));
	}
	.cells {
		padding: var(--space-1);
		background: var(--mat-wood);
		border-radius: var(--radius-field);
	}
	.kosten {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.krap {
		margin: var(--space-2) 0 0;
		padding: var(--space-1h) var(--space-2);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		max-width: 24ch;
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.legenda {
		margin: var(--space-2) 0 0;
		max-width: 24ch;
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	/* The button from step 1 has to stay on screen. In an 80vh dialog with twelve
	   fields above it, it disappeared below the fold, and then the wizard looks like a
	   dead end. */
	.actions .stretch { flex: 1; }
	.actions {
		position: sticky;
		bottom: 0;
		z-index: 1;
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: 0 calc(-1 * var(--space-4));
		padding: var(--space-3) var(--space-4);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
	}
	/* Without this rule the general hover beats .primary: on hover the button went
	   light grey with white text. Same specificity, later in the stylesheet — a
	   classic. */
	/* A disabled primary button must not look like a button that works: 45% accent
	   still reads as "click me" in the dark theme. */
	.btn.primary:disabled {
		background: var(--surface-2);
		border-color: var(--line);
		color: var(--text-2);
		opacity: 1;
	}
	.error, .done {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.error { background: color-mix(in srgb, var(--danger-solid, var(--danger)) 14%, transparent); }
	.done {
		display: grid;
		gap: var(--space-2);
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-left: 3px solid var(--ok);
	}
	.done p { margin: 0; }
	.branden { display: flex; gap: var(--space-2); flex-wrap: wrap; }
	/* The start button should be the largest in this block, but not so large that it
	   starts imitating the sticky main button below it. */
	.branden .btn { flex: 1; min-width: 10rem; }
	.nagekomen { color: var(--text-2); }
</style>
