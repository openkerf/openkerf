<script lang="ts">
	/**
	 * What gets burned, right before you press start (decision B8).
	 *
	 * The canvas is not next to it on tablet and phone, and on the desktop you
	 * stop looking at it just before starting anyway. This is the last moment at
	 * which a wrong layer, a forgotten shape or something hanging over the edge of
	 * the sheet still costs nothing.
	 *
	 * Deliberately no cut order: that needs the full cut plan, and building that
	 * plan is precisely why the preflight used to stall for minutes (gap J1).
	 * See BESLISSINGEN.md, B8.
	 */
	import type { Design } from '$lib/design.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';

	/** The drawing at full size, in a window of its own. */
	let large = $state(false);

	// An SVG pattern has an id, and two views on one page must not carry the same
	// one — the second would then pick up the first one's pattern.
	const ownId = $props.id();

	/**
	 * What the server reports about the limits (gap C2).
	 *
	 * The measurement comes from `/api/job/layers`, the same one the canvas and
	 * the phone use. Redoing it here would mean two places could come to disagree
	 * about whether something still just fits — and then neither can be trusted.
	 */
	type BoundsReport = {
		bed: { width_mm: number; height_mm: number } | null;
		sheet: { width_mm: number; height_mm: number } | null;
		work: { x_mm: number; y_mm: number; width_mm: number; height_mm: number } | null;
		outside_bed: number;
		outside_sheet: number;
		outside_bed_ids: string[];
		outside_sheet_ids: string[];
	};

	let {
		design,
		sheet,
		bounds = null,
		colorFor
	}: {
		design: Design | null;
		/** The sheet being burned on; without a sheet it falls back to the work itself. */
		sheet: { name: string; width_mm: number; height_mm: number } | null;
		bounds?: BoundsReport | null;
		colorFor?: (operationId: string | null) => string;
	} = $props();

	const GREY = 'var(--text-2)';

	/** Layers that burn along. A layer with "burn along" off does not belong here:
	 *  that is exactly the difference this view has to make visible. */
	let burning = $derived(
		new Set((design?.operations ?? []).filter((o) => o.output).map((o) => o.id))
	);

	type Shape = {
		id: string;
		path: string;
		image: { x: number; y: number; w: number; h: number } | null;
		colour: string;
		/** Sits in no burning layer: will not be burned. */
		silent: boolean;
		/** Sticks out beyond the sheet: there is no material there. */
		offSheet: boolean;
		/** Lies outside the bed: the head does not even reach it. */
		offBed: boolean;
	};

	let perMm = $derived(design?.units_per_mm ?? 1);

	// The server's measurement, when there is one. Without `bounds` (while the
	// overview is still loading, say) it falls back to the sheet edge it can see
	// for itself; it does not know the bed then, and so does not report it either.
	let bedIds = $derived(new Set(bounds?.outside_bed_ids ?? []));
	let sheetIds = $derived(new Set(bounds?.outside_sheet_ids ?? []));

	let shapes = $derived.by<Shape[]>(() => {
		if (!design) return [];
		return design.elements
			.filter((element) => !element.hidden)
			.map((element) => {
				const layers = (element.operation_ids ?? []).filter((id) => burning.has(id));
				const box = element.bounds;
				const seenOffSheet = Boolean(
					sheet &&
						box &&
						(box[0] / perMm < -0.05 ||
							box[1] / perMm < -0.05 ||
							box[2] / perMm > sheet.width_mm + 0.05 ||
							box[3] / perMm > sheet.height_mm + 0.05)
				);
				const offBed = bounds ? bedIds.has(element.id) : false;
				return {
					id: element.id,
					path: element.path,
					image: element.image
						? {
								x: element.image.x_mm * perMm,
								y: element.image.y_mm * perMm,
								w: element.image.width_mm * perMm,
								h: element.image.height_mm * perMm
							}
						: null,
					colour: layers.length ? (colorFor?.(layers[0]) ?? GREY) : GREY,
					silent: layers.length === 0,
					// Outside the bed is the heavier of the two, so it wins: a shape
					// that falls outside both is one the machine cannot reach. Two
					// marks over one shape say nothing extra.
					offSheet: (bounds ? sheetIds.has(element.id) : seenOffSheet) && !offBed,
					offBed
				};
			});
	});

	let offSheetCount = $derived(shapes.filter((s) => s.offSheet).length);
	let offBedCount = $derived(shapes.filter((s) => s.offBed).length);
	let silentCount = $derived(shapes.filter((s) => s.silent).length);
	let burningCount = $derived(shapes.filter((s) => !s.silent).length);

	/**
	 * The frame the view looks into, in millimetres.
	 *
	 * The sheet plus everything that falls outside it: someone with a shape
	 * hanging over the edge has to see that shape lying there, not just its
	 * absence.
	 */
	let frame = $derived.by(() => {
		let x0 = 0;
		let y0 = 0;
		let x1 = sheet?.width_mm ?? 0;
		let y1 = sheet?.height_mm ?? 0;
		for (const element of design?.elements ?? []) {
			if (element.hidden || !element.bounds) continue;
			const [a, b, c, d] = element.bounds;
			x0 = Math.min(x0, a / perMm);
			y0 = Math.min(y0, b / perMm);
			x1 = Math.max(x1, c / perMm);
			y1 = Math.max(y1, d / perMm);
		}
		if (x1 <= x0 || y1 <= y0) return null;
		// A little air around it, so a shape lying exactly on the edge is not
		// stuck against the side of the frame.
		const margin = Math.max(x1 - x0, y1 - y0) * 0.04;
		return {
			x: x0 - margin,
			y: y0 - margin,
			w: x1 - x0 + 2 * margin,
			h: y1 - y0 + 2 * margin
		};
	});

	/**
	 * How big the work itself is, in millimetres.
	 *
	 * Without a size the view is a picture: you see that something lies tight, but
	 * not whether it fits. This is the number you hold up against your offcut.
	 */
	let work = $derived.by(() => {
		let x0 = Infinity;
		let y0 = Infinity;
		let x1 = -Infinity;
		let y1 = -Infinity;
		for (const element of design?.elements ?? []) {
			if (element.hidden || !element.bounds) continue;
			const [a, b, c, d] = element.bounds;
			x0 = Math.min(x0, a);
			y0 = Math.min(y0, b);
			x1 = Math.max(x1, c);
			y1 = Math.max(y1, d);
		}
		if (!Number.isFinite(x0)) return null;
		return { w: (x1 - x0) / perMm, h: (y1 - y0) / perMm };
	});

	/** One sentence saying what you see, for whoever does not get the image. */
	let description = $derived.by(() => {
		if (!frame) return t('preview.nothingOnSheet');
		const parts = [t('preview.shapesBurn', { n: burningCount })];
		if (sheet)
			parts.push(
				t('preview.onSheet', {
					name: sheet.name,
					width: size(sheet.width_mm),
					height: size(sheet.height_mm)
				})
			);
		if (offBedCount) parts.push(t('preview.countOutsideBed', { n: offBedCount }));
		if (offSheetCount) parts.push(t('preview.countOutsideSheet', { n: offSheetCount }));
		if (silentCount) parts.push(t('preview.countNoLayer', { n: silentCount }));
		return parts.join('; ') + '.';
	});

	// Whole millimetres, in the reader's own notation: 1.234 in English, 1.234 in
	// Dutch too for a thousand, but 3,5 versus 3.5 the moment a decimal appears.
	// `Intl` is the only place that knows which, so it does the writing.
	function size(value: number) {
		return i18n.number(Math.round(value), 0);
	}

	/**
	 * Outside the sheet is hatched, not coloured differently.
	 *
	 * Measured: `--bed` and `--surface-2` are exactly the same colour in the dark
	 * theme (1.00:1) and 1.14:1 in the light one. No existing token gets past
	 * 1.23:1 against `--bed`, so with a flat colour "there is no material here" is
	 * simply invisible in the dark. Hatching is also the common language for it in
	 * CAM software, and it works for colour blindness.
	 */
	const hatchId = `ok-hatch-${ownId}`;
	// The hatching is in millimetres, like the rest of the view; the step scales
	// with the frame so it looks equally fine at any size.
	let step = $derived(frame ? Math.max(frame.w, frame.h) / 45 : 1);
</script>

<!-- The same drawing twice: small in the panel, large in the window. The pattern
     id has to differ per copy, or the second points at the first one's pattern
     and the hatching disappears as soon as the first is gone. -->
{#snippet drawing(key: string)}
	{@const pattern = `${hatchId}-${key}`}
	{#if frame}
		<svg
			viewBox="{frame.x} {frame.y} {frame.w} {frame.h}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-label={description}
		>
			<!-- The sheet. The view measures in millimetres, so every length here is
			     one; edges get non-scaling-stroke, otherwise the line scales with
			     the sheet and is invisible on a large one. -->
			{#if sheet}
				<defs>
					<pattern
						id={pattern}
						patternUnits="userSpaceOnUse"
						width={step}
						height={step}
						patternTransform="rotate(45)"
					>
						<line class="hatch" x1={step / 2} y1="0" x2={step / 2} y2={step} />
					</pattern>
				</defs>
				<!-- Everything outside the sheet: hatched, because there is no
				     material there. -->
				<rect
					x={frame.x}
					y={frame.y}
					width={frame.w}
					height={frame.h}
					fill="url(#{pattern})"
				/>
				<rect
					class="sheet"
					class:overhang={offSheetCount > 0}
					x="0"
					y="0"
					width={sheet.width_mm}
					height={sheet.height_mm}
				/>
			{/if}

			<!-- The bed edge, only when something falls outside it. Otherwise it is a
			     big box around a small sheet: noise. When something does fall
			     outside, a red shape without a visible boundary is a riddle — you
			     see that something is wrong, not what against. -->
			{#if offBedCount && bounds?.bed}
				<rect
					class="bededge"
					x="0"
					y="0"
					width={bounds.bed.width_mm}
					height={bounds.bed.height_mm}
				/>
			{/if}

			<!-- The work itself. One scale transform converts Tats to mm, exactly as
			     the canvas does it; the path data stays as the engine gave it. -->
			<g transform="scale({1 / perMm})">
				{#each shapes as shape (shape.id)}
					{#if shape.image}
						<image
							href="/api/design/elements/{encodeURIComponent(shape.id)}/image.png"
							x={shape.image.x}
							y={shape.image.y}
							width={shape.image.w}
							height={shape.image.h}
							preserveAspectRatio="none"
							opacity={shape.silent ? 0.35 : 1}
						/>
					{:else if shape.path}
						<path
							d={shape.path}
							class="shape"
							class:silent={shape.silent}
							class:offsheet={shape.offSheet}
							class:offbed={shape.offBed}
							style:stroke={shape.offBed
								? 'var(--danger-solid)'
								: shape.offSheet
									? 'var(--warn-solid)'
									: shape.colour}
						/>
					{/if}
				{/each}
			</g>
		</svg>
	{/if}
{/snippet}

{#if frame}
	<div class="pf-beeld">
		<!-- Small in the panel, large on request. LightBurn gives its preview a
		     whole window; a 220 px strip is too little for a mistake you can only
		     still catch here. -->
		<button
			class="enlarge"
			onclick={() => (large = true)}
			aria-label={t('preview.viewLargerAria', { description })}
			title={t('preview.bigger')}
		>
			{@render drawing('small')}
		</button>

		<!-- The sizes underneath, because the view itself has no scale: you see
		     that something lies tight, not whether it fits. This is also the number
		     you hold up against an offcut. -->
		<p class="sizes">
			{#if sheet}<span
					>{sheet.name}
					<span class="mono">{size(sheet.width_mm)} × {size(sheet.height_mm)} mm</span></span
				>{/if}
			{#if work}<span
					>{t('preview.work')}
					<span class="mono">{size(work.w)} × {size(work.h)} mm</span></span
				>{/if}
		</p>

		<!-- What the image says, in words. A red line you overlook is not a
		     warning; and whoever is standing in the sun with a phone is the first
		     to lose colour differences. -->
		<!-- Outside the bed comes first and is red; outside the sheet below it and
		     amber. That is not a matter of taste but the order in which it goes
		     wrong: outside the sheet costs you material, outside the bed the head
		     does not even get there — the machine stalls or runs into its end
		     stop. Two equally red cards in a row (as it was) make those two
		     equally bad, and then neither carries any weight. -->
		{#if offBedCount}
			<p class="notice offbed" role="alert">
				<strong>{t('preview.outsideBed.title')}</strong>
				{t('preview.outsideBed.body', {
					n: offBedCount,
					reach: bounds?.bed
						? t('preview.reach', {
								width: size(bounds.bed.width_mm),
								height: size(bounds.bed.height_mm)
							})
						: ''
				})}
			</p>
		{/if}
		{#if offSheetCount}
			<p class="notice offsheet">
				{t('preview.outsideSheet', {
					n: offSheetCount,
					sheet: sheet ? sheet.name : t('preview.sheetFallback')
				})}
			</p>
		{/if}
		{#if silentCount}
			<p class="notice silent">{t('preview.silent', { n: silentCount })}</p>
		{/if}
	</div>

	<Dialog title={t('preview.whatBurns')} bind:open={large} width="960px">
		<div class="large">
			{@render drawing('large')}
			<p class="sizes">
				{#if sheet}<span
						>{sheet.name}
						<span class="mono">{size(sheet.width_mm)} × {size(sheet.height_mm)} mm</span></span
					>{/if}
				{#if work}<span
						>{t('preview.work')}
						<span class="mono">{size(work.w)} × {size(work.h)} mm</span></span
					>{/if}
			</p>
		</div>
	</Dialog>
{/if}

<style>
	.pf-beeld {
		margin: 0 0 var(--space-3);
	}
	/* The button is the drawing itself; it must not look like a button, but it
	   does have to be focusable and say that something happens when you touch it. */
	.enlarge {
		display: block;
		width: 100%;
		padding: 0;
		border: none;
		background: none;
		border-radius: var(--radius-field);
		cursor: zoom-in;
	}
	.enlarge:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.large :global(svg) {
		max-height: 66vh;
	}
	svg {
		display: block;
		width: 100%;
		/* Without a ceiling an upright sheet in a narrow panel becomes a tower and
		   the time estimate below it drops off the screen. `meet` makes sure the
		   image never distorts doing so; at most there is air beside it. */
		max-height: 30vh;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	/* Fine enough to stay background, strong enough to still read as hatching on a
	   221 px view. On `--line` it managed 1.41:1 (light) and 1.44:1 (dark) against
	   the sheet — measured, and that is too little. */
	.hatch {
		stroke: color-mix(in srgb, var(--text-2) 45%, transparent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
	}
	/* The edge of the sheet is where your material stops; that is a boundary, not
	   a divider. `--line` got 1.41:1 (light) / 1.44:1 (dark) there, well under the
	   3:1 WCAG 1.4.11 asks of a graphical object; `--text-2` gets 6.00:1 and
	   5.65:1. */
	.sheet {
		fill: var(--bed);
		stroke: var(--text-2);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
	}
	/* If something sticks out over the edge, the edge is the subject. Amber and
	   not red: the sheet is a piece of material that has run out, not a boundary
	   the machine cannot reach. That last one is the bed edge below. */
	.sheet.overhang {
		stroke: var(--warn-solid);
		stroke-width: 2;
	}
	/* Where the machine stops. Red and dashed: two codes for one boundary, because
	   on a small image hue alone is too little — and with deuteranopia red and
	   amber sit right next to each other. */
	.bededge {
		fill: none;
		stroke: var(--danger-solid);
		stroke-width: 2;
		stroke-dasharray: 10 6;
		vector-effect: non-scaling-stroke;
	}
	.shape {
		fill: none;
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	/* Sits in no layer: will not be burned. Dotted grey, the same language as on
	   the canvas — there it already means "this shape does not take part". */
	.shape.silent {
		stroke: var(--text-2);
		stroke-dasharray: 4 3;
		stroke-width: 1;
	}
	/* Outside the sheet: amber and broken. A longer dash than the one for
	   `silent` (4 3), so that "does not take part" and "lies next to your
	   material" do not carry the same pattern on one image. */
	.shape.offsheet {
		stroke-width: 2.5;
		stroke-dasharray: 9 4;
	}
	/* Outside the bed: red and solid. The heaviest of the three gets the calmest
	   line — it does not need to suggest anything, it is simply wrong. */
	.shape.offbed {
		stroke-width: 3;
	}
	/* Two sizes side by side when they fit, stacked when they do not — in a 220px
	   panel they do not, and then aligning left is calmer than a second line stuck
	   against the right edge. */
	.sizes {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-1) var(--space-3);
		margin-top: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.sizes .mono {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.notice {
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		line-height: 1.45;
	}
	.notice.offsheet,
	.notice.offbed {
		color: var(--text-1);
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
	}
	.notice.offbed {
		border-left: 4px solid var(--danger-solid);
		background: color-mix(in srgb, var(--danger) 18%, transparent);
	}
	.notice.offsheet {
		border-left: 4px solid var(--warn-solid);
		background: color-mix(in srgb, var(--warn) 18%, transparent);
	}
	.notice.silent {
		color: var(--text-2);
	}
</style>
